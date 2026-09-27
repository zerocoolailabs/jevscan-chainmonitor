"""The TypeSafe classifier client: a pinned Jev model, validated answers, and conservative spending accounting.

The local dollar ceiling uses a documented price assumption, not a provider-side
billing guarantee. Apply provider account quotas as the ultimate spending limit.
"""

import asyncio
import fcntl
import hashlib
import json
import math
import os
import re
import uuid
from pathlib import Path

import aiohttp

from jevscan_chainmonitor.workspace import atomic_json

API_URL = "https://api.typesafe.ai/v1/systemone"
USD_PER_MILLION_TOKENS = 0.042
RESERVED_TOKENS = 55_000
MAX_REQUEST_BYTES = 48_000
MAX_RESPONSE_BYTES = 1_000_000
MAX_ATTEMPTS = 3
# The service refused the request or a gateway failed before it was answered. Each attempt keeps its own reservation,
# so a retry can never make the local budget optimistic. A timeout or malformed answer is not retried.
RETRY_STATUSES = {429, 502, 503, 504, 520, 521, 522, 523, 524}


def encode(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def score_number(value: object) -> float:
    if type(value) not in (int, float) or not 0 <= value <= 1 or not math.isfinite(value):
        raise ValueError("Provider score must be a finite number between zero and one")
    return float(value)


def validate_response(payload: object, model: str, questions: dict) -> tuple[dict[str, float], int]:
    if not isinstance(payload, dict) or payload.get("model") != model:
        raise ValueError("Provider returned an incompatible model or response")
    usage, answers = payload.get("usage"), payload.get("answers")
    if not isinstance(usage, dict) or type(usage.get("input_tokens")) is not int:
        raise ValueError("Provider returned invalid token accounting")
    tokens = usage["input_tokens"]
    if not 0 <= tokens <= RESERVED_TOKENS:
        raise ValueError("Provider token accounting exceeds the request reservation")
    if not isinstance(answers, dict) or set(answers) != set(questions):
        raise ValueError("Provider answer keys differ from the requested questions")
    scores = {}
    for name, answer in answers.items():
        if not isinstance(answer, dict) or "noul" not in answer:
            raise ValueError("Provider returned an invalid classification answer")
        scores[name] = score_number(answer["noul"])
    return scores, tokens


def ledger_total(rows: list[dict]) -> float:
    reservations = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            raise ValueError("Invalid spending ledger; refusing new paid calls")
        identity, kind = row["id"], row.get("kind")
        tokens = row.get("tokens")
        if type(tokens) is not int or not 0 <= tokens <= RESERVED_TOKENS:
            raise ValueError("Invalid spending ledger amount")
        if kind == "reserve" and identity not in reservations and tokens == RESERVED_TOKENS:
            reservations[identity] = (tokens, False)
        elif kind == "settle" and identity in reservations and not reservations[identity][1]:
            reservations[identity] = (tokens, True)
        else:
            raise ValueError("Invalid spending ledger transition")
    return sum(tokens for tokens, _ in reservations.values()) * USD_PER_MILLION_TOKENS / 1_000_000


class Refused(RuntimeError):
    """The classifier refused the request, or a gateway failed, before it was answered."""


class TypeSafeClassifier:
    """Paid client for one workspace: a pinned model, and retries only for refusals and gateway failures.

    Requests may run concurrently. Each one reserves RESERVED_TOKENS in the durable spending ledger before it is sent,
    and the budget check and the reservation happen with no await between them, so concurrent requests can never
    overspend. Identical requests in flight at the same time are sent once."""

    def __init__(self, workspace: Path, model: str, budget_usd: float):
        if not re.fullmatch(r"jev-\d+\.\d+\.\d+", model):
            raise ValueError("A pinned Jev model version, such as jev-1.13.0, is required")
        if type(budget_usd) not in (int, float) or not math.isfinite(budget_usd) or budget_usd <= 0:
            raise ValueError("A positive finite workspace budget is required")
        self.workspace, self.model, self.budget_usd = workspace, model, budget_usd
        self.requests = 0
        self.cache_hits = 0
        self.billed_tokens = 0
        self.inflight: dict[str, asyncio.Future] = {}

    async def __aenter__(self):
        self.workspace.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = (self.workspace / "spend.lock").open("a+")
        try:
            try:
                fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError(f"Another scoring run is using {self.workspace}") from None
            self.ledger_path = self.workspace / "spend.jsonl"
            self.rows = ([json.loads(line) for line in self.ledger_path.read_text().splitlines()]
                         if self.ledger_path.exists() else [])
            self.spent_usd = ledger_total(self.rows)
            self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120))
            return self
        except BaseException:
            self.lock.close()
            raise

    async def __aexit__(self, *exc):
        try:
            await self.session.close()
        finally:
            self.lock.close()

    def append(self, row: dict) -> None:
        with self.ledger_path.open("a") as stream:
            stream.write(encode(row).decode() + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        directory = os.open(self.ledger_path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        self.rows.append(row)

    async def classify(self, state: dict, questions: dict, *, input_version: int) -> dict[str, float]:
        if not isinstance(state, dict) or not questions or any(q.get("type") != "noul" for q in questions.values()):
            raise ValueError("Only nonempty Noul question bundles and object states are supported")
        body = {"model": self.model, "state": state, "questions": questions}
        encoded = encode(body)
        if len(encoded) > MAX_REQUEST_BYTES:
            raise ValueError("Input exceeds the paid request size limit; transaction not evaluated")
        identity = hashlib.sha256(encode({"request": body, "input_version": input_version})).hexdigest()
        cache = self.workspace / "answers" / f"{identity}.json"
        if cache.exists():
            if cache.stat().st_size > MAX_RESPONSE_BYTES or cache.is_symlink():
                raise ValueError("Cached answer exceeds the size limit or is a symlink")
            payload = json.loads(cache.read_text())
            if not isinstance(payload, dict) or payload.get("request_sha256") != identity:
                raise ValueError("Cached request identity mismatch")
            scores, _ = validate_response(payload, self.model, questions)
            self.cache_hits += 1
            return scores
        if identity in self.inflight:
            self.cache_hits += 1
            return await asyncio.shield(self.inflight[identity])
        future = asyncio.get_running_loop().create_future()
        self.inflight[identity] = future
        try:
            scores = await self.send(encoded, questions, identity, cache)
        except BaseException as error:
            if isinstance(error, asyncio.CancelledError):
                future.cancel()
            else:
                future.set_exception(error)
                future.exception()  # mark it retrieved: this caller reports the failure
            raise
        finally:
            del self.inflight[identity]
        future.set_result(scores)
        return scores

    async def send(self, encoded: bytes, questions: dict, identity: str, cache: Path) -> dict[str, float]:
        key = os.environ.get("TYPESAFE_API_KEY")
        if not key:
            raise RuntimeError("TYPESAFE_API_KEY is not set")
        for attempt in range(MAX_ATTEMPTS):
            try:
                scores, tokens = await self.post(key, encoded, questions)
                break
            except Refused:
                if attempt == MAX_ATTEMPTS - 1:
                    raise
                await asyncio.sleep(2**attempt)
        # Persist only validated fields, never the raw provider response body.
        atomic_json(cache, {"request_sha256": identity, "model": self.model,
                            "usage": {"input_tokens": tokens},
                            "answers": {name: {"noul": value} for name, value in scores.items()}})
        return scores

    async def post(self, key: str, encoded: bytes, questions: dict) -> tuple[dict[str, float], int]:
        """One paid attempt: reserve its worst case in the ledger, send it, and settle the billed tokens."""
        reservation = RESERVED_TOKENS * USD_PER_MILLION_TOKENS / 1_000_000
        # No await between the budget check and the reservation: concurrent requests see each other's reservations.
        if self.spent_usd + reservation > self.budget_usd:
            raise RuntimeError(f"The workspace budget of ${self.budget_usd:g} would be exceeded; no request sent")
        request_id = uuid.uuid4().hex
        self.append({"kind": "reserve", "id": request_id, "tokens": RESERVED_TOKENS})
        self.spent_usd += reservation
        self.requests += 1
        try:
            async with self.session.post(API_URL, data=encoded,
                                         headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                                         allow_redirects=False) as response:
                if response.status in RETRY_STATUSES:
                    raise Refused(f"Classifier HTTP {response.status}; spending reservation retained")
                if response.status != 200:
                    raise RuntimeError(f"Classifier HTTP {response.status}; no retry; spending reservation retained")
                chunks = bytearray()
                async for chunk in response.content.iter_chunked(65536):
                    chunks.extend(chunk)
                    if len(chunks) > MAX_RESPONSE_BYTES:
                        raise RuntimeError("Classifier response too large; reservation retained")
                try:
                    payload = json.loads(chunks)
                    scores, tokens = validate_response(payload, self.model, questions)
                except (ValueError, TypeError, KeyError):
                    raise RuntimeError("Invalid classifier response; transaction not evaluated; reservation retained") from None
        except (TimeoutError, aiohttp.ClientError):
            raise RuntimeError("Classifier transport failed; outcome unknown; reservation retained") from None
        self.append({"kind": "settle", "id": request_id, "tokens": tokens})
        self.spent_usd += (tokens - RESERVED_TOKENS) * USD_PER_MILLION_TOKENS / 1_000_000
        self.billed_tokens += tokens
        return scores, tokens


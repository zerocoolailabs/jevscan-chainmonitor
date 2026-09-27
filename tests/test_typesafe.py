import asyncio
import json
import sys

import pytest

from jevscan_chainmonitor import scoring, typesafe

QUESTIONS = {"a": {"type": "noul", "instructions": "test"}, "b": {"type": "noul", "instructions": "test"}}


class Content:
    def __init__(self, payload):
        self.payload = payload

    async def iter_chunked(self, size):
        yield json.dumps(self.payload).encode()


class Response:
    status = 200

    def __init__(self, payload):
        self.content = Content(payload)

    async def __aenter__(self):
        await asyncio.sleep(0)
        return self

    async def __aexit__(self, *exc):
        pass


def payload(tokens=55000, score=.8):
    return {"model": "jev-1.13.0", "usage": {"input_tokens": tokens},
            "answers": {name: {"noul": score} for name in QUESTIONS}}


@pytest.fixture
def fake_provider(monkeypatch):
    calls = []

    class Session:
        def __init__(self, **kwargs):
            pass

        def post(self, url, **kwargs):
            calls.append(json.loads(kwargs["data"]))
            return Response(payload())

        async def close(self):
            pass

    monkeypatch.setenv("TYPESAFE_API_KEY", "synthetic-key-only")
    monkeypatch.setattr(typesafe.aiohttp, "ClientSession", Session)
    return calls


def test_concurrent_different_states_cannot_exceed_one_reservation(tmp_path, fake_provider):
    async def scenario():
        async with typesafe.TypeSafeClassifier(tmp_path, "jev-1.13.0", .00231) as client:
            results = await asyncio.gather(*(client.classify({"value": n}, QUESTIONS, input_version=13)
                                             for n in range(2)), return_exceptions=True)
            assert sum(isinstance(result, RuntimeError) for result in results) == 1
            assert typesafe.ledger_total(client.rows) <= .00231
    asyncio.run(scenario())
    assert len(fake_provider) == 1


def test_concurrent_identical_states_pay_once(tmp_path, fake_provider):
    async def scenario():
        async with typesafe.TypeSafeClassifier(tmp_path, "jev-1.13.0", .00231) as client:
            results = await asyncio.gather(*(client.classify({"value": 1}, QUESTIONS, input_version=13)
                                             for _ in range(2)))
            assert results[0] == results[1]
            assert client.cache_hits == 1
    asyncio.run(scenario())
    assert len(fake_provider) == 1




@pytest.mark.parametrize("score", [float("nan"), float("inf"), -.1, 1.1, True, "0.8", None])
def test_invalid_score_is_rejected(score):
    with pytest.raises(ValueError):
        typesafe.validate_response(payload(score=score), "jev-1.13.0", QUESTIONS)


def test_wrong_model_or_missing_answer_rejected():
    bad = payload()
    with pytest.raises(ValueError):
        typesafe.validate_response(bad, "jev-1.12.0", QUESTIONS)
    del bad["answers"]["b"]
    with pytest.raises(ValueError):
        typesafe.validate_response(bad, "jev-1.13.0", QUESTIONS)


def test_unresolved_reservation_counts_and_corrupt_ledger_fails():
    assert typesafe.ledger_total([{"kind": "reserve", "id": "x", "tokens": 55000}]) == .00231
    with pytest.raises(ValueError):
        typesafe.ledger_total([{"kind": "settle", "id": "x", "tokens": 0}])


def test_request_size_fails_before_spend(tmp_path, fake_provider):
    async def scenario():
        async with typesafe.TypeSafeClassifier(tmp_path, "jev-1.13.0", 1) as client:
            with pytest.raises(ValueError, match="size limit"):
                await client.classify({"text": "x" * 50000}, QUESTIONS, input_version=13)
            assert not client.rows
    asyncio.run(scenario())
    assert fake_provider == []


@pytest.mark.parametrize("bad", [{}, {"model": "other"}, {"model": "jev-1.13.0", "usage": {"input_tokens": 1},
    "answers": {"a": {"noul": float("nan")}, "b": {"noul": .1}}}])
def test_invalid_response_keeps_reservation_and_never_caches_answer(tmp_path, fake_provider, monkeypatch, bad):
    monkeypatch.setattr(sys.modules[__name__], "payload", lambda: bad)
    async def scenario():
        async with typesafe.TypeSafeClassifier(tmp_path, "jev-1.13.0", 1) as client:
            with pytest.raises(RuntimeError, match="Invalid classifier response"):
                await client.classify({}, QUESTIONS, input_version=13)
            assert len(client.rows) == 1 and client.rows[0]["kind"] == "reserve"
            assert typesafe.ledger_total(client.rows) == .00231
    asyncio.run(scenario())
    assert len(fake_provider) == 1
    assert not list((tmp_path / "answers").glob("*.json"))


def test_classify_all_overlaps_requests_and_keeps_results_in_order(tmp_path, monkeypatch):
    active, peak = [0], [0]

    class Slow(Response):
        async def __aenter__(self):
            active[0] += 1
            peak[0] = max(peak[0], active[0])
            await asyncio.sleep(0.2)
            active[0] -= 1
            return self

    class Session:
        def __init__(self, **kwargs):
            pass

        def post(self, url, **kwargs):
            value = json.loads(kwargs["data"])["state"]["value"]
            return Slow(payload(tokens=100, score=value / 10))

        async def close(self):
            pass

    monkeypatch.setenv("TYPESAFE_API_KEY", "synthetic-key-only")
    monkeypatch.setattr(typesafe.aiohttp, "ClientSession", Session)

    async def scenario():
        async with typesafe.TypeSafeClassifier(tmp_path, "jev-1.13.0", 1) as client:
            return await scoring.classify_all(client, [{"value": n} for n in range(5)], QUESTIONS, input_version=13)
    results = asyncio.run(scenario())
    assert [result["a"] for result in results] == [0.0, 0.1, 0.2, 0.3, 0.4]
    assert peak[0] > 1


def test_classify_all_stops_at_the_first_failure(tmp_path, fake_provider):
    async def scenario():
        async with typesafe.TypeSafeClassifier(tmp_path, "jev-1.13.0", .00231 * 2) as client:
            with pytest.raises(RuntimeError, match="budget"):
                await scoring.classify_all(client, [{"value": n} for n in range(6)], QUESTIONS, input_version=13)
            assert typesafe.ledger_total(client.rows) <= .00231 * 2
    asyncio.run(scenario())
    assert len(fake_provider) <= 2


def test_a_second_scoring_run_on_the_same_workspace_is_refused(tmp_path, fake_provider):
    async def scenario():
        async with typesafe.TypeSafeClassifier(tmp_path, "jev-1.13.0", 1):
            with pytest.raises(RuntimeError, match="Another scoring run"):
                async with typesafe.TypeSafeClassifier(tmp_path, "jev-1.13.0", 1):
                    pass
    asyncio.run(scenario())


def refusing_session(monkeypatch, statuses: list[int]):
    """A fake API that answers with each status in turn, then succeeds."""
    calls = []

    class Refusal(Response):
        def __init__(self, status):
            super().__init__({})
            self.status = status

    class Session:
        def __init__(self, **kwargs):
            pass

        def post(self, url, **kwargs):
            calls.append(url)
            return Refusal(statuses[len(calls) - 1]) if len(calls) <= len(statuses) else Response(payload(tokens=100))

        async def close(self):
            pass

    monkeypatch.setenv("TYPESAFE_API_KEY", "synthetic-key-only")
    monkeypatch.setattr(typesafe.aiohttp, "ClientSession", Session)
    monkeypatch.setattr(typesafe.asyncio, "sleep", _no_wait)
    return calls


async def _no_wait(seconds):
    return None


def test_a_gateway_failure_is_retried_and_each_attempt_keeps_its_reservation(tmp_path, monkeypatch):
    calls = refusing_session(monkeypatch, [520])

    async def scenario():
        async with typesafe.TypeSafeClassifier(tmp_path, "jev-1.13.0", 1) as client:
            assert (await client.classify({"value": 1}, QUESTIONS, input_version=13))["a"] == .8
            assert [row["kind"] for row in client.rows] == ["reserve", "reserve", "settle"]
            assert typesafe.ledger_total(client.rows) == pytest.approx((55000 + 100) * 0.042 / 1e6)
    asyncio.run(scenario())
    assert len(calls) == 2


def test_repeated_refusals_stop_after_three_attempts(tmp_path, monkeypatch):
    calls = refusing_session(monkeypatch, [429, 503, 520])

    async def scenario():
        async with typesafe.TypeSafeClassifier(tmp_path, "jev-1.13.0", 1) as client:
            with pytest.raises(RuntimeError, match="HTTP 520"):
                await client.classify({"value": 1}, QUESTIONS, input_version=13)
            assert [row["kind"] for row in client.rows] == ["reserve"] * 3
    asyncio.run(scenario())
    assert len(calls) == 3


def test_a_client_error_is_not_retried(tmp_path, monkeypatch):
    calls = refusing_session(monkeypatch, [401])

    async def scenario():
        async with typesafe.TypeSafeClassifier(tmp_path, "jev-1.13.0", 1) as client:
            with pytest.raises(RuntimeError, match="HTTP 401"):
                await client.classify({"value": 1}, QUESTIONS, input_version=13)
    asyncio.run(scenario())
    assert len(calls) == 1

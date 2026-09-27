"""Rerun a benchmark of historical exploits with the current extractor.

Each incident declares its attack transactions and a window of blocks around them. The whole window is collected, so
prices come from before it and each record can mention what happened earlier in it, but only the transactions in blocks
that hold a declared attack are scored: every attack transaction, and every other transaction beside one. Collected
rows are kept per incident in the workspace, and classifier answers are cached, so an interrupted run resumes cheaply.
"""

import json
import sys
from pathlib import Path

from jevscan_chainmonitor import collection, facts, views
from jevscan_chainmonitor.evaluation import DETECTOR_PATH, digest, load_detector, load_incidents, measure
from jevscan_chainmonitor.rpc import Http, Rpc
from jevscan_chainmonitor.scoring import classify_all
from jevscan_chainmonitor.typesafe import TypeSafeClassifier
from jevscan_chainmonitor.workspace import atomic_json, data_directory

MAX_WINDOW_BLOCKS = 250


def window_of(incident: dict) -> tuple[int, int]:
    window = incident.get("window")
    if not isinstance(window, dict):
        raise ValueError(f"{incident['id']} has no block window")
    start, end = window.get("start"), window.get("end")
    collection.check_range(start, end, MAX_WINDOW_BLOCKS)
    return start, end


def attack_rows(incident: dict, records: list[facts.TxFacts]) -> list[dict]:
    """The rows to score from a collected window: every transaction in a block that holds a declared attack."""
    declared = set(incident["attack_txs"])
    blocks = {record["tx"]["block"] for record in records if record["tx"]["hash"] in declared}
    found = {record["tx"]["hash"] for record in records} & declared
    if found != declared:
        raise ValueError(f"{incident['id']}: attack transactions outside the window: {sorted(declared - found)}")
    return [{"transaction": record["tx"]["hash"], "block": record["tx"]["block"], "index": record["tx"]["index"],
             "incident": incident["id"], "declared_attack": record["tx"]["hash"] in declared,
             "facts": record, "state": views.render(record)}
            for record in records if record["tx"]["block"] in blocks]


async def collected(rpc: Rpc, http: Http, table: dict, incident: dict, workspace: Path) -> list[dict]:
    """The incident's rows to score, collected once per facts version and reused afterwards."""
    path = workspace / f"{incident['id']}.json"
    start, end = window_of(incident)
    if path.exists():
        saved = json.loads(path.read_text())
        if (saved["facts_version"] == facts.FACTS_VERSION and saved["window"] == [start, end]
                and saved["attack_txs"] == incident["attack_txs"] and digest(saved["rows"]) == saved["rows_sha256"]):
            return saved["rows"]
        raise ValueError(f"{path} was collected for a different definition; move it aside to recollect")
    _, records = await collection.gather_facts(rpc, http, table, start, end)
    rows = attack_rows(incident, records)
    atomic_json(path, {"incident": incident["id"], "facts_version": facts.FACTS_VERSION, "window": [start, end],
                       "attack_txs": incident["attack_txs"], "rows": rows, "rows_sha256": digest(rows)})
    return rows


async def run(incidents_path: Path, output: Path | None, budget_usd: float | None,
              only: list[str] | None = None, detector_path: Path = DETECTOR_PATH) -> dict:
    """Collect every incident's window and, with a budget, score the rows and measure the result. Without a budget
    the windows are only collected, which needs no classifier key."""
    if output is not None and (output.exists() or output.is_symlink()):
        raise FileExistsError(f"{output} already exists; choose a new --output path.")
    detector = load_detector(detector_path)
    incidents = load_incidents(incidents_path)
    if only:
        unknown = set(only) - {incident["id"] for incident in incidents}
        if unknown:
            raise ValueError(f"Unknown incidents: {', '.join(sorted(unknown))}")
        incidents = [incident for incident in incidents if incident["id"] in only]
    for incident in incidents:
        window_of(incident)
    workspace = data_directory() / "benchmark" / f"v{facts.FACTS_VERSION}"
    workspace.mkdir(parents=True, exist_ok=True, mode=0o700)
    rows = []
    async with Rpc() as rpc, Http() as http:
        table = await collection.prepare(rpc, http)
        for number, incident in enumerate(incidents, 1):
            found = await collected(rpc, http, table, incident, workspace)
            rows += found
            print(f"[{number}/{len(incidents)}] {incident['id']}: {len(found)} transactions in its attack blocks",
                  file=sys.stderr)
    if budget_usd is None:
        return {"incidents": len(incidents), "transactions": len(rows), "collected_in": str(workspace)}
    async with TypeSafeClassifier(data_directory() / "classifier", detector["model"], budget_usd) as client:
        scores = await classify_all(client, [row["state"] for row in rows], detector["questions"],
                                    input_version=facts.FACTS_VERSION)
        spent = {"new_requests": client.requests, "cache_hits": client.cache_hits,
                 "billed_input_tokens": client.billed_tokens}
    scored = [{"transaction": row["transaction"], "incident": row["incident"], "declared_attack": row["declared_attack"],
               "scores": answers} for row, answers in zip(rows, scores)]
    result = measure(incidents, scored, detector)
    atomic_json(output, {"schema": "jevscan-benchmark-v1", "facts_version": facts.FACTS_VERSION,
                         "model": detector["model"], "question_sha256": detector["question_sha256"],
                         "threshold": detector["threshold"], "incidents_sha256": digest(incidents)}
                | result | {"rows": scored} | spent, overwrite=False)
    return result["summary"] | spent | {"output": str(output)}

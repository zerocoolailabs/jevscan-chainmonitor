"""The detector configuration, and offline arithmetic over scored benchmark transactions."""

import hashlib
import json
import math
import re
from pathlib import Path

DETECTOR_PATH = Path(__file__).resolve().parent / "data/detector.json"
HASH = re.compile(r"0x[0-9a-f]{64}")
MODEL_VERSION = re.compile(r"[a-z][a-z0-9-]*-\d+\.\d+\.\d+")  # a pinned version, never an alias such as "latest"
# Each measurement has published scores and scores from the current extractor (a fresh classifier run).
MEASUREMENTS = {"published": ("historical.jsonl", "held-out.jsonl", "ordinary-blocks.jsonl"),
                "current": ("historical-v13.jsonl", "held-out-v13.jsonl", "ordinary-blocks-v13.jsonl")}
REPEAT = ("historical-v13-repeat.jsonl", "held-out-v13-repeat.jsonl")  # a second current run on the same day
FILES = {"detector.json", "incidents.json", "held-out-incidents.json", "provenance.json",
         *(name for names in MEASUREMENTS.values() for name in names), *REPEAT}
MAX_FILE_BYTES = 16 * 1024 * 1024


def read_bytes(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError(f"{path} is missing, larger than {MAX_FILE_BYTES // 2**20} MB, or a symbolic link")
    return path.read_bytes()


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def load_detector(path: Path = DETECTOR_PATH) -> dict:
    """A detector: the classifier model, its questions, and the score at which a transaction is flagged. The bundled
    detector is the one the published results were measured with; another file can change any of the three. Each
    question's digest is recorded with every result, so a result always says which wording produced it."""
    detector = json.loads(read_bytes(path))
    if not isinstance(detector, dict):
        raise ValueError(f"{path} does not hold a detector object")
    model, threshold, questions = detector.get("model"), detector.get("threshold"), detector.get("questions")
    if not isinstance(model, str) or not MODEL_VERSION.fullmatch(model):
        raise ValueError(f"{path}: model must be a pinned version such as jev-1.13.0")
    if type(threshold) not in (int, float) or not 0 < threshold <= 1:
        raise ValueError(f"{path}: threshold must be above 0 and at most 1")
    if (not isinstance(questions, dict) or not questions
            or any(not isinstance(question, dict) or question.get("type") != "noul" for question in questions.values())):
        raise ValueError(f"{path}: questions must map names to Noul questions")
    hashes = {name: digest(question) for name, question in questions.items()}
    if detector.get("question_sha256") not in (None, hashes):
        raise ValueError(f"{path}: question_sha256 does not match the questions; update or remove it")
    return detector | {"question_sha256": hashes}


def alerted(scores: dict, detector: dict) -> bool:
    if not isinstance(scores, dict) or set(scores) != set(detector["questions"]):
        raise ValueError("Incomplete detector scores")
    for score in scores.values():
        if type(score) not in (int, float) or not 0 <= score <= 1 or not math.isfinite(score):
            raise ValueError("Invalid detector score")
    return max(scores.values()) >= detector["threshold"]


def load_incidents(path: Path) -> list[dict]:
    """Benchmark incidents: each has an id, a name, and its declared attack transactions."""
    incidents = json.loads(read_bytes(path))
    seen, declared = set(), set()
    for incident in incidents:
        if (not isinstance(incident, dict) or incident.get("id") in seen or incident.get("chain_id") != 1
                or not incident.get("attack_txs")):
            raise ValueError(f"Invalid incident in {path}")
        seen.add(incident["id"])
        for tx in incident["attack_txs"]:
            if not HASH.fullmatch(tx) or tx in declared:
                raise ValueError(f"Invalid or duplicate declared attack {tx} in {path}")
            declared.add(tx)
    return incidents


def measure(incidents: list[dict], rows: list[dict], detector: dict) -> dict:
    """Coverage and potential false positives for scored benchmark rows, each {transaction, incident, scores}. Every
    declared attack transaction must be among the rows; every other row is a transaction from the same blocks."""
    declared = {tx: incident["id"] for incident in incidents for tx in incident["attack_txs"]}
    hits = {incident["id"]: [] for incident in incidents}
    seen, others, potential_false_positives = set(), 0, []
    for row in rows:
        tx, incident = row["transaction"], row["incident"]
        if not HASH.fullmatch(tx) or tx in seen or incident not in hits:
            raise ValueError("Invalid benchmark transaction row")
        if tx in declared and declared[tx] != incident:
            raise ValueError("Benchmark row disagrees with the incident manifest")
        seen.add(tx)
        alert = alerted(row["scores"], detector)
        if tx in declared:
            hits[incident].append({"transaction": tx, "flagged": alert})
        else:
            others += 1
            if alert:
                potential_false_positives.append({"transaction": tx, "incident_block": incident})
    if not set(declared) <= seen:
        raise ValueError("Missing declared attack transaction results")
    per_incident = [{"id": incident["id"], "name": incident["name"], "declared": len(incident["attack_txs"]),
                     "flagged": sum(tx["flagged"] for tx in hits[incident["id"]]), "transactions": hits[incident["id"]]}
                    for incident in incidents]
    return {
        "summary": {"incidents": len(incidents),
                    "incidents_with_any_attack_flagged": sum(any(tx["flagged"] for tx in group) for group in hits.values()),
                    "incidents_with_every_declared_attack_flagged": sum(all(tx["flagged"] for tx in group) for group in hits.values()),
                    "declared_attack_transactions": len(declared),
                    "flagged_attack_transactions": sum(tx["flagged"] for group in hits.values() for tx in group),
                    "other_transactions": others, "potential_false_positives": len(potential_false_positives)},
        "per_incident": per_incident,
        "potential_false_positive_transactions": potential_false_positives,
    }


def replay(incidents_path: Path, rows_path: Path, detector: dict) -> tuple[dict, set[str]]:
    """The measurement of one stored cohort, and the transactions it covers."""
    incidents = load_incidents(incidents_path)
    rows = [json.loads(line) for line in read_bytes(rows_path).splitlines()]
    declared = {tx for incident in incidents for tx in incident["attack_txs"]}
    if any(type(row["declared_attack"]) is not bool or row["declared_attack"] != (row["transaction"] in declared)
           for row in rows):
        raise ValueError(f"Attack labels in {rows_path.name} disagree with the incident manifest")
    return measure(incidents, rows, detector), {row["transaction"] for row in rows}


def observe(path: Path, detector: dict, benchmark: set[str]) -> dict:
    """Alerts in the ordinary-traffic sample, whose transactions appear in no benchmark cohort."""
    controls, blocks, alerts = set(), set(), 0
    for line in read_bytes(path).splitlines():
        row = json.loads(line)
        tx = row["transaction"]
        if not HASH.fullmatch(tx) or tx in controls or tx in benchmark:
            raise ValueError(f"Invalid, duplicate, or overlapping ordinary-sample transaction in {path.name}")
        if type(row["block"]) is not int or row["block"] < 0:
            raise ValueError(f"Invalid block in {path.name}")
        controls.add(tx)
        blocks.add(row["block"])
        alerts += alerted(row["scores"], detector)
    return {"blocks": len(blocks), "transactions": len(controls), "alerts": alerts}


def measure_all(directory: Path, detector: dict, historical: str, held_out: str, ordinary: str) -> dict:
    """The calibration benchmark, the held-out benchmark and the ordinary-traffic sample for one set of scores."""
    calibration, seen = replay(directory / "incidents.json", directory / historical, detector)
    unseen, unseen_seen = replay(directory / "held-out-incidents.json", directory / held_out, detector)
    if seen & unseen_seen:
        raise ValueError("The held-out cohort overlaps the calibration cohort")
    return {"historical": calibration, "held_out": unseen,
            "ordinary_observation": observe(directory / ordinary, detector, seen | unseen_seen)}


def verify(directory: Path) -> dict:
    manifest = json.loads(read_bytes(directory / "manifest.json"))
    if not isinstance(manifest, dict) or set(manifest) != FILES:
        raise ValueError("Unexpected evidence manifest contents")
    for name, expected in manifest.items():
        if hashlib.sha256(read_bytes(directory / name)).hexdigest() != expected:
            raise ValueError(f"Evidence digest mismatch for {name}")
    detector = load_detector(directory / "detector.json")
    published = measure_all(directory, detector, *MEASUREMENTS["published"])
    current = measure_all(directory, detector, *MEASUREMENTS["current"])
    repeat_historical, _ = replay(directory / "incidents.json", directory / REPEAT[0], detector)
    repeat_held_out, _ = replay(directory / "held-out-incidents.json", directory / REPEAT[1], detector)
    return {
        "mode": "offline arithmetic replay; no new classification or network requests",
        "historical": published["historical"]["summary"],
        "held_out": published["held_out"]["summary"],
        "ordinary_observation": published["ordinary_observation"],
        "current_extractor": {"facts_version": 13, "historical": current["historical"]["summary"],
                              "held_out": current["held_out"]["summary"],
                              "ordinary_observation": current["ordinary_observation"],
                              "same_day_repeat": {"historical": repeat_historical["summary"],
                                                  "held_out": repeat_held_out["summary"]}},
        "per_incident": published["historical"]["per_incident"],
        "held_out_per_incident": published["held_out"]["per_incident"],
        "potential_false_positive_transactions": published["historical"]["potential_false_positive_transactions"],
        "current_per_incident": current["historical"]["per_incident"],
        "current_held_out_per_incident": current["held_out"]["per_incident"],
        "current_potential_false_positive_transactions": current["historical"]["potential_false_positive_transactions"],
        "limitations": ["The calibration cohort was used to write the questions; the held-out cohort was not.",
                        "Other transactions are not all verified benign.",
                        "Classifier scores vary slightly between runs; stored scores are replayed, not regenerated."],
    }

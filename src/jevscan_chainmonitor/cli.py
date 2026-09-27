"""Command line: collect finalized blocks, score them, and reproduce the published results offline."""

import argparse
import asyncio
import json
import math
import os
import sys
import traceback
from pathlib import Path

from jevscan_chainmonitor.evaluation import DETECTOR_PATH, digest, load_detector, verify

COLLECT_CREDENTIALS = ("MAINNET_RPC_URL", "ETHERSCAN_API_KEY")
SCORE_CREDENTIALS = ("TYPESAFE_API_KEY",)


def block_range(args) -> tuple[int, int]:
    if args.block is not None:
        if args.end_block is not None:
            raise ValueError("Use --block alone, or --start-block with --end-block.")
        return args.block, args.block
    if args.end_block is None:
        raise ValueError("--start-block needs --end-block.")
    return args.start_block, args.end_block


def require_budget(budget_usd: float | None) -> float:
    if budget_usd is None or not math.isfinite(budget_usd) or budget_usd <= 0:
        raise ValueError("--budget-usd must be a positive amount.")
    return budget_usd


def require_credentials(names: tuple[str, ...]) -> None:
    missing = [name for name in names if not os.environ.get(name)]
    if missing:
        raise ValueError(f"Set {', '.join(missing)} before running this command.")


def require_new_output(path: Path) -> None:
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"{path} already exists; choose a new --output path.")


async def scan(start: int, end: int, output: Path, budget_usd: float, detector_path: Path = DETECTOR_PATH) -> dict:
    """Collect the blocks (reusing an earlier collection of the same range) and score every transaction."""
    from jevscan_chainmonitor import collection, facts
    from jevscan_chainmonitor.workspace import data_directory

    collection.check_range(start, end)
    require_budget(budget_usd)
    require_new_output(output)
    require_credentials(COLLECT_CREDENTIALS + SCORE_CREDENTIALS)
    saved = data_directory() / "scans" / f"{start}-{end}-v{facts.FACTS_VERSION}.json"
    if saved.is_symlink():
        raise ValueError(f"{saved} is a symbolic link; use a private workspace.")
    if saved.exists():
        cached = collection.load_collection(saved)
        if [block["number"] for block in cached["blocks"]] != list(range(start, end + 1)):
            raise ValueError(f"{saved} does not hold the requested blocks.")
        print("Using cached block data.", file=sys.stderr)
    else:
        print("Collecting blocks (the first run also builds the label and mixer indexes)...", file=sys.stderr)
        await collection.collect(start, end, saved)
    print("Scoring transactions...", file=sys.stderr)
    return await score(saved, output, budget_usd, detector_path)


def estimate(path: Path, detector_path: Path = DETECTOR_PATH) -> tuple[dict, dict, dict]:
    """The detector, the loaded collection, and its cost estimate, checked offline before any paid call."""
    from jevscan_chainmonitor.collection import load_collection
    from jevscan_chainmonitor.typesafe import MAX_REQUEST_BYTES, RESERVED_TOKENS, USD_PER_MILLION_TOKENS, encode

    detector, collection = load_detector(detector_path), load_collection(path)
    for row in collection["rows"]:
        body = {"model": detector["model"], "state": row["state"], "questions": detector["questions"]}
        if len(encode(body)) > MAX_REQUEST_BYTES:
            raise ValueError(f"Transaction {row['transaction']} exceeds the request size limit; no scoring started.")
    count = len(collection["rows"])
    summary = {"transactions": count, "facts_version": collection["facts_version"], "model": detector["model"],
               "threshold": detector["threshold"],
               "maximum_cost_usd": count * RESERVED_TOKENS * USD_PER_MILLION_TOKENS / 1e6,
               "assumed_usd_per_million_input_tokens": USD_PER_MILLION_TOKENS}
    return detector, collection, summary


async def score(path: Path, output: Path, budget_usd: float, detector_path: Path = DETECTOR_PATH) -> dict:
    """Score a saved collection. Each output row has the transaction's position, scores and flag; a flagged row also
    carries the fact sheet the classifier read, which says what the transaction did."""
    from jevscan_chainmonitor.scoring import score_states
    from jevscan_chainmonitor.typesafe import TypeSafeClassifier
    from jevscan_chainmonitor.workspace import atomic_json, data_directory

    require_budget(budget_usd)
    require_new_output(output)
    detector, collection, _ = estimate(path, detector_path)
    async with TypeSafeClassifier(data_directory() / "classifier", detector["model"], budget_usd) as client:
        states = [row["state"] for row in collection["rows"]]
        results = await score_states(client, states, detector, input_version=collection["facts_version"])
        rows = [{key: row[key] for key in ("transaction", "block", "index")} | {"state_sha256": digest(row["state"])}
                | result | ({"fact_sheet": row["state"]} if result["flagged"] else {})
                for row, result in zip(collection["rows"], results)]
        result = {"schema": "jevscan-scores-v1", "complete": True, "collection_sha256": collection["content_sha256"],
                  "facts_version": collection["facts_version"], "model": detector["model"],
                  "question_sha256": detector["question_sha256"], "threshold": detector["threshold"],
                  "question_review": detector.get("human_review"), "rows": rows,
                  "new_requests": client.requests, "cache_hits": client.cache_hits, "billed_input_tokens": client.billed_tokens}
    atomic_json(output, result, overwrite=False)
    return {"transactions": len(rows), "flagged": sum(row["flagged"] for row in rows),
            "complete": True, "output": str(output), "facts_version": collection["facts_version"],
            "new_requests": result["new_requests"], "billed_input_tokens": result["billed_input_tokens"]}


def parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--debug", action="store_true", help="Print the full traceback when a command fails")
    detecting = argparse.ArgumentParser(add_help=False)
    detecting.add_argument("--detector", type=Path, default=DETECTOR_PATH,
                           help="Detector file with the model, questions and threshold (default: the published one)")
    root = argparse.ArgumentParser(description="Flag Ethereum transactions that look like smart-contract exploits")
    sub = root.add_subparsers(dest="command", required=True)

    def blocks(command: argparse.ArgumentParser) -> None:
        selection = command.add_mutually_exclusive_group(required=True)
        selection.add_argument("--block", type=int, help="A single finalized block")
        selection.add_argument("--start-block", type=int, help="First block of a range (use with --end-block)")
        command.add_argument("--end-block", type=int, help="Last block of the range, at most 20 blocks in all")

    scanning = sub.add_parser("scan", parents=[common, detecting], help="Collect and score finalized blocks")
    blocks(scanning)
    scanning.add_argument("--budget-usd", type=float, required=True,
                          help="Classifier spending limit for the workspace, cumulative across runs")
    scanning.add_argument("--output", type=Path, default=Path("scan.json"))

    collecting = sub.add_parser("collect", parents=[common], help="Collect finalized blocks without scoring them")
    blocks(collecting)
    collecting.add_argument("--output", type=Path, required=True)

    scoring = sub.add_parser("score", parents=[common, detecting], help="Score a saved collection")
    scoring.add_argument("--input", type=Path, required=True)
    scoring.add_argument("--output", type=Path)
    scoring.add_argument("--budget-usd", type=float,
                         help="Classifier spending limit for the workspace, cumulative across runs")
    scoring.add_argument("--dry-run", action="store_true", help="Check the collection and estimate the cost offline")

    following = sub.add_parser("monitor", parents=[common, detecting],
                               help="Follow finalized blocks and score every transaction as they arrive")
    following.add_argument("--budget-usd", type=float, required=True,
                           help="Classifier spending limit for the workspace, cumulative across runs")
    following.add_argument("--output", type=Path, default=Path("monitor.jsonl"), help="One JSON line per block")
    following.add_argument("--start-block", type=int, help="First block to score (default: the finalized head)")
    following.add_argument("--blocks", type=int, help="Stop after this many blocks (default: run until stopped)")

    rerun = sub.add_parser("benchmark", parents=[common, detecting], help="Rerun the benchmark with the current extractor")
    rerun.add_argument("--incidents", type=Path, default=Path("evidence/incidents.json"))
    rerun.add_argument("--only", nargs="+", metavar="ID", help="Run only these incidents")
    rerun.add_argument("--budget-usd", type=float,
                       help="Classifier spending limit; without it the windows are collected but not scored")
    rerun.add_argument("--output", type=Path, help="Where to write the scored rows and metrics")

    results = sub.add_parser("results", parents=[common], help="Recompute the published benchmark from stored scores")
    results.add_argument("--evidence", type=Path, default=Path("evidence"))
    results.add_argument("--details", action="store_true", help="Include per-incident results")
    return root


def run(args) -> dict:
    if args.command == "scan":
        start, end = block_range(args)
        return asyncio.run(scan(start, end, args.output, args.budget_usd, args.detector))
    if args.command == "collect":
        from jevscan_chainmonitor import collection
        start, end = block_range(args)
        collection.check_range(start, end)
        require_new_output(args.output)
        require_credentials(COLLECT_CREDENTIALS)
        return asyncio.run(collection.collect(start, end, args.output))
    if args.command == "score":
        if args.dry_run:
            return estimate(args.input, args.detector)[2]
        if args.output is None or args.budget_usd is None:
            raise ValueError("score needs --output and --budget-usd (or --dry-run).")
        return asyncio.run(score(args.input, args.output, args.budget_usd, args.detector))
    if args.command == "monitor":
        from jevscan_chainmonitor import monitor
        require_budget(args.budget_usd)
        require_new_output(args.output)
        require_credentials(COLLECT_CREDENTIALS + SCORE_CREDENTIALS)
        if args.blocks is not None and args.blocks < 1:
            raise ValueError("--blocks must be at least 1.")
        return asyncio.run(monitor.run(args.output, args.budget_usd, args.detector, args.start_block, args.blocks))
    if args.command == "benchmark":
        from jevscan_chainmonitor import benchmark
        if args.budget_usd is not None:
            require_budget(args.budget_usd)
            if args.output is None:
                raise ValueError("benchmark --budget-usd needs --output.")
            require_credentials(COLLECT_CREDENTIALS + SCORE_CREDENTIALS)
        else:
            require_credentials(COLLECT_CREDENTIALS)
        return asyncio.run(benchmark.run(args.incidents, args.output, args.budget_usd, args.only, args.detector))
    result = verify(args.evidence)
    if args.details:
        return result
    return {key: result[key] for key in ("mode", "historical", "held_out", "ordinary_observation", "current_extractor",
                                         "limitations")}


def failure_text(error: BaseException, debug: bool) -> str:
    """What to print for a failed command. Messages name the problem; credentials are replaced by their variable
    names and control characters from remote text are neutralized, in case either reached an exception."""
    from jevscan_chainmonitor.rpc import scrub

    if debug:
        text = "".join(traceback.format_exception(error)).rstrip()
    elif isinstance(error, (OSError, ValueError, RuntimeError)):
        text = f"Error: {error}"
    else:
        text = (f"Unexpected {type(error).__name__}: {error}\n"
                "This is probably a bug. Rerun with --debug and include the output in a report.")
    return "".join(c if c.isprintable() or c == "\n" else "�" for c in scrub(text))


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try:
        result = run(args)
    except KeyboardInterrupt:
        print("Stopped.", file=sys.stderr)
        return 130
    except Exception as error:
        print(failure_text(error, args.debug), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

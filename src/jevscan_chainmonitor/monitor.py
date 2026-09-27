"""Follow the chain: score every transaction in each newly finalized block and write one line per block.

At startup the monitor loads the day of blocks before its first block into memory, so the prior-day activity of every
contract is known locally, and it then answers most explorer questions from memory and its caches. Each output line
records the block, how long collection and scoring took, and every flagged transaction with the fact sheet the
classifier read.
"""

import asyncio
import json
import sys
import time
from pathlib import Path

from jevscan_chainmonitor import collection, enrich
from jevscan_chainmonitor.enrich import PRIOR_DAY_BLOCKS
from jevscan_chainmonitor.evaluation import DETECTOR_PATH, load_detector
from jevscan_chainmonitor.memory import ChainMemory, load_blocks
from jevscan_chainmonitor.rpc import Http, Rpc
from jevscan_chainmonitor.scoring import score
from jevscan_chainmonitor.typesafe import TypeSafeClassifier
from jevscan_chainmonitor.workspace import data_directory

POLL_SECONDS = 6.0  # half a slot; the finalized head advances an epoch (32 blocks) at a time
FORGET_EVERY = 100  # blocks between trims of the memory to the prior-day window


def say(text: str) -> None:
    print(text, file=sys.stderr, flush=True)


async def finalized_head(rpc: Rpc) -> int:
    return int((await rpc.call("eth_getBlockByNumber", ["finalized", False], cached=False))["number"], 16)


async def run(output: Path, budget_usd: float, detector_path: Path = DETECTOR_PATH, start_block: int | None = None,
              blocks: int | None = None) -> dict:
    """Monitor from `start_block` (default: the finalized head) until stopped, or for `blocks` blocks."""
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"{output} already exists; choose a new --output path.")
    detector = load_detector(detector_path)
    memory = ChainMemory()
    processed = flagged = 0
    async with Rpc() as rpc, Http() as http, \
            TypeSafeClassifier(data_directory() / "classifier", detector["model"], budget_usd) as classifier:
        say("Preparing the label and mixer indexes...")
        head = synced = await finalized_head(rpc)  # read first: the mixer index then covers at least this far
        table = await collection.prepare(rpc, http)
        number = head if start_block is None else start_block
        say(f"Loading the {PRIOR_DAY_BLOCKS:,} blocks before {number:,} into memory...")
        started = time.perf_counter()
        await load_blocks(rpc, memory, number - PRIOR_DAY_BLOCKS, number - 1)
        say(f"Loaded in {time.perf_counter() - started:.0f}s. Following finalized blocks from {number:,}.")
        with output.open("x") as out:
            while blocks is None or processed < blocks:
                if number > head:
                    await asyncio.sleep(POLL_SECONDS)
                    head = await finalized_head(rpc)
                    continue
                if number > synced:  # extend the mixer payout index once per newly finalized batch
                    synced = await finalized_head(rpc)
                    table = await collection.prepare(rpc, http)
                    enrich.mixer_payouts.cache_clear()
                started = time.perf_counter()
                _, records = await collection.gather_facts(rpc, http, table, number, number, memory)
                collected = time.perf_counter() - started
                results = await score(records, classifier, detector)
                scored = time.perf_counter() - started - collected
                alerts = [row for row in results if row["flagged"]]
                out.write(json.dumps({"block": number, "transactions": len(results),
                                      "collect_seconds": round(collected, 2), "score_seconds": round(scored, 2),
                                      "alerts": alerts}, sort_keys=True) + "\n")
                out.flush()
                say(f"block {number:,}: {len(results)} transactions in {collected + scored:.1f}s "
                    f"(collect {collected:.1f}s, score {scored:.1f}s), {len(alerts)} flagged")
                processed, flagged, number = processed + 1, flagged + len(alerts), number + 1
                if processed % FORGET_EVERY == 0:
                    memory.forget_before(number - PRIOR_DAY_BLOCKS)
    return {"blocks": processed, "flagged": flagged, "output": str(output)}

"""Collect complete finalized blocks into a self-checking file of facts and rendered classifier input."""

import asyncio
import json
from pathlib import Path

from jevscan_chainmonitor import enrich, facts, labels, mixers, views
from jevscan_chainmonitor.evaluation import digest
from jevscan_chainmonitor.memory import ChainMemory
from jevscan_chainmonitor.rpc import Http, Rpc
from jevscan_chainmonitor.validation import require_hash, validate_block
from jevscan_chainmonitor.workspace import atomic_json

TRACER = {"tracer": "callTracer", "tracerConfig": {"withLog": True}}
MAX_BLOCKS = 20
MAX_COLLECTION_BYTES = 128 * 1024 * 1024
FETCH_BLOCKS = 8  # blocks fetched at once; each block's receipts and trace are fetched together


def check_range(start: int, end: int, max_blocks: int = MAX_BLOCKS) -> None:
    if type(start) is not int or type(end) is not int or start < 1 or not start <= end < start + max_blocks:
        raise ValueError(f"Choose one block or a range of up to {max_blocks} consecutive blocks")


async def prepare(rpc: Rpc, http: Http) -> dict[str, facts.Label]:
    """The filtered label table, downloaded on first use, and a mixer index extended to the finalized head."""
    if not labels.labels_file().exists():
        accounts = await http.get("labels_dump", labels.DUMP_PATH + "/accounts.json", {})
        tokens = await http.get("labels_dump", labels.DUMP_PATH + "/tokens.json", {})
        atomic_json(labels.labels_file(), labels.build(accounts, tokens))
    table = labels.load()
    pools = [address for address, entry in table.items() if entry["category"] == "mixer"]
    if not pools:
        raise ValueError("No mixer contracts available in the prepared labels")
    await mixers.sync(rpc, pools)
    enrich.mixer_payouts.cache_clear()
    return table


async def fetch_block(rpc: Rpc, number: int) -> tuple[dict, list, list]:
    # Canonical block identity is always refreshed; cached raw block data
    # cannot silently determine whether collection is complete.
    return await asyncio.gather(
        rpc.call("eth_getBlockByNumber", [hex(number), True], cached=False),
        rpc.call("eth_getBlockReceipts", [hex(number)], cached=False),
        rpc.call("debug_traceBlockByNumber", [hex(number), TRACER], cached=False),
    )


async def gather_facts(rpc: Rpc, http: Http, table: dict[str, facts.Label], start: int, end: int,
                       memory: ChainMemory | None = None) -> tuple[list[dict], list[facts.TxFacts]]:
    """Each block's identity and the facts of every transaction in blocks start..end, in chain order. The blocks
    form one window: prices come from before its first block, and each record can mention what the same sender or
    the same contracts did earlier in it. A monitor passes its `memory`, which also records each block."""
    finalized = await rpc.call("eth_getBlockByNumber", ["finalized", False], cached=False)
    if not isinstance(finalized, dict) or end > int(finalized["number"], 16):
        raise ValueError("Only finalized historical blocks may be collected")
    cores, selected = [], []
    numbers = list(range(start, end + 1))
    for batch in (numbers[i:i + FETCH_BLOCKS] for i in range(0, len(numbers), FETCH_BLOCKS)):
        for number, (block, receipts, traces) in zip(batch, await asyncio.gather(*(fetch_block(rpc, n) for n in batch))):
            validate_block(block, receipts, traces, number)
            if memory is not None:
                memory.add_block(block, receipts)
            for tx, receipt, trace in zip(block["transactions"], receipts, traces):
                cores.append(facts.extract(block, tx, receipt, trace["result"]))
            selected.append({"number": number, "hash": block["hash"], "transactions": len(block["transactions"])})
    context = await enrich.gather(cores, table, rpc, http, memory) if cores else None
    # finish mutates actor and contract history: never parallelize this loop.
    records = [facts.finish(core, context) for core in cores]
    for block in selected:
        refreshed = await rpc.call("eth_getBlockByNumber", [hex(block["number"]), False], cached=False)
        if not isinstance(refreshed, dict) or refreshed["hash"] != block["hash"]:
            raise RuntimeError("Canonical block changed during collection; output not saved")
    return selected, records


async def collect_facts(start: int, end: int) -> list[facts.TxFacts]:
    """The facts of every transaction in finalized blocks start..end, in chain order, for use in a program. Needs
    MAINNET_RPC_URL and ETHERSCAN_API_KEY; the first call builds the label and mixer indexes."""
    check_range(start, end)
    async with Rpc() as rpc, Http() as http:
        _, records = await gather_facts(rpc, http, await prepare(rpc, http), start, end)
    return records


async def collect(start: int, end: int, output: Path) -> dict:
    check_range(start, end)
    if output.exists():
        raise FileExistsError(f"{output} already exists; choose a new output path")
    async with Rpc() as rpc, Http() as http:
        selected, records = await gather_facts(rpc, http, await prepare(rpc, http), start, end)
    rows = [{"transaction": record["tx"]["hash"], "block": record["tx"]["block"],
             "index": record["tx"]["index"], "facts": record, "state": views.render(record)} for record in records]
    result = {"schema": "jevscan-collection-v1", "chain_id": 1, "facts_version": facts.FACTS_VERSION,
              "blocks": selected, "rows": rows, "complete": True}
    result["content_sha256"] = digest(result)
    if len(json.dumps(result).encode()) > MAX_COLLECTION_BYTES:
        raise ValueError("Collection exceeds supported file size; choose fewer blocks")
    atomic_json(output, result, overwrite=False)
    return {"blocks": len(selected), "transactions": len(rows), "facts_version": facts.FACTS_VERSION,
            "output": str(output)}


def load_collection(path: Path) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_COLLECTION_BYTES:
        raise ValueError("Collection missing, oversized, or a symbolic link")
    value = json.loads(path.read_text())
    if (not isinstance(value, dict) or value.get("schema") != "jevscan-collection-v1"
            or value.get("complete") is not True or value.get("chain_id") != 1
            or value.get("facts_version") != facts.FACTS_VERSION):
        raise ValueError("Incomplete or incompatible collection")
    checksum = value.pop("content_sha256", None)
    if digest(value) != checksum:
        raise ValueError("Collection integrity mismatch")
    rows, blocks = value["rows"], value["blocks"]
    if not isinstance(blocks, list) or not 1 <= len(blocks) <= MAX_BLOCKS:
        raise ValueError(f"Collection must contain one to {MAX_BLOCKS} consecutive blocks")
    if not isinstance(rows, list) or len(rows) > 100000:
        raise ValueError("Invalid or oversized collection rows")
    expected, seen = {}, set()
    for block in blocks:
        if (not isinstance(block, dict) or type(block.get("number")) is not int
                or not 1 <= block["number"] < 2**63
                or type(block.get("transactions")) is not int
                or not 0 <= block["transactions"] <= 5000):
            raise ValueError("Invalid collection block metadata")
        require_hash(block.get("hash"))
        if expected and block["number"] != next(reversed(expected)) + 1:
            raise ValueError("Collection blocks are not consecutive and ordered")
        expected[block["number"]] = block["transactions"]
    if len(rows) != sum(expected.values()):
        raise ValueError("Collection transaction count mismatch")
    positions = {number: set() for number in expected}
    previous = None
    for row in rows:
        tx, block, index = row["transaction"], row["block"], row["index"]
        require_hash(tx)
        if (type(block) is not int or type(index) is not int or block not in expected
                or not 0 <= index < expected[block] or not isinstance(row.get("state"), dict)):
            raise ValueError("Invalid collection transaction position or state")
        if previous is not None and (block, index) <= previous:
            raise ValueError("Collection transactions are not ordered")
        previous = (block, index)
        if tx in seen or block not in expected or index in positions[block]:
            raise ValueError("Duplicate or unknown collection transaction")
        record = row["facts"]
        if (record["version"] != facts.FACTS_VERSION or record["tx"]["hash"] != tx
                or record["tx"]["block"] != block or record["tx"]["index"] != index
                or views.render(record) != row["state"]):
            raise ValueError("Collection facts and rendered state disagree")
        seen.add(tx)
        positions[block].add(index)
    if any(positions[number] != set(range(count)) for number, count in expected.items()):
        raise ValueError("Collection omits transactions from a declared block")
    value["content_sha256"] = checksum
    return value

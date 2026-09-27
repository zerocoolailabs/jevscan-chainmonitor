import asyncio
import json

import pytest

from jevscan_chainmonitor import benchmark, facts, typesafe
from tests.helpers import BLOCK_NUMBER, BUILDER, SENDER, WALLET, context, kinds
from tests.test_typesafe import Response
from tests.test_validation import complete_block


def record(tx_hash: str, block: int) -> dict:
    raw, receipts, traces = complete_block()
    base = facts.finish(facts.extract(raw, raw["transactions"][0], receipts[0], traces[0]["result"]),
                        context(kinds=kinds(wallet=[SENDER, WALLET, BUILDER])))
    return base | {"tx": base["tx"] | {"hash": tx_hash, "block": block}}


ATTACK, PEER, BEFORE, AFTER = ("0x" + c * 64 for c in "abcd")


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("JEVSCAN_DATA_DIR", str(tmp_path / "workspace"))
    monkeypatch.setenv("TYPESAFE_API_KEY", "synthetic-key-only")
    incidents = tmp_path / "incidents.json"
    incidents.write_text(json.dumps([{"id": "example-hack", "name": "Example", "chain_id": 1, "attack_txs": [ATTACK],
                                      "window": {"start": BLOCK_NUMBER - 1, "end": BLOCK_NUMBER + 1}}]))
    collections, requests = [], []

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    async def prepare(rpc, http):
        return {}

    async def gather_facts(rpc, http, table, start, end):
        collections.append((start, end))
        return [], [record(BEFORE, start), record(ATTACK, BLOCK_NUMBER), record(PEER, BLOCK_NUMBER), record(AFTER, end)]

    class Session:
        def __init__(self, **kwargs):
            pass

        async def close(self):
            pass

        def post(self, url, **kwargs):
            request = json.loads(kwargs["data"])
            requests.append(request)
            return Response({"model": request["model"], "usage": {"input_tokens": 100},
                             "answers": {name: {"noul": .8} for name in request["questions"]}})

    monkeypatch.setattr(benchmark, "Rpc", Client)
    monkeypatch.setattr(benchmark, "Http", Client)
    monkeypatch.setattr(benchmark.collection, "prepare", prepare)
    monkeypatch.setattr(benchmark.collection, "gather_facts", gather_facts)
    monkeypatch.setattr(typesafe.aiohttp, "ClientSession", Session)
    return incidents, collections, requests


def test_only_the_attack_blocks_are_scored_and_measured(world, tmp_path):
    incidents, collections, requests = world
    summary = asyncio.run(benchmark.run(incidents, tmp_path / "result.json", 1))
    assert collections == [(BLOCK_NUMBER - 1, BLOCK_NUMBER + 1)]
    assert summary["incidents_with_any_attack_flagged"] == 1 and summary["other_transactions"] == 1
    assert summary["potential_false_positives"] == 1
    saved = json.loads((tmp_path / "result.json").read_text())
    assert [row["transaction"] for row in saved["rows"]] == [ATTACK, PEER]
    assert saved["facts_version"] == facts.FACTS_VERSION


def test_a_collected_window_is_reused_and_collection_alone_needs_no_budget(world, tmp_path):
    incidents, collections, requests = world
    assert asyncio.run(benchmark.run(incidents, None, None))["transactions"] == 2
    asyncio.run(benchmark.run(incidents, tmp_path / "result.json", 1))
    assert len(collections) == 1 and requests


def test_an_attack_outside_its_window_is_an_error(world, monkeypatch):
    incidents, _, _ = world

    async def elsewhere(rpc, http, table, start, end):
        return [], [record(PEER, start)]
    monkeypatch.setattr(benchmark.collection, "gather_facts", elsewhere)
    with pytest.raises(ValueError, match="outside the window"):
        asyncio.run(benchmark.run(incidents, None, None))

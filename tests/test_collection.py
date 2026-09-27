import asyncio
import json

import pytest

from jevscan_chainmonitor import cli, collection, facts, typesafe
from jevscan_chainmonitor.evaluation import digest
from tests.helpers import BLOCK_NUMBER, BUILDER, SENDER, WALLET, context, kinds
from tests.test_typesafe import Response
from tests.test_validation import complete_block


def saved(tmp_path, blocks, rows=None):
    value = {"schema": "jevscan-collection-v1", "complete": True, "chain_id": 1,
             "facts_version": facts.FACTS_VERSION, "blocks": blocks, "rows": rows or []}
    value["content_sha256"] = digest(value)
    path = tmp_path / "collection.json"
    path.write_text(json.dumps(value))
    return path


def block(number=1, count=0):
    return {"number": number, "hash": "0x" + "11" * 32, "transactions": count}


@pytest.mark.parametrize("blocks", [[], [block(-5)], [block(True)], [block(count=10**12)],
    [block(count=-1)], [block(count=True)], [block(2), block(1)], [block(1), block(3)],
    [block(1), block(1)], [block() | {"hash": "not-a-hash"}], [block(i) for i in range(1, 22)]])
def test_invalid_metadata_rejected_before_rendering(tmp_path, blocks, monkeypatch):
    def forbidden(*args):
        pytest.fail("Rendering must not precede metadata validation")
    monkeypatch.setattr(collection.views, "render", forbidden)
    with pytest.raises(ValueError):
        collection.load_collection(saved(tmp_path, blocks))


def test_genuine_empty_block_is_not_an_empty_collection(tmp_path):
    assert collection.load_collection(saved(tmp_path, [block()]))["blocks"] == [block()]


def test_declared_missing_transaction_rejected(tmp_path):
    with pytest.raises(ValueError, match="count"):
        collection.load_collection(saved(tmp_path, [block(count=1)]))


def test_modified_checksum_rejected(tmp_path):
    path = saved(tmp_path, [block()])
    value = json.loads(path.read_text())
    value["blocks"][0]["number"] = 2
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="integrity"):
        collection.load_collection(path)


def test_collect_estimate_and_score_complete_path_offline(tmp_path, monkeypatch):
    raw_block, receipts, traces = complete_block()

    class Rpc:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def call(self, method, params, **kwargs):
            return {"eth_getBlockByNumber": raw_block, "eth_getBlockReceipts": receipts,
                    "debug_traceBlockByNumber": traces}[method]

    async def gather(*args):
        return context(kinds=kinds(wallet=[SENDER, WALLET, BUILDER]))

    calls = []

    class Session:
        def __init__(self, **kwargs):
            pass

        async def close(self):
            pass

        def post(self, url, **kwargs):
            request = json.loads(kwargs["data"])
            calls.append(request)
            return Response({"model": request["model"], "usage": {"input_tokens": 100},
                             "answers": {name: {"noul": .8} for name in request["questions"]}})

    monkeypatch.setenv("JEVSCAN_DATA_DIR", str(tmp_path / "private"))
    monkeypatch.setenv("TYPESAFE_API_KEY", "synthetic-key-only")
    monkeypatch.setattr(collection, "Rpc", Rpc)
    monkeypatch.setattr(collection, "Http", Rpc)
    async def prepare(rpc, http):
        return {}

    monkeypatch.setattr(collection, "prepare", prepare)
    monkeypatch.setattr(collection.enrich, "gather", gather)
    monkeypatch.setattr(typesafe.aiohttp, "ClientSession", Session)
    path, output = tmp_path / "collected.json", tmp_path / "scored.json"
    collected = asyncio.run(collection.collect(BLOCK_NUMBER, BLOCK_NUMBER, path))
    assert collected["transactions"] == 1
    _, loaded, preview = cli.estimate(path)
    assert preview["transactions"] == 1 and calls == []
    assert isinstance(loaded["rows"][0]["state"], dict)
    result = asyncio.run(cli.score(path, output, 1))
    assert result["complete"] and result["flagged"] == 1 and len(calls) == 1
    assert json.loads(output.read_text())["rows"][0]["scores"]
    with pytest.raises(FileExistsError):
        asyncio.run(cli.score(path, output, 1))
    assert len(calls) == 1

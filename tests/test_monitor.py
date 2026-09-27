"""The monitor scores each finalized block in order, waits for new ones, and writes one line per block."""

import asyncio
import json

import pytest

from jevscan_chainmonitor import monitor
from tests.test_benchmark import record

HEAD = 1_000


class Rpc:
    """A chain whose finalized head advances by one each time it is read after the first two reads."""

    reads = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def call(self, method, params, cached=True):
        assert method == "eth_getBlockByNumber" and params[0] == "finalized"
        Rpc.reads += 1
        return {"number": hex(HEAD + max(0, Rpc.reads - 2))}


class Classifier:
    """Gives every transaction the same score."""

    score = 0.1

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def classify(self, state, questions, *, input_version):
        return dict.fromkeys(questions, self.score)


@pytest.fixture
def chain(monkeypatch, tmp_path):
    Rpc.reads = 0
    collected, loaded = [], []

    async def prepare(rpc, http):
        return {}

    async def load_blocks(rpc, memory, start, end):
        loaded.append((start, end))

    async def gather_facts(rpc, http, table, start, end, memory):
        collected.append(start)
        return [], [record("0x" + format(start, "064x"), start)]

    monkeypatch.setattr(monitor, "Rpc", Rpc)
    monkeypatch.setattr(monitor, "Http", Rpc)
    monkeypatch.setattr(monitor, "TypeSafeClassifier", lambda *args: Classifier())
    monkeypatch.setattr(monitor, "load_blocks", load_blocks)
    monkeypatch.setattr(monitor.collection, "prepare", prepare)
    monkeypatch.setattr(monitor.collection, "gather_facts", gather_facts)
    monkeypatch.setattr(monitor, "POLL_SECONDS", 0)
    return tmp_path / "monitor.jsonl", collected, loaded


def test_blocks_are_scored_in_order_after_a_day_of_memory_is_loaded(chain):
    output, collected, loaded = chain
    summary = asyncio.run(monitor.run(output, 1, start_block=HEAD - 1, blocks=3))
    assert loaded == [(HEAD - 1 - 7_200, HEAD - 2)]
    assert collected == [HEAD - 1, HEAD, HEAD + 1]  # the last one after waiting for the head to advance
    lines = [json.loads(line) for line in output.read_text().splitlines()]
    assert [line["block"] for line in lines] == collected and summary == {"blocks": 3, "flagged": 0, "output": str(output)}
    assert all(line["transactions"] == 1 and line["alerts"] == [] for line in lines)


def test_an_existing_output_is_never_overwritten(chain):
    output, _, _ = chain
    output.write_text("keep")
    with pytest.raises(FileExistsError):
        asyncio.run(monitor.run(output, 1, blocks=1))
    assert output.read_text() == "keep"


def test_an_alert_carries_the_transaction_and_the_fact_sheet_the_classifier_read(chain, monkeypatch):
    output, _, _ = chain
    monkeypatch.setattr(Classifier, "score", 0.9)
    assert asyncio.run(monitor.run(output, 1, start_block=HEAD, blocks=1))["flagged"] == 1
    [line] = [json.loads(line) for line in output.read_text().splitlines()]
    [alert] = line["alerts"]
    assert alert["transaction"] == "0x" + format(HEAD, "064x") and alert["fact_sheet"]["status"] == "success"

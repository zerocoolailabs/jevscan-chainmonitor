import json

import pytest

from jevscan_chainmonitor import cli, facts, typesafe, views, workspace
from jevscan_chainmonitor.evaluation import digest
from tests.helpers import BLOCK_NUMBER, BUILDER, SENDER, WALLET, context, kinds
from tests.test_typesafe import Response
from tests.test_validation import complete_block


@pytest.fixture
def scan_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("JEVSCAN_DATA_DIR", str(tmp_path))
    for name in ("MAINNET_RPC_URL", "ETHERSCAN_API_KEY", "TYPESAFE_API_KEY"):
        monkeypatch.setenv(name, "synthetic-test-credential")
    block, receipts, traces = complete_block()
    record = facts.finish(facts.extract(block, block["transactions"][0], receipts[0], traces[0]["result"]),
                          context(kinds=kinds(wallet=[SENDER, WALLET, BUILDER])))
    collection = {"schema": "jevscan-collection-v1", "complete": True, "chain_id": 1,
                  "facts_version": facts.FACTS_VERSION,
                  "blocks": [{"number": BLOCK_NUMBER, "hash": block["hash"], "transactions": 1}],
                  "rows": [{"transaction": record["tx"]["hash"], "block": BLOCK_NUMBER, "index": 0,
                            "facts": record, "state": views.render(record)}]}
    collection["content_sha256"] = digest(collection)
    workspace.atomic_json(tmp_path / "scans" / f"{BLOCK_NUMBER}-{BLOCK_NUMBER}-v{facts.FACTS_VERSION}.json", collection)
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
                             "answers": {key: {"noul": .8} for key in request["questions"]}})

    monkeypatch.setattr(typesafe.aiohttp, "ClientSession", Session)
    return tmp_path, calls


def test_scan_budget_authorizes_scoring_and_reuses_answers(scan_workspace, capsys):
    workspace, calls = scan_workspace
    for index in range(2):
        output = workspace / f"result-{index}.json"
        assert cli.main(["scan", "--block", str(BLOCK_NUMBER), "--budget-usd", "1", "--output", str(output)]) == 0
        summary = json.loads(capsys.readouterr().out)
        assert summary["transactions"] == 1 and summary["flagged"] == 1
        result = json.loads(output.read_text())
        assert result["complete"] and result["question_review"] == "pending"
        assert result["rows"][0]["fact_sheet"] == result["rows"][0]["fact_sheet"] | {"status": "success"}
        assert result["new_requests"] == (1 if index == 0 else 0)
    assert len(calls) == 1


def test_scan_accepts_block_range(scan_workspace, capsys):
    workspace, calls = scan_workspace
    assert cli.main(["scan", "--start-block", str(BLOCK_NUMBER), "--end-block", str(BLOCK_NUMBER),
                     "--budget-usd", "1", "--output", str(workspace / "range.json")]) == 0
    assert len(calls) == 1


@pytest.mark.parametrize("selection,budget", [(["--block", "0"], "1"),
    (["--block", "1", "--end-block", "2"], "1"), (["--start-block", "1"], "1"),
    (["--start-block", "2", "--end-block", "1"], "1"),
    (["--start-block", "1", "--end-block", "21"], "1"),
    (["--block", "1"], "nan"), (["--block", "1"], "inf"), (["--block", "1"], "0"),
    (["--block", "1"], "-1")])
def test_invalid_scan_stops_before_network(tmp_path, selection, budget, capsys):
    assert cli.main(["scan", *selection, "--budget-usd", budget, "--output", str(tmp_path / "result.json")]) == 1
    assert not (tmp_path / "result.json").exists()
    assert "Error:" in capsys.readouterr().err


def test_scan_does_not_overwrite_or_charge(scan_workspace, capsys):
    workspace, calls = scan_workspace
    output = workspace / "existing.json"
    output.write_text("keep")
    assert cli.main(["scan", "--block", str(BLOCK_NUMBER), "--budget-usd", "1", "--output", str(output)]) == 1
    assert output.read_text() == "keep" and calls == []


def test_scan_missing_credentials_stops_before_network(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    assert cli.main(["scan", "--block", "1", "--budget-usd", "1", "--output", str(tmp_path / "result.json")]) == 1
    assert "TYPESAFE_API_KEY" in capsys.readouterr().err


def test_scan_budget_exhaustion_keeps_output_absent(scan_workspace, capsys):
    workspace, calls = scan_workspace
    output = workspace / "too-cheap.json"
    assert cli.main(["scan", "--block", str(BLOCK_NUMBER), "--budget-usd", "0.000001", "--output", str(output)]) == 1
    assert not output.exists() and calls == []


def test_corrupt_cached_collection_never_triggers_paid_calls(scan_workspace, capsys):
    workspace, calls = scan_workspace
    saved = next((workspace / "scans").glob("*.json"))
    saved.write_text("{}")
    output = workspace / "corrupt.json"
    assert cli.main(["scan", "--block", str(BLOCK_NUMBER), "--budget-usd", "1", "--output", str(output)]) == 1
    assert not output.exists() and calls == []


def test_symlinked_cached_collection_stops_before_network(scan_workspace, capsys):
    workspace, calls = scan_workspace
    saved = workspace / "scans" / f"1-1-v{facts.FACTS_VERSION}.json"
    saved.symlink_to(workspace / "missing-target")
    output = workspace / "link.json"
    assert cli.main(["scan", "--block", "1", "--budget-usd", "1", "--output", str(output)]) == 1
    assert not output.exists() and calls == []


def test_budget_argument_cannot_be_omitted():
    with pytest.raises(SystemExit):
        cli.parser().parse_args(["scan", "--block", "1"])

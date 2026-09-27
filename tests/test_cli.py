import json
from pathlib import Path

import pytest

from jevscan_chainmonitor import cli

EVIDENCE = Path(__file__).resolve().parents[1] / "evidence"


def test_results_are_offline_and_do_not_need_credentials(monkeypatch, capsys):
    for name in ("TYPESAFE_API_KEY", "MAINNET_RPC_URL", "ETHERSCAN_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    assert cli.main(["results", "--evidence", str(EVIDENCE)]) == 0
    assert json.loads(capsys.readouterr().out)["historical"]["flagged_attack_transactions"] == 55


def test_an_expected_failure_prints_its_message(capsys):
    assert cli.main(["results", "--evidence", "missing"]) == 1
    assert capsys.readouterr().err.startswith("Error: missing/manifest.json is missing")


def test_failure_text_hides_credentials_and_control_characters(monkeypatch, capsys):
    monkeypatch.setenv("ETHERSCAN_API_KEY", "SYNTHETIC_SECRET_VALUE")

    def failure(*args):
        raise RuntimeError("explorer said SYNTHETIC_SECRET_VALUE\x1b[2J")
    monkeypatch.setattr(cli, "verify", failure)
    assert cli.main(["results"]) == 1
    err = capsys.readouterr().err
    assert "SYNTHETIC_SECRET_VALUE" not in err and "<ETHERSCAN_API_KEY>" in err and "\x1b" not in err


def test_an_unexpected_failure_asks_for_a_debug_report_and_debug_shows_the_traceback(monkeypatch, capsys):
    def failure(*args):
        raise KeyError("number")
    monkeypatch.setattr(cli, "verify", failure)
    assert cli.main(["results"]) == 1
    assert "Unexpected KeyError: 'number'" in capsys.readouterr().err
    assert cli.main(["results", "--debug"]) == 1
    assert "Traceback (most recent call last)" in capsys.readouterr().err


def test_score_without_budget_or_output_explains_the_dry_run(tmp_path, capsys):
    assert cli.main(["score", "--input", str(tmp_path / "c.json")]) == 1
    assert "--dry-run" in capsys.readouterr().err


@pytest.mark.parametrize("command", ["prepare", "preflight", "questions"])
def test_removed_commands_are_gone(command):
    with pytest.raises(SystemExit):
        cli.parser().parse_args([command])

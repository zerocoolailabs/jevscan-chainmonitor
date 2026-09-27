from pathlib import Path

import pytest

from jevscan_chainmonitor.evaluation import alerted, load_detector, verify

EVIDENCE = Path(__file__).resolve().parents[1] / "evidence"


def test_frozen_results_reproduce_exactly_offline():
    report = verify(EVIDENCE)
    assert report["historical"] == {
        "incidents": 50, "incidents_with_any_attack_flagged": 42,
        "incidents_with_every_declared_attack_flagged": 35,
        "declared_attack_transactions": 70, "flagged_attack_transactions": 55,
        "other_transactions": 12947, "potential_false_positives": 5,
    }
    assert report["held_out"] == {
        "incidents": 10, "incidents_with_any_attack_flagged": 7,
        "incidents_with_every_declared_attack_flagged": 7,
        "declared_attack_transactions": 10, "flagged_attack_transactions": 7,
        "other_transactions": 1022, "potential_false_positives": 0,
    }
    assert report["ordinary_observation"] == {"blocks": 20, "transactions": 5420, "alerts": 0}


def test_the_current_extractor_run_reproduces_exactly_offline():
    current = verify(EVIDENCE)["current_extractor"]
    assert current["facts_version"] == 13
    assert current["historical"] == {
        "incidents": 50, "incidents_with_any_attack_flagged": 46,
        "incidents_with_every_declared_attack_flagged": 40,
        "declared_attack_transactions": 70, "flagged_attack_transactions": 60,
        "other_transactions": 12947, "potential_false_positives": 7,
    }
    assert current["held_out"]["incidents_with_any_attack_flagged"] == 10
    assert current["held_out"]["potential_false_positives"] == 1
    assert current["ordinary_observation"] == {"blocks": 20, "transactions": 5420, "alerts": 0}
    repeat = current["same_day_repeat"]
    assert repeat["historical"]["incidents_with_any_attack_flagged"] == 46
    assert repeat["historical"]["potential_false_positives"] + repeat["held_out"]["potential_false_positives"] == 6
    assert repeat["held_out"]["incidents_with_any_attack_flagged"] == 10


@pytest.mark.parametrize("value", [True, float("nan"), -1, 1.1, "0.7"])
def test_malformed_scores_never_count_as_clean(value):
    detector = load_detector(EVIDENCE / "detector.json")
    with pytest.raises(ValueError):
        alerted(dict.fromkeys(detector["questions"], value), detector)

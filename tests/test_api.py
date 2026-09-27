"""The public API: a configurable detector and scoring with any classifier."""

import asyncio
import json

import pytest

import jevscan_chainmonitor as jcm
from jevscan_chainmonitor.evaluation import DETECTOR_PATH
from tests.test_benchmark import record

REVIEWED = {
    "c23_guided_lending_accounting_context": "0f0abd880284714756646d57285d5a8b0c94a2a021bda2a6214241bd3e2507cc",
    "p10_multi_pool_depletion": "60b489739ca1701dc54401044bd25d757f69e31c0ba21ceb7b9f441509901f87",
}


def test_the_bundled_detector_is_the_published_one():
    detector = jcm.load_detector()
    assert detector["model"] == "jev-1.13.0" and detector["threshold"] == 0.7
    assert detector["question_sha256"] == REVIEWED


def custom(tmp_path, **changes):
    value = json.loads(DETECTOR_PATH.read_text()) | changes
    path = tmp_path / "detector.json"
    path.write_text(json.dumps(value))
    return path


def test_a_detector_file_can_change_the_threshold_and_questions(tmp_path):
    assert jcm.load_detector(custom(tmp_path, threshold=0.5))["threshold"] == 0.5
    question = {"type": "noul", "instructions": "The transaction drains a lending pool."}
    detector = jcm.load_detector(custom(tmp_path, questions={"drain": question}, question_sha256=None))
    assert set(detector["question_sha256"]) == {"drain"}


@pytest.mark.parametrize("changes", [{"model": "jev-latest"}, {"threshold": 0}, {"threshold": 1.5},
                                     {"questions": {}}, {"question_sha256": {"p10_multi_pool_depletion": "0" * 64}}])
def test_an_invalid_detector_is_rejected(tmp_path, changes):
    with pytest.raises(ValueError):
        jcm.load_detector(custom(tmp_path, **changes))


class Keyword:
    """A stand-in classifier: scores 0.9 when the fact sheet mentions a flash loan."""

    def __init__(self):
        self.versions = []

    async def classify(self, state, questions, *, input_version):
        self.versions.append(input_version)
        score = 0.9 if state["flash_loans"] else 0.1
        return dict.fromkeys(questions, score)


def test_score_accepts_any_classifier_and_returns_the_fact_sheet():
    records = [record("0x" + "ab" * 32, 1), record("0x" + "cd" * 32, 2)]
    records[1] = records[1] | {"flash_loans": [{"lender": "sender", "detected_by": "shape", "asset": "ETH",
                                                "amount_raw": "1", "amount": 1.0, "usd": 2000.0}]}
    classifier = Keyword()
    results = asyncio.run(jcm.score(records, classifier))
    assert [row["flagged"] for row in results] == [False, True]
    assert [row["block"] for row in results] == [1, 2]
    assert results[1]["fact_sheet"]["flash_loans"] and classifier.versions == [jcm.FACTS_VERSION] * 2

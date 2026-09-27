"""Scoring rendered fact sheets with any classifier that answers the detector's questions."""

import asyncio
from typing import Protocol

from jevscan_chainmonitor.evaluation import alerted, load_detector
from jevscan_chainmonitor.facts import FACTS_VERSION, TxFacts
from jevscan_chainmonitor.views import render

SCORING_CONCURRENCY = 64  # the classifier answered 60 simultaneous requests in 0.3 s without refusing any


class Classifier(Protocol):
    """Anything that scores a fact sheet against the detector's questions. `input_version` is the facts version the
    state was rendered from, so a cached answer is never reused for a different rendering. TypeSafeClassifier is the
    implementation the published results use."""

    async def classify(self, state: dict, questions: dict, *, input_version: int) -> dict[str, float]:
        ...


async def classify_all(client: Classifier, states: list[dict], questions: dict, *, input_version: int,
                       concurrency: int = SCORING_CONCURRENCY) -> list[dict[str, float]]:
    """Scores for each state, in order, with at most `concurrency` requests in flight. The first failure cancels the
    requests still waiting and is raised."""
    gate = asyncio.Semaphore(concurrency)

    async def one(state: dict) -> dict[str, float]:
        async with gate:
            return await client.classify(state, questions, input_version=input_version)

    tasks = [asyncio.create_task(one(state)) for state in states]
    try:
        return await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise


async def score_states(classifier: Classifier, states: list[dict], detector: dict, *,
                       input_version: int) -> list[dict]:
    """{"scores", "flagged"} for each rendered fact sheet, in order."""
    scores = await classify_all(classifier, states, detector["questions"], input_version=input_version)
    return [{"scores": answers, "flagged": alerted(answers, detector)} for answers in scores]


async def score(records: list[TxFacts], classifier: Classifier, detector: dict | None = None) -> list[dict]:
    """Each transaction's position, scores, flag, and the fact sheet the classifier read, in order."""
    detector = detector or load_detector()
    if any(record["version"] != FACTS_VERSION for record in records):
        raise ValueError(f"Records must come from facts version {FACTS_VERSION}")
    sheets = [render(record) for record in records]
    results = await score_states(classifier, sheets, detector, input_version=FACTS_VERSION)
    return [{"transaction": record["tx"]["hash"], "block": record["tx"]["block"], "index": record["tx"]["index"]}
            | result | {"fact_sheet": sheet} for record, sheet, result in zip(records, sheets, results)]


async def scan(start: int, end: int, *, budget_usd: float, detector: dict | None = None) -> list[dict]:
    """Collect finalized blocks start..end and score every transaction with TypeSafe. `budget_usd` caps the
    workspace's cumulative classifier spending."""
    from jevscan_chainmonitor.collection import collect_facts
    from jevscan_chainmonitor.typesafe import TypeSafeClassifier
    from jevscan_chainmonitor.workspace import data_directory

    detector = detector or load_detector()
    records = await collect_facts(start, end)
    async with TypeSafeClassifier(data_directory() / "classifier", detector["model"], budget_usd) as classifier:
        return await score(records, classifier, detector)

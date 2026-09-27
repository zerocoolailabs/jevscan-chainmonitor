"""Jevscan Chain Monitor: flag Ethereum transactions that look like smart-contract exploits.

    import asyncio
    import jevscan_chainmonitor as jcm

    results = asyncio.run(jcm.scan(22785461, 22785461, budget_usd=1))
    flagged = [row for row in results if row["flagged"]]

`collect_facts` returns the facts without scoring them, `render` turns one record into the fact sheet a classifier
reads, and `score` accepts any object with the `Classifier` interface. No network activity occurs on import.
"""

from jevscan_chainmonitor.collection import collect_facts
from jevscan_chainmonitor.evaluation import load_detector
from jevscan_chainmonitor.facts import FACTS_VERSION, TxFacts
from jevscan_chainmonitor.scoring import Classifier, scan, score
from jevscan_chainmonitor.typesafe import TypeSafeClassifier
from jevscan_chainmonitor.views import render

__version__ = "0.1.0"
__all__ = ["FACTS_VERSION", "Classifier", "TxFacts", "TypeSafeClassifier", "collect_facts", "load_detector", "render",
           "scan", "score"]

"""The same transaction must render the same record in every process. Python randomizes string hashing per process,
so anything that names parties while iterating a set would number aliases differently from run to run."""

import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT = """
import json
from jevscan_chainmonitor import facts, views
from tests.helpers import BOT, SENDER, TOKEN, addr, chain_data, context, frame, kinds
from tests.test_facts import approval

spenders = [addr(200 + i) for i in range(6)]
trace = frame(SENDER, BOT, logs=[approval(TOKEN, BOT, spender) for spender in spenders])
ctx = context(kinds=kinds(wallet=[SENDER], contract=[BOT, *spenders]),
              creations={BOT: {"creator": SENDER, "block": 1, "timestamp": 1}})
record = facts.finish(facts.extract(*chain_data(trace)), ctx)
print(json.dumps([record, views.render(record)], sort_keys=True))
"""


def test_records_are_identical_across_hash_seeds():
    root = Path(__file__).resolve().parents[1]
    outputs = {subprocess.run([sys.executable, "-c", SCRIPT], cwd=root, capture_output=True, text=True, check=True,
                              env=os.environ | {"PYTHONHASHSEED": str(seed)}).stdout for seed in range(6)}
    assert len(outputs) == 1
    assert len(json.loads(outputs.pop())[0]["allowance_changes"]) == 3

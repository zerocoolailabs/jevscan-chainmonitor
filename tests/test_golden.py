"""A tripwire for the rule that results are only comparable within one TxFacts version: if the facts record or the
fact sheet the classifier reads changes, FACTS_VERSION must change with it. Stored classifier answers and the published
benchmark apply to one rendering only."""

import hashlib
import json

from jevscan_chainmonitor import facts, views
from tests.helpers import (
    BLOCK_NUMBER,
    BLOCK_TIME,
    BOT,
    LENDER,
    MIXER,
    POOL_A,
    SENDER,
    TOKEN,
    TOKEN_2,
    VICTIM,
    WALLET,
    addr,
    chain_data,
    context,
    frame,
    kinds,
    transfer,
)
from tests.test_facts import ONE, USDX, flash_loan_trace

# sha256 of the facts records and fact sheets for the transactions below, per TxFacts version. Add an entry when you
# bump FACTS_VERSION; never edit an existing one.
GOLDEN = {
    13: "cf61d3b1ca78cd529a5589590ca132e63634cc2b5c41fbecd774722981aa2a69",
}


def fixtures() -> list[facts.TxFacts]:
    pay = facts.SELECTOR["transfer(address,uint256)"]
    traces = [
        flash_loan_trace(repay=1_000_900 * USDX),
        frame(SENDER, WALLET, value=ONE, selector="0x"),
        frame(SENDER, BOT, value=2 * ONE, error="out of gas", calls=[frame(BOT, WALLET, value=ONE)]),
        frame(SENDER, POOL_A, calls=[frame(POOL_A, TOKEN, selector=pay, logs=[transfer(TOKEN, SENDER, POOL_A, 1_000 * USDX)]),
                                     frame(POOL_A, SENDER, value=ONE // 2, selector="0x")]),
        frame(SENDER, TOKEN_2, logs=[transfer(TOKEN_2, SENDER, facts.ZERO, 5 * ONE)], calls=[
            frame(TOKEN_2, TOKEN, selector=pay, logs=[transfer(TOKEN, TOKEN_2, SENDER, 1_000 * USDX)])]),
        frame(SENDER, BOT, kind="CREATE", calls=[
            frame(BOT, VICTIM, calls=[frame(VICTIM, TOKEN, logs=[transfer(TOKEN, facts.ZERO, BOT, 10_000_000 * USDX)])]),
            frame(BOT, VICTIM, calls=[frame(VICTIM, BOT, value=ONE, calls=[frame(BOT, VICTIM)])]),
            frame(BOT, TOKEN, selector=pay, logs=[transfer(TOKEN, BOT, POOL_A, 10_000_000 * USDX)])]),
    ]
    ctx = context(
        kinds=kinds(wallet=[SENDER, WALLET], contract=[BOT, LENDER, VICTIM, POOL_A, TOKEN_2]),
        labels={LENDER: {"name": "Big Lender: Pool", "category": "lending", "symbol": None}},
        creations={LENDER: {"creator": addr(98), "block": 5, "timestamp": BLOCK_TIME - 400 * 86400},
                   VICTIM: {"creator": addr(98), "block": 5, "timestamp": BLOCK_TIME - 90 * 86400}},
        balances_before={(VICTIM, TOKEN, BLOCK_NUMBER, i): 400_000 * USDX for i in range(8)}
        | {(POOL_A, facts.ETH, BLOCK_NUMBER, i): 40 * ONE for i in range(8)},
        decimals={TOKEN_2: 18}, function_names={"0x12345678": "flashLoan"},
        funding={SENDER: {"timestamp": BLOCK_TIME - 240, "funder": LENDER}},
        mixer_payouts={(SENDER, BLOCK_NUMBER, 3): (BLOCK_NUMBER - 25, MIXER)},
        prior_day_calls={(BOT, BLOCK_NUMBER): 0}, nonces_before={(WALLET, BLOCK_NUMBER): 0})
    return [facts.finish(facts.extract(*chain_data(trace, nonce=i)), ctx) for i, trace in enumerate(traces)]


def digest() -> str:
    rendered = [[record, views.render(record)] for record in fixtures()]
    return hashlib.sha256(json.dumps(rendered, sort_keys=True).encode()).hexdigest()


def test_facts_and_views_output_is_pinned_to_the_facts_version():
    assert facts.FACTS_VERSION in GOLDEN, "new FACTS_VERSION: add its digest to GOLDEN"
    assert digest() == GOLDEN[facts.FACTS_VERSION], (
        "what facts.py or views.py produce has changed: bump FACTS_VERSION and add the new digest, so answers given "
        f"to the old rendering are never scored as answers to the new one (new digest: {digest()})")

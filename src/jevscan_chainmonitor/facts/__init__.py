"""Raw chain data to versioned, language-neutral facts about each transaction.

    trace.extract(block, tx, receipt, trace) -> Core     the transaction alone: movements, call structure, events
    ledger.cast(core, ...)                    -> Cast     which addresses, assets and balances the record will mention
    record.finish(core, ctx)                  -> TxFacts  Core plus the lookups in a Context, which enrich.py fills

extract and cast do no I/O. finish updates the window memory in the Context, so it must run in chain order. naming.py
decides which external names a record may show, calltree.py prints the pruned call tree, and constants.py holds the
facts version and every heuristic threshold.

TxFacts is JSON. Raw amounts are decimal strings, because a uint256 does not fit a JSON number. views.render turns a
record into the classifier's input; it never sees Core.
"""

from jevscan_chainmonitor.facts.constants import (
    ESTABLISHED_SECONDS,
    ETH,
    FACTS_VERSION,
    FUNCTION_NAME,
    HIGH_VOLUME_TXS,
    INTERNAL_BALANCE_CHANGED,
    NEW_WALLET_NONCES,
    PUBLIC_SENDERS,
    SELECTOR,
    TOPIC,
    TRANSFER,
    TRANSFER_FROM,
    TREE_TOKEN_CAP,
    WALLET_KINDS,
    WETH,
    ZERO,
)
from jevscan_chainmonitor.facts.context import Context, Creation, Funding, Label, Price
from jevscan_chainmonitor.facts.ledger import (
    cast,
    contract_age,
    created_side,
    flash_loans_taken,
    implied_prices,
    net_ledger,
    reentries_shown,
    usd_value,
    whole_side,
)
from jevscan_chainmonitor.facts.naming import Naming
from jevscan_chainmonitor.facts.record import TxFacts, finish, logic_changes_of, remember_logic_changes, watched_before
from jevscan_chainmonitor.facts.trace import Core, Movement, extract, log_movement, pulls_of

__all__ = ["cast", "Context", "Core", "created_side", "Creation", "ESTABLISHED_SECONDS", "ETH", "extract", "FACTS_VERSION", "finish", "flash_loans_taken", "FUNCTION_NAME", "Funding", "HIGH_VOLUME_TXS", "implied_prices", "INTERNAL_BALANCE_CHANGED", "Label", "log_movement", "logic_changes_of", "Movement", "Naming", "net_ledger", "Price", "PUBLIC_SENDERS", "pulls_of", "reentries_shown", "SELECTOR", "TOPIC", "TRANSFER", "TRANSFER_FROM", "TREE_TOKEN_CAP", "TxFacts", "usd_value", "watched_before", "WETH", "whole_side", "ZERO", "NEW_WALLET_NONCES", "WALLET_KINDS", "contract_age", "remember_logic_changes"]

"""The finished record: `finish` turns a transaction and its lookups into versioned TxFacts."""

from collections import Counter
from dataclasses import dataclass, replace
from typing import TypedDict

from jevscan_chainmonitor.facts.calltree import call_tree, function_name
from jevscan_chainmonitor.facts.constants import (
    DRAIN_MIN_USD,
    ESTABLISHED_SECONDS,
    ETH,
    EVENTS_SHOWN,
    FACTS_VERSION,
    FRESH_CODE_SECONDS,
    LOGIC_EVENTS,
    NEW_WALLET_NONCES,
    PROCEEDS_MIN_USD,
    PROCEEDS_SHARE,
    PROTOCOLS_SHOWN,
    PUBLIC_SENDERS,
    PULL_MIN_USD,
    PULL_RECIPIENTS_SHOWN,
    SIDE_KEEPS_SHARE,
    SLOT_SECONDS,
    WALLET_KINDS,
    ZERO,
)
from jevscan_chainmonitor.facts.context import Context
from jevscan_chainmonitor.facts.ledger import (
    cast,
    created_side,
    flash_loans_taken,
    flows,
    implied_prices,
    net_ledger,
    reentries_shown,
    shown_parties,
    usd_value,
    whole_side,
)
from jevscan_chainmonitor.facts.naming import Naming, amount_facts, by_value
from jevscan_chainmonitor.facts.trace import Core, frame_holding, frames_of, is_precompile, pulls_of


class TxFacts(TypedDict):
    version: int
    tx: dict  # hash, block, index, raw addresses: for the harness and the raw view only
    status: str  # success, failed
    trivial: bool
    sender: dict
    entry: dict | None  # None when the transaction is sent to a wallet
    parties: dict[str, dict]  # alias -> what is known about the address
    assets: dict[str, dict]  # asset alias -> what is known about the token
    ledger: list[dict]
    ledger_logs_only: list[dict]  # what a receipt alone shows: no internal ETH movement
    minted: list[dict]
    lending_accounting_issuances: list[dict]  # a lending-pool Borrow event linked to a same-pool token issuance to its borrower
    sender_side: dict
    drains: list[dict]
    pulls: list[dict]  # tokens taken with transferFrom from addresses outside the sender's side, by spender
    allowance_changes: list[dict]  # standalone token approvals involving the sender's side
    internal_balance_changes: list[dict]  # protocol accounting credits/debits involving the sender's side
    positions_moved: list[dict]  # ERC-1155 position transfers, including raw identifier and quantity where encoded
    self_minted_collateral: list[dict]  # an asset the side minted itself, posted to a contract that then paid it
    precursor: bool  # deploys a contract and moves positions or unpriced assets while no priced value moves
    earlier_by_this_sender: list[dict]  # this sender's precursor-shaped transactions earlier in the window
    logic_changes: list[dict]  # contracts whose logic, control, or modules this transaction changed
    heightened: list[dict]  # contracts touched here whose logic or control changed earlier in the window
    flash_loans: list[dict]
    reentrancy: list[dict]
    privileged_events: list[dict]
    events: list[dict]
    protocols_touched: list[str]
    call_shape: dict
    call_tree: list[str]
    mev: dict


def logic_changes_of(core: Core, side: list[str], age_of) -> list[tuple[str, str, int]]:
    """(contract, what changed, the contract's age) for an established contract whose logic or control this
    transaction changed: a logic or control event, or a delegatecall into the sender's own contract or into code
    created within the last day. `age_of(address)` gives seconds since creation, 0 for a contract created here, None
    when unknown."""
    changes: list[tuple[str, str, int]] = []
    for change in core.privileged:  # a fresh deployment's own OwnershipTransferred is boilerplate, not a change
        age = age_of(change["emitter"])
        if change["event"] in LOGIC_EVENTS and age is not None and age > ESTABLISHED_SECONDS:
            changes.append((change["emitter"], f"{change['event']} event", age))
    born = {contract for _, contract in core.created}
    for context, target, _ in core.delegations:
        context_age, target_age = age_of(context), age_of(target)
        if context_age is None or context_age <= ESTABLISHED_SECONDS or context in side:
            continue
        if target in side or target in born:
            when = "created in this transaction" if not target_age else f"created {span_seconds(target_age)} earlier"
            changes.append((context, f"ran code from the sender's own contract ({when}) by delegatecall", context_age))
        elif target_age is not None and target_age <= FRESH_CODE_SECONDS:
            when = "created in this transaction" if target_age == 0 else f"created {span_seconds(target_age)} earlier"
            changes.append((context, f"ran code from a contract {when} by delegatecall", context_age))
    return list(dict.fromkeys(changes))


def remember_logic_changes(watch: dict[str, dict], changes: list[tuple[str, str, int]],
                           prior_day_senders: dict[tuple[str, int], int], block: int, index: int) -> None:
    """Add each contract whose logic or control this transaction changed to the window's watch. A protocol that many
    wallets call and that upgraded its code is doing business as usual; the watch is for a contract few wallets call,
    such as a treasury or a multisig."""
    for address, what, age in changes:
        if prior_day_senders.get((address, block), 0) < PUBLIC_SENDERS:
            watch.setdefault(address, {"block": block, "index": index, "what": what, "age_seconds": age})


def watched_before(watch: dict[str, dict], address: str | None, block: int, index: int) -> bool:
    """Whether `address` had its logic or control changed earlier in the window than this transaction."""
    entry = watch.get(address) if address else None
    return bool(entry) and (entry["block"], entry["index"]) < (block, index)


def proceeds_reason(party: str, side: list[str], sender: str, block: int, names: "Naming", ctx: "Context") -> str | None:
    """Why value that landed on `party` counts as the sender's side's: a labeled mixer, a wallet with very few prior
    transactions, a wallet the sender funded, or one funded from the same source as the sender."""
    label = names.label(party)
    if label and label["category"] == "mixer":
        return "a labeled mixer"
    if ctx.kinds.get((party, block)) not in WALLET_KINDS:
        return None
    nonce = ctx.nonces_before.get((party, block))
    if nonce is not None and nonce < NEW_WALLET_NONCES:
        return "a wallet with no prior transactions" if nonce == 0 else f"a wallet with only {nonce} prior transaction{'s' if nonce != 1 else ''}"
    funding = ctx.funding.get(party)
    if funding:
        if funding["funder"] in side:
            return "a wallet the sender's side funded"
        sender_funding = ctx.funding.get(sender)
        if sender_funding and sender_funding["funder"] == funding["funder"]:
            return "a wallet funded from the same source as the sender"
    return None


def span_seconds(seconds: int) -> str:
    for size, name in ((86400 * 365, "year"), (86400 * 30, "month"), (86400, "day"), (3600, "hour"), (60, "minute")):
        if seconds >= size:
            n = seconds // size
            return f"{n} {name}{'s' if n != 1 else ''}"
    return f"{seconds} seconds"


def ledger_rows(ledger: dict[str, dict[str, int]], shown: list[str], names: Naming, ctx: Context) -> list[dict]:
    rows = []
    for party in shown:
        changes = [{"direction": "gained" if net > 0 else "lost"} | amount_facts(asset, abs(net), names, ctx)
                   for asset, net in ledger[party].items()]
        changes.sort(key=lambda c: (-(c["usd"] or 0.0), c["asset"]))
        gave = sum(c["usd"] for c in changes if c["usd"] is not None and c["direction"] == "lost")
        received = sum(c["usd"] for c in changes if c["usd"] is not None and c["direction"] == "gained")
        rows.append({"party": names.party(party), "changes": changes, "gave_usd": round(gave, 2),
                     "received_usd": round(received, 2), "net_usd": round(received - gave, 2)})
    return rows


def own_capital_usd(core: Core, side: list[str], ctx: Context) -> float:
    """Priced value the sender's side had to hold before the transaction: for each asset, how far its running balance
    over the movements dips below zero. Borrowed funds arrive before they are spent, so they never count."""
    running: dict[str, int] = {}
    lowest: dict[str, int] = {}
    for m in core.movements:
        change = (m.recipient in side) - (m.sender in side)
        if change:
            running[m.asset] = running.get(m.asset, 0) + change * m.amount
            lowest[m.asset] = min(lowest.get(m.asset, 0), running[m.asset])
    return sum(usd_value(asset, -low, ctx.prices, ctx.eth_usd) or 0.0 for asset, low in lowest.items() if low < 0)


@dataclass
class Subject:
    """One transaction as the record builders see it. `ctx` includes the prices implied by this transaction."""
    core: Core
    ctx: Context
    names: Naming
    side: list[str]  # the sender first, then its contracts
    ledger: dict[str, dict[str, int]]
    flow: dict[str, tuple[float, float]]
    block: int
    index: int


def finish(core: Core, ctx: Context) -> TxFacts:
    """The finished record for one transaction. Aliases are numbered in the order parties are first named, so the
    sections below are built in a fixed order. It updates the window memory in `ctx`: call it in chain order."""
    tx, block = core.tx, int(core.tx["blockNumber"], 16)
    sender, entry_address = tx["from"].lower(), core.root.target
    index = int(tx["transactionIndex"], 16)
    # A contract whose logic or control changed earlier in the window is nobody's bot, whoever calls it now.
    entry_is_public = (ctx.prior_day_senders.get((entry_address, block), 0) >= PUBLIC_SENDERS
                       or watched_before(ctx.contract_watch, entry_address, block, index))
    needed = cast(core, ctx.prices, ctx.eth_usd, ctx.labels, entry_is_public)
    side = whole_side(core, needed.parties, ctx.creations, block)
    implied = implied_prices(core, side, ctx.prices, ctx.eth_usd, ctx.decimals)
    if implied:  # a shallow copy: the shared lookups and the window memory stay the same objects
        ctx = replace(ctx, prices=ctx.prices | implied)
    names = Naming(core, ctx, side)
    names.party(sender)
    if entry_address:
        names.party(entry_address)

    ledger, logs_only = net_ledger(core.movements), net_ledger(core.log_movements)
    shown = shown_parties(ledger, core, ctx.prices, ctx.eth_usd)
    rows = ledger_rows(ledger, shown, names, ctx)
    logs_rows = ledger_rows(logs_only, shown_parties(logs_only, core, ctx.prices, ctx.eth_usd), names, ctx)
    s = Subject(core, ctx, names, side, ledger, flows(ledger, ctx.prices, ctx.eth_usd), block, index)

    sender_side = sender_side_facts(s)
    minted, lending_accounting_issuances = minted_facts(s, shown)
    collateral = self_minted_collateral_facts(s)
    allowance_changes = allowance_facts(s)
    internal_balance_changes = internal_balance_facts(s)
    positions_moved = position_facts(s)
    precursor, earlier_notes = precursor_facts(s, sender_side)
    logic_changes, heightened = logic_facts(s)
    drains = drain_facts(s, needed.drains)
    pulls = pull_facts(s, entry_address)
    flash_loans = [{"lender": names.party(loan["lender"]), "detected_by": loan["source"]}
                   | amount_facts(loan["asset"], loan["amount"], names, ctx)
                   for loan in flash_loans_taken(core, ctx.labels, entry_is_public)]
    reentrancy = [{"contract": names.party(contract), "through": names.party(through), "read_only": static}
                  for contract, through, static in reentries_shown(core, ctx.labels, entry_is_public)]
    privileged = [{"contract": names.party(p["emitter"]), "event": p["event"],
                   "subject": names.party(p["subject"]) if p["subject"] and p["subject"] != ZERO else None}
                  for p in core.privileged]
    events = event_facts(s, needed.parties)
    touched, call_shape = call_shape_facts(s)
    sender_facts = sender_identity_facts(s)
    entry = None
    if entry_address:
        entry = {"alias": names.party(entry_address), "function": function_name(entry_address, core.root.selector, names, ctx),
                 "calls_in_prior_day": ctx.prior_day_calls.get((entry_address, block))}

    value = int(tx["value"], 16)
    return {
        "version": FACTS_VERSION,
        "tx": {"hash": tx["hash"], "block": block, "index": index, "type": tx.get("type"),
               "from": sender, "to": tx["to"].lower() if tx.get("to") else None,
               "creates": None if tx.get("to") else entry_address,
               "selector": core.root.selector if tx.get("to") else None, "input_bytes": (len(tx["input"]) - 2) // 2,
               "value_wei": str(value), "gas_used": core.gas_used, "log_count": core.log_count},
        "status": "success" if core.succeeded else "failed",
        "trivial": core.trivial,
        "sender": sender_facts,
        "entry": entry,
        "ledger": rows,
        "ledger_logs_only": logs_rows,
        "minted": minted,
        "lending_accounting_issuances": lending_accounting_issuances,
        "sender_side": sender_side,
        "drains": drains,
        "pulls": pulls,
        "allowance_changes": allowance_changes[:PULL_RECIPIENTS_SHOWN],
        "internal_balance_changes": internal_balance_changes[:PULL_RECIPIENTS_SHOWN],
        "positions_moved": positions_moved,
        "self_minted_collateral": collateral,
        "precursor": precursor,
        "earlier_by_this_sender": earlier_notes,
        "logic_changes": logic_changes,
        "heightened": heightened,
        "flash_loans": flash_loans,
        "reentrancy": reentrancy,
        "privileged_events": privileged,
        "events": events,
        "protocols_touched": touched[:PROTOCOLS_SHOWN],
        "call_shape": call_shape,
        "call_tree": call_tree(core, names, ctx),
        "mev": {"position": index + 1, "block_transactions": core.block_tx_count,
                "builder_payment_usd": round(core.builder_payment_wei / 1e18 * ctx.eth_usd, 2),
                "fee_usd": round(core.fee_wei / 1e18 * ctx.eth_usd, 2),
                "value_sent_usd": round(value / 1e18 * ctx.eth_usd, 2)},
        # Last, so every alias the fields above introduced is described.
        "parties": names.parties,
        "assets": names.assets,
    }


def sender_side_facts(s: Subject) -> dict:
    """The sender's side: its net result, the proceeds it sent to wallets that count as its own, the largest gain that
    went elsewhere, the capital it put in, and what it burned."""
    core, ctx, names, side, flow = s.core, s.ctx, s.names, s.side, s.flow
    sender = side[0]
    unpriced = sorted({names.asset(a) for p in side for a in s.ledger.get(p, {})
                       if usd_value(a, 1, ctx.prices, ctx.eth_usd) is None})
    burned: Counter = Counter()
    for m in core.movements:
        if m.recipient == ZERO and m.sender in side:
            burned[m.asset] += m.amount
    side_net = sum(flow[p][1] - flow[p][0] for p in side if p in flow)
    proceeds, extended = [], list(side)
    losses = [flow[p][0] - flow[p][1] for p in flow if p not in side and p != core.builder]
    largest_loss = max(losses, default=0.0)
    largest_gain = None
    for party in sorted((p for p in flow if p not in side and p not in (core.builder, ZERO)),
                        key=lambda p: flow[p][0] - flow[p][1]):
        gain = flow[party][1] - flow[party][0]
        if gain < PROCEEDS_MIN_USD:
            break
        reason = proceeds_reason(party, side, sender, s.block, names, ctx)
        if reason:
            proceeds.append({"party": names.party(party), "reason": reason, "usd": round(gain, 2)})
            extended.append(party)
        elif largest_gain is None and largest_loss >= DRAIN_MIN_USD and gain >= PROCEEDS_SHARE * largest_loss \
                and side_net < SIDE_KEEPS_SHARE * largest_loss:
            largest_gain = {"party": names.party(party), "usd": round(gain, 2)}
    return {"members": [names.party(p) for p in side],
            "net_usd": round(sum(flow[p][1] - flow[p][0] for p in extended if p in flow), 2),
            "own_side_net_usd": round(side_net, 2), "proceeds_to": proceeds, "largest_gain_elsewhere": largest_gain,
            "own_capital_usd": round(own_capital_usd(core, side, ctx), 2), "unpriced_assets": unpriced,
            "burned": by_value([amount_facts(a, n, names, ctx) for a, n in burned.items()])}


def minted_facts(s: Subject, shown: list[str]) -> tuple[list[dict], list[dict]]:
    """Tokens minted to shown parties or the sender's side, with their issuer and what the issuer received from the
    side; and the mints a labeled lender made to the side in the same transaction as its Borrow event."""
    core, ctx, names, side = s.core, s.ctx, s.names, s.side
    minted: dict[tuple[str, str], list[int]] = {}  # (asset, recipient) -> [amount, first movement index]
    for i, m in enumerate(core.movements):
        if m.sender == ZERO and m.recipient in [*shown, *created_side(core)]:  # the side may sell a mint at once
            minted.setdefault((m.asset, m.recipient), [0, i])[0] += m.amount
    minted_rows = []
    lending_accounting_issuances = []
    lending_borrow_emitters = {
        emitter for emitter, event in core.events
        if event == "Borrow" and (label := names.label(emitter)) and label["category"] == "lending"
    }
    for (asset, recipient), (amount, first) in minted.items():
        call = frame_holding(core.root, first, asset)
        issuer = call.caller if call else None  # the contract whose call made the token mint
        row = {"to": names.party(recipient), "issued_by": names.party(issuer, "contract") if issuer else None,
               "issuer_received_from_side": None} | amount_facts(asset, amount, names, ctx)  # a caller below the root is a contract
        if issuer and recipient in side and issuer not in side:  # the robbed party, if there is one, is the issuer
            got: Counter = Counter()
            for m in core.movements:
                if m.sender in side and m.recipient == issuer:
                    got[m.asset] += m.amount
            row["issuer_received_from_side"] = by_value([amount_facts(a, n, names, ctx) for a, n in got.items()])
        minted_rows.append(row)
        if recipient in side and issuer in lending_borrow_emitters:
            lending_accounting_issuances.append({"borrower": names.party(recipient), "lender": names.party(issuer, "contract"),
                                                 "issued": amount_facts(asset, amount, names, ctx)})
    minted_rows.sort(key=lambda row: (-(row["usd"] or 0.0), row["asset"], row["to"]))
    lending_accounting_issuances.sort(key=lambda row: (row["lender"], row["borrower"], row["issued"]["asset"]))
    return minted_rows, lending_accounting_issuances


def self_minted_collateral_facts(s: Subject) -> list[dict]:
    """An asset the side minted itself, posted to a contract that then paid the side something else."""
    core, ctx, names, side = s.core, s.ctx, s.names, s.side
    collateral = []
    for i, mint in enumerate(core.movements):
        if not (mint.sender == ZERO and mint.recipient in side):
            continue
        call = frame_holding(core.root, i, mint.asset)
        if not call or call.caller not in side:  # minted by someone else's contract: a purchase or a reward, not self-issue
            continue
        posted = next(((j, m) for j, m in enumerate(core.movements) if j > i and m.asset == mint.asset
                       and m.sender in side and m.recipient not in side and m.recipient != ZERO), None)
        if not posted:
            continue
        j, deposit = posted
        received = next((m for k, m in enumerate(core.movements) if k > j and m.recipient in side and m.asset != mint.asset
                         and (m.sender == deposit.recipient or (m.sender == ZERO and (issue := frame_holding(core.root, k, m.asset))
                                                                 and issue.caller == deposit.recipient))), None)
        if received:
            collateral.append({"posted_to": names.party(deposit.recipient, "contract"),
                               "posted": amount_facts(deposit.asset, deposit.amount, names, ctx),
                               "received": amount_facts(received.asset, received.amount, names, ctx)})
            break
    return collateral


def allowance_facts(s: Subject) -> list[dict]:
    """Nonzero token approvals granted by or to the sender's side, largest first."""
    ctx, names, side = s.ctx, s.names, s.side
    allowance_changes = []
    for asset, owner, spender, amount in sorted(s.core.approvals):  # a set: sorted, so aliases number the same every run
        if amount and (owner in side or spender in side):
            allowance_changes.append({"asset": amount_facts(asset, amount, names, ctx), "owner": names.party(owner),
                                      "spender": names.party(spender, "contract"), "owner_is_sender_side": owner in side,
                                      "spender_is_sender_side": spender in side})
    allowance_changes.sort(key=lambda row: (-(row["asset"]["usd"] or 0.0), row["asset"]["asset"], row["owner"], row["spender"],
                                            int(row["asset"]["amount_raw"])))
    return allowance_changes


def internal_balance_facts(s: Subject) -> list[dict]:
    """Net credits and debits to the sender's side in a protocol's internal accounting, largest first."""
    ctx, names, side = s.ctx, s.names, s.side
    internal_by_account_asset: dict[tuple[str, str, str], int] = {}
    for vault, account, asset, delta in s.core.internal_balances:
        if account in side:
            key = (vault, account, asset)
            internal_by_account_asset[key] = internal_by_account_asset.get(key, 0) + delta
    internal_balance_changes = []
    for (vault, account, asset), delta in internal_by_account_asset.items():
        if delta:
            internal_balance_changes.append({"vault": names.party(vault, "contract"), "account": names.party(account),
                                             "account_is_sender_side": account in side, "direction": "credited" if delta > 0 else "debited"}
                                            | amount_facts(asset, abs(delta), names, ctx))
    internal_balance_changes.sort(key=lambda row: (-(row["usd"] or 0.0), row["asset"], row["vault"], row["account"]))
    return internal_balance_changes


def position_facts(s: Subject) -> list[dict]:
    """ERC-1155 position transfers grouped by issuer, with raw identifiers and quantities where encoded."""
    core, names, side = s.core, s.names, s.side
    positions_moved = []
    for issuer in dict.fromkeys(emitter for emitter, _, _, _, _ in core.positions):
        mine = [(source, recipient, token_id, amount) for emitter, source, recipient, token_id, amount in core.positions if emitter == issuer]
        recipients = [names.party(recipient) for recipient in dict.fromkeys(recipient for _, recipient, _, _ in mine)
                      if recipient != ZERO][:PULL_RECIPIENTS_SHOWN]
        positions_moved.append({"issuer": names.party(issuer, "contract"), "count": len(mine), "to": recipients,
                                "to_sender_side": sum(recipient in side for _, recipient, _, _ in mine),
                                "minted": sum(source == ZERO for source, _, _, _ in mine),
                                "raw_ids": [str(token_id) for _, _, token_id, _ in mine if token_id is not None][:4],
                                "raw_amounts": [str(amount) for _, _, _, amount in mine if amount is not None][:4]})
    return positions_moved


def precursor_facts(s: Subject, sender_side: dict) -> tuple[bool, list[dict]]:
    """Whether this transaction has the shape of a preparation step, and the sender's earlier ones in the window. A
    preparation step is remembered in the window memory for the sender's later transactions."""
    core, ctx, side, block, index = s.core, s.ctx, s.side, s.block, s.index
    sender = side[0]
    side_unpriced_moves = sum(1 for m in core.movements if (m.sender in side or m.recipient in side) and m.asset != ETH
                              and m.asset not in core.nft_collections and usd_value(m.asset, 1, ctx.prices, ctx.eth_usd) is None)
    nft_moves = sum(1 for m in core.movements if m.asset in core.nft_collections)
    precursor = bool(core.created) and (nft_moves > 0 or bool(core.positions) or side_unpriced_moves > 0) \
        and abs(sender_side["net_usd"]) < 1 and sender_side["own_capital_usd"] < 1
    earlier_notes = [{"blocks_earlier": block - note["block"], "summary": note["summary"]}
                     for note in ctx.actor_notes.get(sender, []) if (note["block"], note["index"]) < (block, index)]
    if precursor:
        ctx.actor_notes.setdefault(sender, []).append({
            "block": block, "index": index,
            "summary": (f"deployed {len(core.created)} contract{'s' if len(core.created) != 1 else ''} and moved "
                        f"{nft_moves + len(core.positions) + side_unpriced_moves} positions or unpriced tokens "
                        "while no priced value moved")})
    return precursor, earlier_notes


def logic_facts(s: Subject) -> tuple[list[dict], list[dict]]:
    """Logic or control changes made by this transaction, and contracts it touches whose logic or control changed
    earlier in the window. A change to a contract few wallets call is remembered for later transactions."""
    core, ctx, names, block, index = s.core, s.ctx, s.names, s.block, s.index
    effective_frames = [f for f in frames_of(core.root) if not f.failed and f.target and not is_precompile(f.target)]
    changes = logic_changes_of(core, s.side, names.age)
    logic_changes = [{"contract": names.party(address, "contract"), "what": what, "contract_age_seconds": age}
                     for address, what, age in changes]
    touched_here = {f.context for f in effective_frames} | {f.target for f in effective_frames}
    heightened = []
    for address, watch in ctx.contract_watch.items():
        if address in touched_here and (watch["block"], watch["index"]) < (block, index):
            heightened.append({"contract": names.party(address, "contract"), "what": watch["what"],
                               "blocks_earlier": block - watch["block"], "contract_age_seconds": watch["age_seconds"]})
    remember_logic_changes(ctx.contract_watch, changes, ctx.prior_day_senders, block, index)
    return logic_changes, heightened


def drain_facts(s: Subject, candidates: list[tuple[str, str]]) -> list[dict]:
    """The largest losses outside the sender's side, each with its share of the holder's prior balance and what the
    holder received in return, which says whether the loss was a sale or a drain."""
    core, ctx, names, ledger, flow = s.core, s.ctx, s.names, s.ledger, s.flow
    drains = []
    for holder, asset in candidates:
        if holder in s.side:  # a contract the sender deployed earlier: its loss is the sender's own business
            continue
        position = (holder, asset, s.block, s.index)
        before = ctx.balances_before.get(position)
        lost, (gave, received) = -ledger[holder][asset], flow[holder]
        earlier = ctx.same_sender_deposits.get(position)
        drains.append({"party": names.party(holder), "share_of_prior_balance": round(lost / before, 4) if before else None,
                       "gave_usd": round(gave, 2), "received_usd": round(received, 2),
                       "received_assets": [a["asset"] for a in by_value([amount_facts(a, n, names, ctx)
                                                                         for a, n in ledger[holder].items() if n > 0])],
                       "unpriced_legs": any(usd_value(a, 1, ctx.prices, ctx.eth_usd) is None for a in ledger[holder]),
                       "unpriced_received": any(n > 0 and usd_value(a, 1, ctx.prices, ctx.eth_usd) is None
                                                for a, n in ledger[holder].items()),
                       "events_recorded": sorted({name for emitter, name in core.events if emitter == holder})[:3],
                       "same_sender_put_in_earlier": ({"index": earlier[1]} | amount_facts(asset, earlier[0], names, ctx)
                                                      if earlier else None)}
                      | amount_facts(asset, lost, names, ctx))
    return drains


def pull_facts(s: Subject, entry_address: str | None) -> list[dict]:
    """Tokens taken with transferFrom from wallets outside the sender's side, grouped by spender. A pull from a
    contract is a protocol's own plumbing (a vault funding a market); the pulls that matter come from wallets, or from
    addresses whose code was not looked up."""
    ctx, names, side = s.ctx, s.names, s.side
    pulls = []
    pulled = [p for p in pulls_of(s.core, side) if ctx.kinds.get((p["owner"], s.block)) != "contract"]
    for spender in dict.fromkeys(p["spender"] for p in pulled):
        mine = [p for p in pulled if p["spender"] == spender]
        by_asset: Counter = Counter()
        for p in mine:
            by_asset[p["asset"]] += p["amount"]
        amounts = by_value([amount_facts(a, n, names, ctx) for a, n in by_asset.items()])
        priced = [a["usd"] for a in amounts if a["usd"] is not None]
        if sum(priced) < PULL_MIN_USD:
            continue
        pulls.append({"spender": names.party(spender, "contract" if spender != side[0] else None),
                      "spender_is": ("the sender" if spender == side[0] else "the sender's contract" if spender in side
                                     else "the contract the sender called" if spender == entry_address else "another contract"),
                      "owners": len({p["owner"] for p in mine}), "transfers": len(mine),
                      "recipients": [names.party(r) for r in dict.fromkeys(p["recipient"] for p in mine)][:PULL_RECIPIENTS_SHOWN],
                      "approved_in_this_transaction": sum(p["approved_now"] for p in mine),
                      "usd": round(sum(priced), 2) if priced else None, "assets": [a["asset"] for a in amounts][:3]})
    return pulls


def event_facts(s: Subject, known: list[str]) -> list[dict]:
    """The most frequent known events. An emitter the record already mentions, or looked up, is named; any other is
    described only as an exchange pool or another contract."""
    core, names = s.core, s.names

    def emitter_name(emitter: str) -> str:
        if emitter in names.alias_of or emitter in known:
            return names.party(emitter)
        return "an exchange pool" if emitter in core.swap_emitters else "another contract"

    return [{"contract": emitter_name(emitter), "event": name, "count": n}
            for (emitter, name), n in Counter(core.events).most_common(EVENTS_SHOWN)]


def call_shape_facts(s: Subject) -> tuple[list[str], dict]:
    """The labeled protocols the calls reached, and the size and shape of the call tree."""
    core, ctx, names = s.core, s.ctx, s.names
    effective = [f for f in frames_of(core.root) if not f.failed and f.target and not is_precompile(f.target)]
    touched: list[str] = []
    for f in effective:
        label = names.label(f.context)
        if label and label["category"] != "token" and label["name"] not in touched:
            touched.append(label["name"])
    repeated = [{"target": names.party(target, "contract"), "function": function_name(target, selector, names, ctx),
                 "count": n} for target, selector, n in core.repeated]
    return touched, {"calls": core.calls, "max_depth": core.max_depth,
                     "distinct_contracts": len({f.target for f in effective}), "labeled_protocols": len(touched),
                     "contracts_created": len(core.created), "contracts_destroyed": len(core.destroyed),
                     "reverted_inner_calls": core.reverted_inner_calls, "repeated_calls": repeated,
                     "nft_transfers": core.nft_transfers, "other_events": core.other_events}


def sender_identity_facts(s: Subject) -> dict:
    """Who the sender is: its kind, history, label, first funding, and any recent mixer payout."""
    core, ctx, names, block = s.core, s.ctx, s.names, s.block
    sender = s.side[0]
    funding = ctx.funding.get(sender)
    sender_label = names.label(sender)
    sender_facts = {"kind": ctx.kinds[(sender, block)], "prior_transactions": int(core.tx["nonce"], 16),
                    "label": sender_label["name"] if sender_label else None,
                    "category": sender_label["category"] if sender_label else None,
                    "funding_looked_up": sender in ctx.funding, "first_funded_seconds_earlier": None,
                    "funded_by": None, "funded_by_category": None, "mixer_funded_within_30_days": None,
                    "mixer_paid_seconds_earlier": None, "mixer_paid_by": None}
    if funding:
        funder = ctx.labels.get(funding["funder"])  # a funder's label needs no age check: the funding is in the past
        sender_facts |= {"first_funded_seconds_earlier": max(0, core.block_timestamp - funding["timestamp"]),
                         "funded_by": funder["name"] if funder else None,
                         "funded_by_category": funder["category"] if funder else None}
    position = (sender, block, s.index)
    if position in ctx.mixer_payouts:
        payout = ctx.mixer_payouts[position]
        sender_facts["mixer_funded_within_30_days"] = payout is not None
        if payout:
            paid_block, pool = payout  # every pool in the payout list comes from the label file
            sender_facts |= {"mixer_paid_seconds_earlier": (block - paid_block) * SLOT_SECONDS,
                             "mixer_paid_by": ctx.labels[pool]["name"]}
    return sender_facts

"""Net asset changes per party, their priced value, the sender's side, and the lookups a record needs (`cast`)."""

from jevscan_chainmonitor.facts.constants import (
    DRAIN_CANDIDATES,
    DRAIN_MIN_USD,
    ETH,
    IMPLIED_MIN_USD,
    IMPLIED_PASSES,
    IMPLIED_REACH,
    LEDGER_PARTIES,
    MULTISIG_EVENTS,
    NEW_WALLET_CHECKS,
    PROCEEDS_SHARE,
    SIDE_KEEPS_SHARE,
    WETH,
    ZERO,
)
from jevscan_chainmonitor.facts.context import Cast, Creation, Label, Price
from jevscan_chainmonitor.facts.trace import Core, Movement, frames_of, is_precompile


def net_ledger(movements: list[Movement]) -> dict[str, dict[str, int]]:
    """party -> asset -> net change. A mint or burn (a transfer from or to the zero address) is booked against the
    token's own contract, so a vault that pays out assets is seen to take its shares back. A contract that only
    issues or redeems its own token is no party, and neither is the WETH wrapper, whose ETH always matches its WETH."""
    ledger: dict[str, dict[str, int]] = {}
    for m in movements:
        for party, sign in ((m.sender, -1), (m.recipient, 1)):
            party = m.asset if party == ZERO and m.asset != ETH else party
            changes = ledger.setdefault(party, {})
            changes[m.asset] = changes.get(m.asset, 0) + sign * m.amount
    return {party: {a: n for a, n in changes.items() if n} for party, changes in ledger.items()
            if party not in (ZERO, WETH) and any(n for a, n in changes.items() if a != party)}


def usd_value(asset: str, amount: int, prices: dict[str, Price], eth_usd: float) -> float | None:
    if asset == ETH:
        return amount / 1e18 * eth_usd
    price = prices.get(asset)
    if price is None or (price.get("max_amount") is not None and abs(amount) > price["max_amount"]):
        return None  # an implied price says nothing about a quantity far beyond the exchange that set it
    return amount / 10 ** price["decimals"] * price["usd"]


def flows(ledger: dict[str, dict[str, int]], prices: dict[str, Price], eth_usd: float) -> dict[str, tuple[float, float]]:
    """party -> (priced value given out, priced value received)."""
    out = {}
    for party, changes in ledger.items():
        values = [usd_value(asset, n, prices, eth_usd) for asset, n in changes.items()]
        out[party] = (-sum(v for v in values if v is not None and v < 0), sum(v for v in values if v and v > 0))
    return out


def created_side(core: Core) -> list[str]:
    """The sender and the contracts its side created in this transaction, in creation order."""
    side = [core.tx["from"].lower()]
    for creator, contract in core.created:
        if creator in side:
            side.append(contract)
    return side


def contract_age(core: Core, creations: dict[str, Creation | None], block: int, address: str) -> int | None:
    """Seconds since `address` was created, as of this transaction: 0 when it was created here, None when its creation
    is unknown or came later."""
    if any(contract == address for _, contract in core.created):
        return 0
    creation = creations.get(address)
    if creation is None or creation["block"] > block:
        return None
    return max(0, core.block_timestamp - creation["timestamp"])


def whole_side(core: Core, parties: list[str], creations: dict[str, Creation], block: int) -> list[str]:
    """The sender, the contracts its side created in this transaction, the contracts it deployed earlier (among the
    parties looked up), and, again, anything those created in this transaction: proceeds sent to a contract that an
    older sender contract deploys on the fly are still the sender's."""
    side = created_side(core)
    changed = True
    while changed:
        changed = False
        for address in parties:
            creation = creations.get(address)
            if address not in side and creation and creation.get("creator") in side and creation["block"] <= block:
                side.append(address)
                changed = True
        for creator, contract in core.created:
            if creator in side and contract not in side:
                side.append(contract)
                changed = True
    return side


def implied_prices(core: Core, side: list[str], prices: dict[str, Price], eth_usd: float,
                   decimals: dict[str, int | None]) -> dict[str, Price]:
    """A price for an asset nobody quotes, from what it was exchanged for in this transaction: a party outside the
    sender's side that took the asset in and gave out at least IMPLIED_MIN_USD of priced assets (or the reverse) sets
    its value. Passes repeat, because one implied price can price the next exchange."""
    ledger = net_ledger(core.movements)
    implied: dict[str, Price] = {}
    for _ in range(IMPLIED_PASSES):
        known = prices | implied
        added = False
        for asset in {a for p in ledger for a in ledger[p] if a != ETH and a not in known and a not in core.nft_collections}:
            best: tuple[float, int] | None = None
            for party, changes in ledger.items():
                n = changes.get(asset, 0)
                if not n or party in side or party == asset or party == core.builder:
                    continue
                opposite = sum(usd_value(b, abs(m), known, eth_usd) or 0.0 for b, m in changes.items()
                               if b != asset and (m < 0) == (n > 0))
                if opposite >= IMPLIED_MIN_USD and (best is None or opposite > best[0]):
                    best = (opposite, abs(n))
            if best:
                scale = decimals.get(asset)
                scale = 18 if scale is None else scale
                implied[asset] = {"usd": best[0] / (best[1] / 10**scale), "symbol": None, "decimals": scale, "implied": True,
                                  "max_amount": best[1] * IMPLIED_REACH}
                added = True
        if not added:
            break
    return implied


def shown_parties(ledger: dict[str, dict[str, int]], core: Core, prices: dict[str, Price], eth_usd: float) -> list[str]:
    """The ledger rows a record shows: the sender's side and the entry contract, then the largest flows."""
    side, flow = created_side(core), flows(ledger, prices, eth_usd)
    ranked = sorted(ledger, key=lambda p: (-max(flow[p]), p))
    first = [p for p in ranked if p in side or p == core.root.target]
    return (first + [p for p in ranked if p not in first])[:LEDGER_PARTIES]


def controlled_by_sender(core: Core, labels: dict[str, Label], entry_is_public: bool) -> set[str]:
    """The sender's side, plus the entry contract when it has no label and few wallets use it: the sender chose to
    run it, whoever deployed it (a bot's operator often deploys from another wallet). An unlabeled contract that
    many wallets call is someone's protocol or router: what it loses is a loss, and its own callbacks are not the
    sender re-entering anything. A multisig wallet executing a signed transaction is its owners' wallet, so what it
    loses is a loss too, whoever submitted the transaction."""
    controlled = set(created_side(core))
    multisig = any(emitter == core.root.target and name in MULTISIG_EVENTS for emitter, name in core.events)
    if core.root.target and core.root.target not in labels and not entry_is_public and not multisig:
        controlled.add(core.root.target)
    return controlled


def flash_loans_taken(core: Core, labels: dict[str, Label], entry_is_public: bool) -> list[dict]:
    """The detected flash loans, without shape matches whose lender is the sender's own contract. A contract that
    deposits into a protocol and withdraws at least as much in the same call has the loan's shape, with the roles
    reversed: nobody lent the sender anything. An attack that loops deposit and withdraw showed 52 of these."""
    controlled = controlled_by_sender(core, labels, entry_is_public)
    return [loan for loan in core.flash_loans if loan["source"] == "event" or loan["lender"] not in controlled]


def reentries_shown(core: Core, labels: dict[str, Label], entry_is_public: bool) -> list[tuple[str, str, bool]]:
    """(contract, the sender-controlled contract it was re-entered through, read-only) for the reentrancy fact: a
    protocol contract twice on the call stack with a sender-controlled frame between, outside a flash loan callback.
    A read-only re-entry counts only when some other contract does the reading: a bot that reads a pool's price
    inside that pool's own callback is ordinary, a protocol that reads it there can be fooled."""
    controlled = controlled_by_sender(core, labels, entry_is_public)
    lenders = {loan["lender"] for loan in flash_loans_taken(core, labels, entry_is_public)}
    shown: dict[tuple[str, bool], tuple[str, str, bool]] = {}
    for r in core.reentries:
        through = [a for a in r["between"] if a in controlled]
        if through and r["contract"] not in controlled and r["contract"] not in lenders \
                and not (r["static"] and r["caller"] in controlled):
            shown.setdefault((r["contract"], r["static"]), (r["contract"], through[0], r["static"]))
    return list(shown.values())


def cast(core: Core, prices: dict[str, Price], eth_usd: float, labels: dict[str, Label],
         entry_is_public: bool) -> Cast:
    ledger, logs_only = net_ledger(core.movements), net_ledger(core.log_movements)
    shown = shown_parties(ledger, core, prices, eth_usd)
    logs_shown = shown_parties(logs_only, core, prices, eth_usd)
    side, flow = created_side(core), flows(ledger, prices, eth_usd)
    effective = [f for f in frames_of(core.root) if not f.failed and f.target and not is_precompile(f.target)]
    gainers = [p for p in sorted(ledger, key=lambda p: (flow[p][0] - flow[p][1], p))
               if p not in side and p != core.builder and flow[p][1] > flow[p][0]][:NEW_WALLET_CHECKS]
    controlled = controlled_by_sender(core, labels, entry_is_public)  # what the sender's own contracts spend is no one's loss
    losses = sorted(((usd_value(a, -n, prices, eth_usd) or 0.0, p, a) for p in ledger if p not in controlled
                     for a, n in ledger[p].items() if n < 0 and a != p), reverse=True)  # nor is issuing one's own token
    drains = [(p, a) for usd, p, a in losses[:DRAIN_CANDIDATES] if usd >= DRAIN_MIN_USD]
    largest_loss = losses[0][0] if losses else 0.0
    side_net = sum(flow[p][1] - flow[p][0] for p in side if p in flow)
    proceeds_checks = [p for p in gainers if largest_loss >= DRAIN_MIN_USD and side_net < SIDE_KEEPS_SHARE * largest_loss
                       and flow[p][1] - flow[p][0] >= PROCEEDS_SHARE * largest_loss][:1]
    entry_delegations = [target for context, target, _ in core.delegations if context == core.root.target]
    parties = [side[0]]  # the sender, even when it is the block's builder paying its proposer
    for address in ([core.root.target, *shown, *logs_shown, *gainers, *(p for p, _ in drains), *entry_delegations]
                    + [loan["lender"] for loan in flash_loans_taken(core, labels, entry_is_public)]
                    + [a for contract, through, _ in reentries_shown(core, labels, entry_is_public) for a in (contract, through)]
                    + [a for p in core.privileged for a in (p["emitter"], p["subject"])]
                    + [contract for _, contract in core.created] + [target for target, _, _ in core.repeated]
                    + sorted({f.context for f in effective if f.context in labels})):
        if address and address not in parties and address not in (ZERO, core.builder):
            parties.append(address)
    assets = sorted(({a for p in shown for a in ledger[p]} | {a for p in logs_shown for a in logs_only[p]}
                     | {loan["asset"] for loan in flash_loans_taken(core, labels, entry_is_public)} | {a for _, a in drains}
                     | {m.asset for m in core.movements if m.sender == ZERO and m.recipient in [*shown, *side]})
                    - {ETH})
    selectors = sorted({f.selector for f in effective if f.selector and f.target in labels})
    return Cast(parties, assets, drains, gainers, selectors, proceeds_checks)

"""The transaction alone: asset movements, the call tree, and the events, flash loans and re-entries they show."""

from collections import Counter
from dataclasses import dataclass, field

from jevscan_chainmonitor.facts.constants import (
    APPROVAL,
    CREATE_KINDS,
    ETH,
    EVENT_NAME,
    FLASH_LOAN_EVENTS,
    INHERITS_CONTEXT,
    INTERNAL_BALANCE_CHANGED,
    NFT_BATCH_TOPICS,
    NOISE_TOPICS,
    PRECOMPILE_LIMIT,
    PRIVILEGED_EVENTS,
    REENTRANT_BY_DESIGN,
    REENTRY_CAP,
    REPEAT_MIN,
    REPEATS_SHOWN,
    SWAP_TOPICS,
    TOPIC,
    TRANSFER,
    TRANSFER_FROM,
    UNISWAP_V3_FLASH,
    VALUE_KINDS,
    WETH,
    WETH_DEPOSIT,
    WETH_WITHDRAWAL,
)


@dataclass
class Movement:
    asset: str  # token address, or ETH
    sender: str
    recipient: str
    amount: int


@dataclass
class Frame:
    kind: str
    caller: str
    target: str | None  # None only for a failed CREATE, which has no address
    context: str  # whose storage and balance the code runs against: the parent's for DELEGATECALL
    selector: str | None
    value: int
    depth: int
    failed: bool  # this frame or an ancestor reverted, so nothing in it happened
    static: bool
    start: int = 0  # movements[start:end] happened inside this frame
    end: int = 0
    children: list["Frame"] = field(default_factory=list)


@dataclass
class Core:
    tx: dict
    block_tx_count: int
    block_timestamp: int
    builder: str
    succeeded: bool
    root: Frame
    movements: list[Movement]  # ETH and token transfers that took effect, in execution order
    log_movements: list[Movement]  # what the receipt alone shows: token transfers plus the envelope's value
    nft_transfers: int
    events: list[tuple[str, str]]  # (emitter, event name) for known events other than transfers and approvals
    other_events: int
    swap_emitters: set[str]
    flash_loans: list[dict]  # {lender, asset, amount, source}
    reentries: list[dict]  # {contract, between, static, caller}
    privileged: list[dict]  # {emitter, event, subject}
    approvals: set[tuple[str, str, str, int]]  # observed Approval event values; not final or ordered authorization
    positions: list[tuple[str, str, str, int | None, int | None]]  # (issuer, from, to, id, raw amount) per ERC-1155 transfer
    internal_balances: list[tuple[str, str, str, int]]  # (vault, user, token, signed delta) from accounting events
    delegations: list[tuple[str, str, str | None]]  # (context, code target, selector) for every DELEGATECALL that ran
    nft_collections: set[str]  # ERC-721 contracts whose tokens moved
    created: list[tuple[str, str]]  # (creator, new contract)
    destroyed: list[str]
    calls: int
    max_depth: int
    reverted_inner_calls: int
    repeated: list[tuple[str, str | None, int]]  # (target, selector, count)
    gas_used: int
    log_count: int
    fee_wei: int
    builder_payment_wei: int
    trivial: bool


def word(data: str, i: int) -> int:
    return int(data[2 + 64 * i: 66 + 64 * i] or "0", 16)


def signed_word(data: str, i: int) -> int:
    value = word(data, i)
    return value - 2**256 if value >= 2**255 else value


def topic_address(topic: str) -> str:
    return "0x" + topic[-40:]


def located(log: dict, where: tuple[str, int]) -> int:
    kind, i = where
    return int(log["topics"][i], 16) if kind == "topic" else word(log["data"], i)


def located_if_present(log: dict, where: tuple[str, int]) -> int | None:
    """Read an ABI-mapped field only when this log actually contains it.

    Contracts can emit a familiar topic from assembly while using a different field layout.  It is still useful to
    retain the event name, but an absent indexed field must not make fact extraction fail or be guessed from data.
    """
    kind, i = where
    if kind == "topic":
        return int(log["topics"][i], 16) if len(log["topics"]) > i else None
    return word(log["data"], i) if len(log["data"]) >= 2 + 64 * (i + 1) else None


def as_address(value: int) -> str:
    return "0x" + format(value, "040x")


def is_precompile(address: str) -> bool:
    return int(address, 16) < PRECOMPILE_LIMIT


def log_movement(log: dict) -> Movement | None:
    """The fungible transfer a log records, if any. An ERC-721 Transfer has four topics and its last one is a token
    id, not an amount. WETH emits Deposit and Withdrawal, never Transfer, when it wraps and unwraps: model them as
    transfers from and to the WETH contract, so the wrapper nets to zero and every holder's balance comes out right."""
    topics, address = log["topics"], log["address"].lower()
    if not topics:
        return None
    if topics[0] == TRANSFER and len(topics) == 3 and len(log["data"]) == 66:
        return Movement(address, topic_address(topics[1]), topic_address(topics[2]), word(log["data"], 0))
    if topics[0] == TRANSFER and len(topics) == 4:  # ERC-721: one token, counted as one unit of the collection
        return Movement(address, topic_address(topics[1]), topic_address(topics[2]), 1)
    if address == WETH and len(topics) == 2 and len(log["data"]) == 66:
        if topics[0] == WETH_DEPOSIT:
            return Movement(WETH, WETH, topic_address(topics[1]), word(log["data"], 0))
        if topics[0] == WETH_WITHDRAWAL:
            return Movement(WETH, topic_address(topics[1]), WETH, word(log["data"], 0))
    return None


def extract(block: dict, tx: dict, receipt: dict, trace: dict) -> Core:
    """Everything the transaction's own data says. `trace` is the callTracer frame (withLog) for this transaction.
    Receipt logs are canonical; the trace supplies call structure, ETH movement, and ordering, and its surviving logs
    must equal the receipt's, or the trace handling is wrong."""
    for name in ("from", "hash", "input", "value", "nonce", "transactionIndex"):
        if name not in tx:
            raise ValueError(f"transaction is missing required field {name!r}")
    succeeded = receipt["status"] == "0x1"
    builder = block["miner"].lower()
    movements: list[Movement] = []
    surviving_logs: list[dict] = []
    stats = {"calls": 0, "max_depth": 0, "reverted": 0}
    created: list[tuple[str, str]] = []
    destroyed: list[str] = []
    call_counts: Counter = Counter()
    delegations: list[tuple[str, str, str | None]] = []

    def walk(node: dict, depth: int, parent: Frame | None) -> Frame:
        kind = node["type"]
        target = node["to"].lower() if node.get("to") else None
        caller = node["from"].lower()
        context = parent.context if parent and kind in INHERITS_CONTEXT else (target or caller)
        failed = bool(parent and parent.failed) or "error" in node
        if "error" in node and parent and not parent.failed:
            stats["reverted"] += 1
        data = node.get("input", "0x")
        frame = Frame(kind, caller, target, context, data[:10] if len(data) >= 10 else None,
                      int(node.get("value", "0x0"), 16), depth, failed,
                      bool(parent and parent.static) or kind == "STATICCALL", start=len(movements))
        stats["calls"] += 1
        stats["max_depth"] = max(stats["max_depth"], depth)
        if not failed and target:
            if kind in INHERITS_CONTEXT and parent is not None:
                delegations.append((context, target, frame.selector))
            if frame.value and kind in VALUE_KINDS:
                movements.append(Movement(ETH, caller, target, frame.value))
            if kind in CREATE_KINDS:
                created.append((caller, target))
            elif kind == "SELFDESTRUCT":
                destroyed.append(caller)
            elif kind == "CALL" and not is_precompile(target):
                call_counts[(target, frame.selector)] += 1
        logs = sorted(node.get("logs", ()), key=lambda entry: int(entry["position"], 16))
        emitted = 0
        for i, child in enumerate([*node.get("calls", ()), None]):
            # A log's position is the number of subcalls made before it.
            while emitted < len(logs) and (child is None or int(logs[emitted]["position"], 16) <= i):
                if not failed:
                    surviving_logs.append(logs[emitted])
                    moved = log_movement(logs[emitted])
                    if moved:
                        movements.append(moved)
                emitted += 1
            if child is not None:
                frame.children.append(walk(child, depth + 1, frame))
        frame.end = len(movements)
        return frame

    root = walk(trace, 0, None)
    if root.failed == succeeded:
        raise ValueError(f"{tx['hash']}: receipt status and trace disagree about success")
    seen = [(entry["address"].lower(), entry["topics"], entry["data"]) for entry in surviving_logs]
    canonical = [(entry["address"].lower(), entry["topics"], entry["data"]) for entry in receipt["logs"]]
    if seen != canonical:
        raise ValueError(f"{tx['hash']}: the trace's surviving logs differ from the receipt's "
                         f"({len(seen)} against {len(canonical)})")

    log_movements = [m for m in map(log_movement, receipt["logs"]) if m]
    value = int(tx["value"], 16)
    if succeeded and value and root.target:
        log_movements.insert(0, Movement(ETH, root.caller, root.target, value))
    nft_transfers, events, other_events, swap_emitters, privileged, approvals = 0, [], 0, set(), [], set()
    positions: list[tuple[str, str, str, int | None, int | None]] = []
    internal_balances: list[tuple[str, str, str, int]] = []
    nft_collections: set[str] = set()
    for entry in receipt["logs"]:
        topics, emitter = entry["topics"], entry["address"].lower()
        topic0 = topics[0] if topics else None
        if topic0 == TRANSFER and len(topics) == 4:
            nft_collections.add(emitter)
        if (topic0 in NFT_BATCH_TOPICS and len(topics) == 4
                and (topic0 != TOPIC["TransferSingle(address,address,address,uint256,uint256)"] or len(entry["data"]) >= 130)):
            token_id, amount = (word(entry["data"], 0), word(entry["data"], 1)) if topic0 == TOPIC["TransferSingle(address,address,address,uint256,uint256)"] else (None, None)
            positions.append((emitter, topic_address(topics[2]), topic_address(topics[3]), token_id, amount))
        if topic0 == APPROVAL and len(topics) == 3 and len(entry["data"]) == 66:  # a fourth topic is an NFT approval
            approvals.add((emitter, topic_address(topics[1]), topic_address(topics[2]), word(entry["data"], 0)))
        if topic0 == INTERNAL_BALANCE_CHANGED and len(topics) == 3 and len(entry["data"]) == 66:
            internal_balances.append((emitter, topic_address(topics[1]), topic_address(topics[2]), signed_word(entry["data"], 0)))
        if (topic0 == TRANSFER and len(topics) == 4) or topic0 in NFT_BATCH_TOPICS:
            nft_transfers += 1
        if topic0 in SWAP_TOPICS:
            swap_emitters.add(emitter)
        if topic0 in PRIVILEGED_EVENTS:
            where = PRIVILEGED_EVENTS[topic0]
            value = located_if_present(entry, where) if where else None
            subject = as_address(value & (2**160 - 1)) if value is not None else None
            privileged.append({"emitter": emitter, "event": EVENT_NAME[topic0], "subject": subject})
        if topic0 in EVENT_NAME and topic0 not in NOISE_TOPICS:
            events.append((emitter, EVENT_NAME[topic0]))
        elif topic0 not in NOISE_TOPICS:
            other_events += 1

    gas_used = int(receipt["gasUsed"], 16)
    gas_price = int(receipt["effectiveGasPrice"], 16)
    base_fee = int(block.get("baseFeePerGas", "0x0"), 16)
    direct_tip = sum(m.amount for m in movements if m.asset == ETH and m.recipient == builder)
    token_transfer_logs = sum(1 for entry in receipt["logs"] if entry["topics"] and entry["topics"][0] == TRANSFER)
    one_context = all(f.context == root.context for f in frames_of(root))
    # A proxy runs one implementation. A wallet contract that delegates into a second target is running code the
    # transaction chose, which is never trivial, whatever else happened.
    code_targets = {target for context, target, _ in delegations if context == root.context}
    repeated = [(target, selector, n) for (target, selector), n in call_counts.most_common() if n >= REPEAT_MIN]
    return Core(
        tx=tx, block_tx_count=len(block["transactions"]), block_timestamp=int(block["timestamp"], 16),
        builder=builder, succeeded=succeeded, root=root, movements=movements, log_movements=log_movements,
        nft_transfers=nft_transfers, events=events, other_events=other_events, swap_emitters=swap_emitters,
        flash_loans=find_flash_loans(root, movements, receipt["logs"]), reentries=find_reentries(root),
        privileged=privileged, approvals=approvals, positions=positions, internal_balances=internal_balances, delegations=delegations,
        nft_collections=nft_collections, created=created, destroyed=destroyed, calls=stats["calls"],
        max_depth=stats["max_depth"], reverted_inner_calls=stats["reverted"], repeated=repeated[:REPEATS_SHOWN],
        gas_used=gas_used, log_count=len(receipt["logs"]), fee_wei=gas_used * gas_price, builder_payment_wei=gas_used * max(0, gas_price - base_fee) + direct_tip,
        trivial=one_context and not created and token_transfer_logs <= 1 and len(code_targets) <= 1,
    )


def frames_of(frame: Frame):
    yield frame
    for child in frame.children:
        yield from frames_of(child)


def frame_holding(root: Frame, index: int, context: str) -> Frame | None:
    """The shallowest call into `context` in which movement `index` happened: the call that made a token move."""
    found = None
    for f in frames_of(root):
        if (f.context == context and f.kind not in INHERITS_CONTEXT and f.start <= index < f.end
                and (found is None or f.depth < found.depth)):
            found = f
    return found


def pulls_of(core: Core, side: list[str]) -> list[dict]:
    """Token transfers made with transferFrom on someone else's balance. The spender is the address that called the
    token. A transfer of the caller's own tokens, or of the sender's side's, is not a pull."""
    pulls = []
    for f in frames_of(core.root):
        if f.failed or f.selector != TRANSFER_FROM or f.kind in INHERITS_CONTEXT or not f.target:
            continue
        for m in core.movements[f.start:f.end]:
            if m.asset == f.context and m.sender not in side and m.sender != f.caller:
                pulls.append({"spender": f.caller, "owner": m.sender, "recipient": m.recipient, "asset": m.asset,
                              "amount": m.amount, "approved_now": any((m.asset, m.sender, f.caller) == approval[:3]
                                                                      for approval in core.approvals)})
    return pulls


def find_flash_loans(root: Frame, movements: list[Movement], logs: list[dict]) -> list[dict]:
    """Flash loans from lenders' own events, and from the shape every flash loan has whatever the lender: inside one
    frame, funds go to a contract, the frame calls that contract back, and at least as much of the same asset returns
    from it to where the funds came from before the frame ends. An arbitrage cycle does not match: its funds come back
    from the last pool, not from the contract that was called."""
    found: dict[tuple[str, int], dict] = {}
    for entry in logs:
        topic0 = entry["topics"][0] if entry["topics"] else None
        lender = entry["address"].lower()
        if topic0 == UNISWAP_V3_FLASH:
            if len(entry["data"]) < 2 + 64 * 2:
                continue
            amounts, named = {word(entry["data"], 0), word(entry["data"], 1)} - {0}, None  # the event names no token
        elif topic0 in FLASH_LOAN_EVENTS:
            asset_at, amount_at = FLASH_LOAN_EVENTS[topic0]
            if len(entry["topics"]) == 2:  # Maker's DssFlash shares Balancer's signature but indexes only the receiver
                asset_at, amount_at = ("data", 0), ("data", 1)
            amount, asset = located_if_present(entry, amount_at), located_if_present(entry, asset_at)
            if amount is None or asset is None:
                continue
            amounts, named = {amount}, as_address(asset & (2**160 - 1))
        else:
            continue
        # Lenders reuse each other's event signatures with other fields (Curve's crvUSD lender puts the receiver where
        # Morpho puts the token), so an event counts only with a matching transfer, and that transfer names the asset.
        for amount in amounts:
            moved = [m.asset for m in movements if m.amount == amount and m.asset != ETH
                     and (m.asset == named or m.sender == lender)]
            if moved:
                asset = named if named in moved else moved[0]
                found.setdefault((asset, amount), {"lender": lender, "asset": asset, "amount": amount, "source": "event"})
    for frame in frames_of(root):
        if frame.failed:
            continue
        for callback in frame.children:
            if callback.kind != "CALL" or callback.failed or not callback.children or not callback.target:
                continue
            borrower = callback.target
            for lent in movements[frame.start:callback.start]:
                if lent.recipient != borrower or lent.asset == ETH or not lent.amount:
                    continue
                repaid = any(m.asset == lent.asset and m.sender == borrower and m.recipient == lent.sender
                             and m.amount >= lent.amount for m in movements[callback.start:frame.end])
                if repaid:
                    found.setdefault((lent.asset, lent.amount), {"lender": frame.context, "asset": lent.asset,
                                                                 "amount": lent.amount, "source": "shape"})
    return list(found.values())


def find_reentries(root: Frame) -> list[dict]:
    """Every time a contract is entered while an earlier call into it is still running, with the contracts in between.
    Whether one of those is the sender's, and whether the outer call is a flash loan, is decided in `finish`."""
    found: dict[tuple, dict] = {}

    def visit(frame: Frame, stack: list[tuple[str, str | None]]) -> None:
        if frame.failed or len(found) >= REENTRY_CAP:
            return
        contexts = [context for context, _ in stack]
        if frame.context in contexts:
            outer = contexts.index(frame.context)
            between = sorted(set(contexts[outer + 1:]) - {frame.context})
            if between and stack[outer][1] not in REENTRANT_BY_DESIGN:
                found.setdefault((frame.context, tuple(between), frame.static, frame.caller),
                                 {"contract": frame.context, "between": between, "static": frame.static,
                                  "caller": frame.caller})
        stack.append((frame.context, frame.selector))
        for child in frame.children:
            visit(child, stack)
        stack.pop()

    visit(root, [])
    return list(found.values())

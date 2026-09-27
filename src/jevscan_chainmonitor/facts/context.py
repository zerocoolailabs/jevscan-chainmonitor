"""What the lookups return for a window of transactions, and what a record will ask them for."""

from dataclasses import dataclass, field
from typing import TypedDict


class Label(TypedDict):
    name: str
    category: str  # exchange, lending, bridge, mixer, token, centralized exchange
    symbol: str | None  # tokens only


class Price(TypedDict):
    usd: float
    symbol: str
    decimals: int


class Creation(TypedDict):
    creator: str
    block: int
    timestamp: int


class Funding(TypedDict):
    timestamp: int  # of the first inbound transfer
    funder: str


@dataclass
class Context:
    """Lookup results for a window. An absent key was not looked up (a trivial transaction skips the Etherscan reads),
    and the record then says nothing about it; a None value means the lookup found nothing. Reads that depend on
    the block are keyed with the transaction's block."""
    labels: dict[str, Label]
    eth_usd: float
    prices: dict[str, Price] = field(default_factory=dict)  # only confident prices from before the window
    kinds: dict[tuple[str, int], str] = field(default_factory=dict)  # wallet, contract, delegated wallet
    creations: dict[str, Creation | None] = field(default_factory=dict)
    verified: dict[str, bool] = field(default_factory=dict)
    decimals: dict[str, int | None] = field(default_factory=dict)
    # (holder, asset, block, transaction index) -> the balance just before that transaction
    balances_before: dict[tuple[str, str, int, int], int | None] = field(default_factory=dict)
    nonces_before: dict[tuple[str, int], int] = field(default_factory=dict)
    funding: dict[str, Funding | None] = field(default_factory=dict)  # looked up only for wallets with few transactions
    # (sender, block, transaction index) -> (block, pool) of the sender's latest mixer payout inside the look-back
    mixer_payouts: dict[tuple[str, int, int], tuple[int, str] | None] = field(default_factory=dict)
    # (holder, asset, block, transaction index) -> (amount, index of the first such transaction): what earlier
    # transactions of the same block, sent by this transaction's sender, moved into the holder
    same_sender_deposits: dict[tuple[str, str, int, int], tuple[int, int]] = field(default_factory=dict)
    nfts: dict[str, dict] = field(default_factory=dict)  # collection -> {name, verified, floor_usd or None}
    # Filled by finish() as it walks the window in chain order: what each sender did earlier that looked like
    # preparation, and which contracts had their logic or control changed, so later transactions can say so.
    actor_notes: dict[str, list[dict]] = field(default_factory=dict)
    contract_watch: dict[str, dict] = field(default_factory=dict)
    prior_day_calls: dict[tuple[str, int], int] = field(default_factory=dict)
    prior_day_senders: dict[tuple[str, int], int] = field(default_factory=dict)  # distinct wallets behind those calls
    function_names: dict[str, str] = field(default_factory=dict)


@dataclass
class Cast:
    """What a finished record mentions, so enrichment fetches exactly what `finish` will read."""
    parties: list[str]  # addresses needing code kind, creation, and label checks, most important first
    assets: list[str]  # token addresses the record names
    drains: list[tuple[str, str]]  # (holder, asset) balance reads one block earlier
    new_wallet_checks: list[str]  # gainers whose prior transaction count is worth a read
    tree_selectors: list[str]  # selectors of calls into labeled contracts, the only calls whose functions are named
    proceeds_checks: list[str]  # wallets that took the bulk of a loss while the sender's side kept little: read their funding

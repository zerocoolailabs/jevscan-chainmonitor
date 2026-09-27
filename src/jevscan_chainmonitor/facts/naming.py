"""Aliases for the parties and assets a record mentions, so external names reach the classifier only when trusted."""

from collections import Counter

from jevscan_chainmonitor.facts.constants import ESTABLISHED_SECONDS, ETH, WALLET_KINDS
from jevscan_chainmonitor.facts.context import Context, Label
from jevscan_chainmonitor.facts.ledger import contract_age, usd_value
from jevscan_chainmonitor.facts.trace import Core


class Naming:
    """Aliases for one transaction. Filtered external names are still untrusted: an address shows its label,
    and a token its symbol, only when the label passed the filters in labels.py and the contract is older than
    30 days. Everything else is numbered."""

    def __init__(self, core: Core, ctx: Context, side: list[str]) -> None:
        self.core, self.ctx, self.side = core, ctx, side
        self.block = int(core.tx["blockNumber"], 16)
        self.born_here = {contract: creator for creator, contract in core.created}
        self.parties: dict[str, dict] = {}
        self.assets: dict[str, dict] = {}
        self.alias_of: dict[str, str] = {}
        self.asset_alias_of: dict[str, str] = {ETH: ETH}
        self.counts: Counter = Counter()

    def age(self, address: str) -> int | None:
        """Seconds since the contract was created, as of this transaction; None when unknown or not yet created."""
        return contract_age(self.core, self.ctx.creations, self.block, address)

    def label(self, address: str) -> Label | None:
        """The label, if the 30-day rule lets it show. A labeled wallet, such as an exchange hot wallet, has no
        deployment to date, so its label stands."""
        label = self.ctx.labels.get(address)
        if label is None:
            return None
        if self.ctx.kinds.get((address, self.block)) in WALLET_KINDS:
            return None if label["category"] == "token" else label
        age = self.age(address)
        return label if age is not None and age > ESTABLISHED_SECONDS else None

    def numbered(self, stem: str) -> str:
        self.counts[stem] += 1
        return f"{stem}_{self.counts[stem]}"

    def party(self, address: str, assume: str | None = None) -> str:
        """The alias for `address`, recording what is known about it. `assume` is the kind to use for an address whose
        code was not looked up (a minor party of the call tree)."""
        if address in self.alias_of:
            return self.alias_of[address]
        core, ctx = self.core, self.ctx
        kind = "contract" if address in self.born_here else ctx.kinds.get((address, self.block), assume)
        label = self.label(address)
        info: dict = {"address": address, "kind": kind, "label": None, "category": None,
                      "age_seconds": self.age(address), "created_in_tx": address in self.born_here,
                      "created_by": None, "exchange_pool": address in core.swap_emitters}
        if address == self.side[0]:
            alias = "sender"
        elif address == core.builder:
            alias, info["kind"] = "block_builder", "block builder"
        elif address in self.side:
            alias = self.numbered("sender_contract")
        elif label:
            alias, info["label"], info["category"] = label["name"], label["name"], label["category"]
            if alias in {"sender", "block_builder"}:
                alias = "labelled_" + alias
        else:
            alias = self.numbered({"wallet": "unknown_wallet", "delegated wallet": "unknown_wallet",
                                   "contract": "unknown_contract"}.get(kind, "unknown_address"))
        stem, suffix = alias, 2
        while alias in self.parties:
            alias = f"{stem}__{suffix}"
            suffix += 1
        self.alias_of[address] = alias
        creator = self.born_here.get(address) or (ctx.creations.get(address) or {}).get("creator")
        if creator and info["age_seconds"] is not None:
            info["created_by"] = ("sender" if creator == self.side[0] else
                                  "sender's contract" if creator in self.side else "someone else")
        if (address, self.block) in ctx.nonces_before:
            info["prior_transactions"] = ctx.nonces_before[(address, self.block)]
        if address in ctx.verified:
            info["source_verified"] = ctx.verified[address]
        elif address in self.born_here:
            info["source_verified"] = False  # nothing can be verified on an explorer before it exists
        self.parties[alias] = info
        return alias

    def asset(self, address: str) -> str:
        if address in self.asset_alias_of:
            return self.asset_alias_of[address]
        label, price, age = self.label(address), self.ctx.prices.get(address), self.age(address)
        symbol = label["symbol"] if label else None
        nft = self.ctx.nfts.get(address)
        # Marketplace verification does not make arbitrary collection text safe
        # as a model instruction. Keep only independently filtered label symbols.
        stem = "unrecognized_nft" if address in self.core.nft_collections else "unrecognized_token"
        alias = symbol if symbol and symbol not in self.asset_alias_of.values() else self.numbered(stem)
        creator = self.born_here.get(address) or (self.ctx.creations.get(address) or {}).get("creator")
        self.assets[alias] = {"address": address, "symbol": symbol, "priced": price is not None, "age_seconds": age,
                              "created_by_sender_side": bool(creator and creator in self.side),
                              "price_basis": ("implied from what it was exchanged for in this transaction" if price and price.get("implied")
                                              else "current floor price" if nft and price else None),
                              "nft": address in self.core.nft_collections}
        self.asset_alias_of[address] = alias
        return alias


def decimals_of(asset: str, ctx: Context) -> int | None:
    if asset == ETH:
        return 18
    if asset in ctx.prices:
        return ctx.prices[asset]["decimals"]
    return ctx.decimals.get(asset)


def amount_facts(asset: str, amount: int, names: Naming, ctx: Context) -> dict:
    usd, decimals = usd_value(asset, amount, ctx.prices, ctx.eth_usd), decimals_of(asset, ctx)
    return {"asset": names.asset(asset), "amount_raw": str(amount),
            "amount": None if decimals is None else amount / 10**decimals,
            "usd": None if usd is None else round(usd, 2)}


def by_value(amounts: list[dict]) -> list[dict]:
    """Amount facts, largest priced value first; unpriced amounts last, by asset name."""
    return sorted(amounts, key=lambda a: (-(a["usd"] or 0.0), a["asset"]))

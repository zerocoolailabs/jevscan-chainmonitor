"""The fact sheet the classifier reads: a pure function of TxFacts.

The classifier reads hex, raw numbers, and comparisons poorly, so the sheet speaks in aliases and in words with a size
bucket ("about $8.9 million (very large)"), and code makes every comparison ("received about as much as it gave"). It
never carries a transaction hash, block number, date, or address. The detector configuration calls this view "R2".
"""

from jevscan_chainmonitor.facts import HIGH_VOLUME_TXS, WALLET_KINDS, TxFacts

BUCKETS = ((100, "negligible"), (10_000, "small"), (100_000, "moderate"), (1_000_000, "large"),
           (10_000_000, "very large"))
EVEN_BAND = 0.1  # a party that got back within 10% of what it gave is "about even"
SMALL_SHARE = 0.01
ORDINALS = {1: "st", 2: "nd", 3: "rd"}


def bucket(usd: float) -> str:
    return next((name for limit, name in BUCKETS if usd < limit), "enormous")


def money(usd: float) -> str:
    """'about $8.9 million (very large)': a rounded figure in words plus its size bucket."""
    usd = abs(usd)
    if usd < 1:
        words = "under $1"
    elif usd < 10_000:
        words = f"about ${float(f'{usd:.2g}'):,.0f}"
    elif usd < 1_000_000:
        words = f"about ${usd / 1e3:.0f} thousand"
    elif usd < 1_000_000_000:
        words = f"about ${usd / 1e6:.3g} million"
    else:
        words = f"about ${usd / 1e9:.3g} billion"
    return f"{words} ({bucket(usd)})"


def quantity(amount: float | None) -> str:
    if amount is None:
        return "an unknown amount"
    if amount < 0.001:
        return "a dust amount (under 0.001 units)"
    for size, name in ((1e12, "trillion"), (1e9, "billion"), (1e6, "million")):
        if amount >= size:
            return f"about {min(amount / size, 999):.3g} {name} units" if amount < 1e15 else "over a quadrillion units"
    if amount >= 1_000:
        return f"about {amount / 1e3:.3g} thousand units"
    return f"about {amount:.3g} units"


def span(seconds: int) -> str:
    for size, unit in ((365 * 86400, "year"), (30 * 86400, "month"), (86400, "day"), (3600, "hour"), (60, "minute")):
        if seconds >= size:
            n = seconds // size
            return f"{n} {unit}{'s' if n != 1 else ''}"
    return "under a minute"


def ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else ORDINALS.get(n % 10, 'th')}"


def asset_name(alias: str, facts: TxFacts) -> str:
    info = facts["assets"].get(alias)
    if info is None or info["symbol"]:
        return alias + (" NFTs" if info and info.get("nft") else "")
    origin = " created by the sender's side" if info["created_by_sender_side"] else ""
    kind = "an unrecognized NFT collection" if info.get("nft") else "an unrecognized token"
    if info["age_seconds"] is None:
        return f"{alias} ({kind}{origin})"
    when = "in this transaction" if info["age_seconds"] == 0 else f"{span(info['age_seconds'])} earlier"
    return f"{alias} ({kind} created {when}{origin})"


def value_of(item: dict, facts: TxFacts) -> str:
    """'about $4,000 (small) of USDC', or a unit count when the asset has no trustworthy price. An implied price and a
    floor price are said to be what they are."""
    info = facts["assets"].get(item["asset"]) or {}
    name = asset_name(item["asset"], facts)
    if info.get("nft"):
        count = int(item["amount"]) if item["amount"] is not None else None
        units = f"{count} {name}" if count is not None else f"some {name}"
        if item["usd"] is None:
            return f"{units} (no floor price)"
        return f"{units} ({money(item['usd'])}, {info.get('price_basis') or 'priced'})"
    if item["usd"] is None:
        return f"{quantity(item['amount'])} of {name} (no reliable price)"
    basis = f" ({info['price_basis']})" if info.get("price_basis") else ""
    return f"{money(item['usd'])} of {name}{basis}"


def describe(alias: str, facts: TxFacts) -> str:
    """An alias with what is known about the address behind it."""
    info = facts["parties"][alias]
    if alias == "sender":
        return "sender"
    if info["kind"] == "block builder":
        return "block_builder (the builder of this block)"
    traits = []
    if info["category"]:
        traits.append(info["category"])
    elif info["exchange_pool"]:
        traits.append("exchange pool")
    elif info["kind"]:
        traits.append(info["kind"])
    if info["created_in_tx"]:
        by = "another party" if info["created_by"] == "someone else" else f"the {info['created_by']}"
        traits.append(f"created in this transaction by {by}")
    elif info["age_seconds"] is not None:
        by = {"sender": " by the sender", "sender's contract": " by the sender's contract"}.get(info["created_by"], "")
        traits.append(f"created {span(info['age_seconds'])} earlier{by}")
    if info.get("source_verified") is False:
        traits.append("source code unverified")
    if info.get("prior_transactions") is not None:
        n = info["prior_transactions"]
        traits.append("no prior transactions" if n == 0 else f"{n:,} prior transactions")
    return f"{alias} ({', '.join(traits)})" if traits else alias


def exchange_words(row: dict) -> str:
    """Code compares what a party gave with what it received, because Jev should not do arithmetic."""
    gave, received = row["gave_usd"], row["received_usd"]
    unpriced = any(c["usd"] is None for c in row.get("changes", ()))
    if unpriced:
        if not gave and not received:
            priced = "no priced asset movement is recorded"
        elif not gave:
            priced = "priced assets show an inflow"
        elif not received:
            priced = "priced assets show an outflow"
        else:
            ratio = received / gave
            priced = ("priced assets are approximately balanced" if abs(ratio - 1) <= EVEN_BAND else
                      "priced assets show more received than given" if ratio > 1 else
                      "priced assets show more given than received")
        return priced + "; assets with no reliable price also moved, so total compensation cannot be determined from this ledger"
    if not gave and not received:
        return "no priced value moved"
    if not gave:
        return "received value and gave nothing"
    if not received:
        return "gave value and received nothing"
    ratio = received / gave
    if abs(ratio - 1) <= EVEN_BAND:
        return "received about as much value as it gave"
    if ratio > 1:
        return "received more value than it gave"
    return f"gave more value than it received (got back about {ratio:.0%})"


def row_words(row: dict, facts: TxFacts) -> dict:
    out = {"party": describe(row["party"], facts)}
    for direction in ("gained", "lost"):
        items = [value_of(c, facts) for c in row["changes"] if c["direction"] == direction]
        if items:
            out[direction] = "; ".join(items)
    out["balance"] = exchange_words(row)
    return out


def volume_words(prior_transactions: int) -> str | None:
    return f"a very high-volume wallet, over {HIGH_VOLUME_TXS:,} prior transactions" if prior_transactions >= HIGH_VOLUME_TXS else None


def sender_words(facts: TxFacts) -> dict:
    s = facts["sender"]
    out = {"kind": s["kind"], "prior_transactions": s["prior_transactions"]}
    if s["label"]:
        out["identity"] = f"{s['label']} ({s['category']})"
    elif s["category"]:
        out["identity"] = f"a {s['category']}"
    if volume_words(s["prior_transactions"]):
        out["activity"] = volume_words(s["prior_transactions"])
    if s["first_funded_seconds_earlier"] is not None:
        out["first_funded"] = f"{span(s['first_funded_seconds_earlier'])} earlier"
        out["funded_by"] = (f"{s['funded_by']} ({s['funded_by_category']})" if s["funded_by"]
                            else f"a {s['funded_by_category']}" if s["funded_by_category"] else "an unlabeled address")
    elif s["funding_looked_up"]:
        out["first_funded"] = "no inbound ETH transfer found"
    if s["mixer_funded_within_30_days"]:
        mixer = f"{s['mixer_paid_by']} (mixer)" if s["mixer_paid_by"] else "a mixer"
        out["mixer_funding"] = f"received funds from {mixer} {span(s['mixer_paid_seconds_earlier'])} earlier"
    return out


def entry_words(facts: TxFacts) -> dict | str:
    entry = facts["entry"]
    if entry is None:
        return "none"
    info = facts["parties"][entry["alias"]]
    if info["kind"] in WALLET_KINDS:
        return f"none: the transaction is sent to {describe(entry['alias'], facts)}"
    out = {"contract": describe(entry["alias"], facts)}
    if entry["function"]:
        out["function_called"] = entry["function"]
    if entry["calls_in_prior_day"] is not None:
        n = entry["calls_in_prior_day"]
        out["use_in_prior_day"] = ("not called" if n == 0 else "called 100 or more times" if n >= 100
                                   else f"called {n} times")
    return out


def sender_side_words(facts: TxFacts) -> dict:
    side = facts["sender_side"]
    net, capital = side["net_usd"], side["own_capital_usd"]
    out = {"members": side["members"]}
    if abs(net) < 1:
        out["net_result"] = "no priced gain or loss"
    else:
        out["net_result"] = f"{'gained' if net > 0 else 'lost'} {money(net)}"
    out["own_capital_put_in"] = "none" if capital < 1 else money(capital)
    largest = max((max(r["gave_usd"], r["received_usd"]) for r in facts["ledger"]), default=0.0)
    if net >= BUCKETS[0][0] and largest:  # a negligible gain is not worth comparing
        share = net / largest
        out["gain_compared_with_largest_amount_moved"] = (
            "tiny (under 1% of it)" if share < 0.01 else "small (1% to 10% of it)" if share < 0.1
            else "substantial (10% to 50% of it)" if share < 0.5 else "most of it (over 50%)")
    if side["unpriced_assets"]:
        out["also_moved_unpriced_assets"] = [asset_name(a, facts) for a in side["unpriced_assets"]]
    if side["proceeds_to"]:
        out["proceeds_sent_to"] = [f"{money(p['usd'])} to {describe(p['party'], facts)}, {p['reason']}, counted as the sender's side's"
                                   for p in side["proceeds_to"]]
        out["net_result_of_the_sender_and_its_contracts_alone"] = (
            f"{'gained' if side['own_side_net_usd'] > 0 else 'lost'} {money(side['own_side_net_usd'])}"
            if abs(side["own_side_net_usd"]) >= 1 else "no priced gain or loss")
    if side["largest_gain_elsewhere"]:
        gain = side["largest_gain_elsewhere"]
        out["largest_gain_went_elsewhere"] = (f"the largest gain, {money(gain['usd'])}, went to {describe(gain['party'], facts)}, "
                                              "not to the sender's side")
    return out


def paid_words(drain: dict, facts: TxFacts) -> str:
    """What the party that gave out an asset received in the same transaction. A pool that sells half its balance of
    one token for full value is trading; a contract that pays out a small share of an old balance is paying a claim;
    what came back is stated either way, never judged."""
    caveat = ", not counting assets with no reliable price" if drain["unpriced_legs"] else ""
    if not drain["received_usd"]:
        if drain["unpriced_received"]:
            return "it received only assets with no reliable price (" + ", ".join(asset_name(a, facts) for a in drain["received_assets"]) + ")"
        return "no tokens came back to it in this transaction"
    got = f"it received {money(drain['received_usd'])} of " + ", ".join(asset_name(a, facts) for a in drain["received_assets"][:2])
    ratio = drain["received_usd"] / drain["gave_usd"]
    if ratio < 1 - EVEN_BAND:
        got += f", about {ratio:.0%} of what it gave out"
    return got + caveat


def share_words(share: float | None) -> str:
    if share is None:
        return "its balance just before is unknown or zero"
    if share >= 1:
        return "its entire balance just before this transaction, or more"
    if share < SMALL_SHARE:
        return "under 1% of its balance just before this transaction"
    return f"{share:.0%} of its balance just before this transaction"


def drain_words(drain: dict, facts: TxFacts) -> str:
    """One party's outflow with everything that says whether it was a sale, a payout, or a robbery: the share of its
    balance, its age (in its description), what came back, what it recorded, what the sender's side burned, and what
    the same sender put into it earlier in the block."""
    verb = "gave out" if drain["received_usd"] else "sent out"
    text = (f"{describe(drain['party'], facts)} {verb} {value_of(drain, facts)} "
            f"({share_words(drain['share_of_prior_balance'])}); {paid_words(drain, facts)}")
    if not drain["received_usd"] and drain["events_recorded"]:
        text += "; it recorded " + " and ".join(drain["events_recorded"]) + (" events" if len(drain["events_recorded"]) > 1 else " event")
    if not drain["received_usd"] and facts["sender_side"]["burned"]:
        text += "; the sender's side burned " + "; ".join(value_of(b, facts) for b in facts["sender_side"]["burned"][:2])
    if drain["same_sender_put_in_earlier"]:
        earlier = drain["same_sender_put_in_earlier"]
        text += (f"; the same sender put {value_of(earlier, facts)} into it earlier in this block "
                 f"(transaction {ordinal(earlier['index'] + 1)} of the block)")
    return text


def minted_words(minted: dict, facts: TxFacts) -> str:
    text = f"{value_of(minted, facts)}, minted to {minted['to']}"
    if minted["issued_by"] == "sender":
        text += " at the sender's own call"
    elif minted["issued_by"]:
        text += f" by {describe(minted['issued_by'], facts)}"
    if minted["issuer_received_from_side"] is not None:
        got = minted["issuer_received_from_side"]
        text += (", which received from the sender's side " + "; ".join(value_of(a, facts) for a in got[:2])) if got \
            else ", which received nothing from the sender's side in this transaction"
    return text


def lending_accounting_words(issuance: dict, facts: TxFacts) -> str:
    return (f"{describe(issuance['lender'], facts)} emitted Borrow and its call minted {value_of(issuance['issued'], facts)} "
            f"to {issuance['borrower']} in the same transaction. This issuance is linked to the lending operation, but does not by itself "
            "establish authorization or adequate collateral.")


def collateral_words(c: dict, facts: TxFacts) -> str:
    return (f"the sender's side minted {value_of(c['posted'], facts)} itself, posted it to {describe(c['posted_to'], facts)}, "
            f"and received {value_of(c['received'], facts)} from it")


def position_words(p: dict, facts: TxFacts) -> str:
    minted = f", {p['minted']} of them newly minted" if p["minted"] else ""
    to = f", to {', '.join(p['to'])}" if p["to"] else ""
    side = " (the sender's side)" if p["to_sender_side"] == p["count"] and p["count"] else ""
    amounts = f"; raw quantities include {', '.join(p['raw_amounts'])}" if p["raw_amounts"] else ""
    ids = f"; raw identifiers include {', '.join(p['raw_ids'])}" if p["raw_ids"] else ""
    return (f"{p['count']} ERC-1155 position transfer{'s' if p['count'] != 1 else ''} issued by "
            f"{describe(p['issuer'], facts)}{minted}{to}{side}; positions have no market price here{amounts}{ids}")


def allowance_words(change: dict, facts: TxFacts) -> str:
    giver = "the sender's side" if change["owner_is_sender_side"] else describe(change["owner"], facts)
    receiver = "the sender's side" if change["spender_is_sender_side"] else describe(change["spender"], facts)
    amount = change["asset"]
    value = (f"the maximum possible {asset_name(amount['asset'], facts)}"
             if int(amount["amount_raw"]) == 2**256 - 1 else value_of(amount, facts))
    return f"{giver} granted {value} allowance to {receiver}"


def internal_balance_words(change: dict, facts: TxFacts) -> str:
    account = "the sender's side" if change["account_is_sender_side"] else describe(change["account"], facts)
    return (f"{account} was {change['direction']} {value_of(change, facts)} as an internal balance in "
            f"{describe(change['vault'], facts)}")


def pull_words(pull: dict, facts: TxFacts) -> str:
    """Who took tokens with transferFrom, from how many addresses, under allowances granted when, and to whom."""
    amount = money(pull["usd"]) if pull["usd"] is not None else "an unpriced amount"
    assets = ", ".join(asset_name(a, facts) for a in pull["assets"])
    who = pull["spender_is"] + ("" if pull["spender_is"] == "the sender" else f" ({describe(pull['spender'], facts)})")
    granted = pull["approved_in_this_transaction"]
    when = ("granted in this same transaction" if granted == pull["transfers"] else
            "granted before this transaction" if granted == 0 else
            f"granted before this transaction for {pull['transfers'] - granted} of the {pull['transfers']} transfers")
    into = ", ".join(pull["recipients"]) or "unknown recipients"
    return (f"{who} pulled {amount} of {assets} from {pull['owners']} address{'es' if pull['owners'] != 1 else ''} "
            f"under allowances {when}, into {into}")


def shape_words(facts: TxFacts) -> dict:
    shape = facts["call_shape"]
    out = {k: shape[k] for k in ("calls", "max_depth", "distinct_contracts", "contracts_created",
                                 "contracts_destroyed", "reverted_inner_calls")}
    if shape["repeated_calls"]:
        out["repeated_calls"] = [f"{r['function'] or 'a function'} on {r['target']}, {r['count']} times"
                                 for r in shape["repeated_calls"]]
    if shape["nft_transfers"]:
        out["nft_transfers"] = shape["nft_transfers"]
    return out


def privileged_words(facts: TxFacts) -> list[str]:
    return [f"{p['event']} on {describe(p['contract'], facts)}"
            + (f", naming {describe(p['subject'], facts)}" if p["subject"] else "") for p in facts["privileged_events"]]


def render(facts: TxFacts) -> dict:
    """Every fact group as named fields in words: the state sent to the classifier."""
    tip = facts["mev"]["builder_payment_usd"]
    sheet = {
        "status": facts["status"],
        "sender": sender_words(facts),
        "entry_contract": entry_words(facts),
        "value_sent": money(facts["mev"]["value_sent_usd"]) + " of ETH" if facts["mev"]["value_sent_usd"] >= 1 else "none",
        "flash_loans": [f"{value_of(loan, facts)} from {describe(loan['lender'], facts)}"
                        for loan in facts["flash_loans"]],
        "protocols_touched": facts["protocols_touched"],
        "sender_side": sender_side_words(facts),
        "net_asset_changes": [row_words(r, facts) for r in facts["ledger"]],
        "newly_minted": [minted_words(m, facts) for m in facts["minted"]],
        "lending_accounting_issuances": [lending_accounting_words(item, facts) for item in facts["lending_accounting_issuances"]],
        "tokens_pulled_with_transferFrom": [pull_words(p, facts) for p in facts["pulls"]],
        "standalone_allowance_changes": [allowance_words(change, facts) for change in facts["allowance_changes"]],
        "internal_balance_changes": [internal_balance_words(change, facts) for change in facts["internal_balance_changes"]],
        "self_minted_collateral": [collateral_words(c, facts) for c in facts["self_minted_collateral"]],
        "positions_moved": [position_words(p, facts) for p in facts["positions_moved"]],
        "largest_losses": [drain_words(d, facts) for d in facts["drains"]],
        "preparation_shape": ("deploys a contract and moves positions or unpriced tokens while no priced value moves: the shape of "
                              "either a preparation step or an attack on assets nobody prices") if facts["precursor"] else None,
        "this_senders_earlier_transactions_in_this_window": [
            f"{n['blocks_earlier']} block{'s' if n['blocks_earlier'] != 1 else ''} earlier this sender {n['summary']}"
            for n in facts["earlier_by_this_sender"]],
        "logic_or_control_changed": [f"{describe(c['contract'], facts)} {c['what']}" for c in facts["logic_changes"]],
        "contracts_whose_logic_changed_recently": [
            (f"{describe(h['contract'], facts)} {h['what']} {h['blocks_earlier']} block{'s' if h['blocks_earlier'] != 1 else ''} earlier"
             + (f", after {span(h['contract_age_seconds'])} without a recorded change in this window" if h["contract_age_seconds"] else ""))
            for h in facts["heightened"]],
        "reentrancy": [f"{describe(r['contract'], facts)} was {'read' if r['read_only'] else 'called'} again through "
                       f"{r['through']} before an earlier call into it had finished" for r in facts["reentrancy"]]
        or "none detected",
        "privileged_events": privileged_words(facts),
        "events": [f"{e['event']} by {e['contract']}" + (f", {e['count']} times" if e["count"] > 1 else "")
                   for e in facts["events"]],
        "call_shape": shape_words(facts),
        "block_position": f"{ordinal(facts['mev']['position'])} of {facts['mev']['block_transactions']}",
        "builder_payment": money(tip) if tip >= 1 else "none",
    }
    return sheet

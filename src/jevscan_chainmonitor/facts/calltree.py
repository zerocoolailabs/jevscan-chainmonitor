"""The pruned call tree printed in each record."""

from jevscan_chainmonitor.facts.constants import (
    CREATE_KINDS,
    FUNCTION_NAME,
    INHERITS_CONTEXT,
    PRICE_READS,
    TOKEN_SELECTORS,
    TREE_MAX_DEPTH,
    TREE_TOKEN_CAP,
    VALUE_KINDS,
)
from jevscan_chainmonitor.facts.context import Context
from jevscan_chainmonitor.facts.naming import Naming
from jevscan_chainmonitor.facts.trace import Core, Frame, frames_of, is_precompile


def function_name(target: str, selector: str | None, names: Naming, ctx: Context) -> str | None:
    """A function's name, only for a call into a labeled, established contract. On any other contract the selector is
    its deployer's choice, so a name resolved from it is attacker-controlled text: bots mine selectors that resolve
    to names like IBribe2MuchZ7650399733."""
    if selector is None or names.label(target) is None:
        return None
    return FUNCTION_NAME.get(selector) or ctx.function_names.get(selector)


def call_tree(core: Core, names: Naming, ctx: Context) -> list[str]:
    """The call tree as indented lines, pruned: no read-only calls except known price reads, no calls into token
    contracts (the ledger has their effect), proxies folded into their callers, repeats collapsed to one line with a
    count, and depth cut until the text fits TREE_TOKEN_CAP."""
    tokens = {m.asset for m in core.movements}

    def is_token(address: str) -> bool:
        return address in tokens or ctx.labels.get(address, {}).get("category") == "token"

    def subtree(frame: Frame, depth: int, limit: int) -> list[str]:
        blocks: list[list[str]] = []
        for child in frame.children:
            if child.failed or not child.target or is_precompile(child.target):
                continue
            if child.kind in INHERITS_CONTEXT:  # a proxy's implementation: its calls are the proxy's calls
                blocks += [[line] for line in subtree(child, depth, limit)]
                continue
            if (child.static and child.selector not in PRICE_READS) or \
                    (is_token(child.target) and (child.static or child.selector in TOKEN_SELECTORS)):
                continue
            indent = "  " * depth
            if depth >= limit:
                blocks.append([f"{indent}({sum(1 for _ in frames_of(child))} deeper calls not shown)"])
                continue
            name = function_name(child.target, child.selector, names, ctx)
            bare_payment = child.value and not child.children and child.selector is None
            callee = names.party(child.target, "wallet" if bare_payment else "contract")
            if child.kind in CREATE_KINDS:
                text = f"{names.party(child.caller)} creates {callee}"
            elif child.static:
                text = f"{names.party(child.caller, 'contract')} reads {name or 'a price'} from {callee}"
            elif bare_payment:
                text = f"{names.party(child.caller, 'contract')} pays {callee}"
            else:
                text = f"{names.party(child.caller, 'contract')} calls {callee}" + (f".{name}" if name else "")
            if child.value and child.kind in VALUE_KINDS:
                text += f" with {child.value / 1e18:.4g} ETH"
            blocks.append([indent + text, *subtree(child, depth + 1, limit)])
        lines: list[str] = []
        for i, block in enumerate(blocks):
            if i and blocks[i - 1] == block:
                continue
            run = 1
            while i + run < len(blocks) and blocks[i + run] == block:
                run += 1
            lines += [block[0] + (f"  (x{run})" if run > 1 else ""), *block[1:]]
        return lines

    def tokens_of(lines: list[str]) -> float:
        return sum(len(line) + 1 for line in lines) / 3.5

    for limit in range(TREE_MAX_DEPTH, 0, -1):
        tree = subtree(core.root, 0, limit)
        if tokens_of(tree) <= TREE_TOKEN_CAP:
            return tree
    kept: list[str] = []
    for line in tree:
        if tokens_of(kept + [line]) > TREE_TOKEN_CAP - 20:
            return kept + [f"({len(tree) - len(kept)} more lines not shown)"]
        kept.append(line)
    return kept

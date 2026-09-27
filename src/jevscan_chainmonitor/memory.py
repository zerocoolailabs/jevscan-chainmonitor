"""What a monitor that follows the chain remembers between blocks, so repeated explorer lookups are answered locally.

Enrichment asks Etherscan two questions per block that a running monitor can answer itself:

- Who called this contract in the prior day? The monitor has read every recent block, so it keeps each contract's
  top-level calls and counts them the way the explorer's transaction list would.
- When was this new wallet first funded, and by whom? A wallet's earliest funding never changes once it exists, so
  the first answer is kept and reused for its later transactions.
"""

import asyncio
from bisect import bisect_left
from collections import defaultdict

from jevscan_chainmonitor.facts import Funding


class ChainMemory:
    def __init__(self) -> None:
        self.calls: dict[str, list[tuple[int, int, str]]] = defaultdict(list)  # contract -> (block, index, sender)
        self.first: int | None = None
        self.last: int | None = None
        self.funding: dict[str, tuple[tuple[int, int], Funding]] = {}  # wallet -> (where it was found, funding)

    def add_block(self, block: dict, receipts: list[dict]) -> None:
        """Record the block's top-level calls. Blocks must arrive in order with no gap, so the memory's range is
        exactly the blocks it has seen."""
        number = int(block["number"], 16)
        if self.last is not None and number != self.last + 1:
            raise ValueError(f"Block {number} does not follow block {self.last}")
        for tx, receipt in zip(block["transactions"], receipts):
            target = tx.get("to") or receipt.get("contractAddress")  # a creation counts toward the new contract
            if target:
                self.calls[target.lower()].append((number, int(tx["transactionIndex"], 16), tx["from"].lower()))
        self.first = number if self.first is None else self.first
        self.last = number

    def covers(self, start: int, end: int) -> bool:
        return self.first is not None and self.first <= start and end <= self.last

    def recent_callers(self, address: str, start: int, end: int, limit: int) -> list[str]:
        """Senders of the latest `limit` top-level calls into `address` in blocks start..end, newest first: what the
        explorer's descending transaction list returns for that range."""
        calls = self.calls.get(address, [])
        low, high = bisect_left(calls, (start, -1, "")), bisect_left(calls, (end + 1, -1, ""))
        return [sender for _, _, sender in reversed(calls[low:high])][:limit]

    def forget_before(self, block: int) -> None:
        """Drop calls older than `block`, keeping memory bounded to the window a monitor needs."""
        for address in list(self.calls):
            calls = self.calls[address]
            kept = calls[bisect_left(calls, (block, -1, "")):]
            if kept:
                self.calls[address] = kept
            else:
                del self.calls[address]
        if self.first is not None:
            self.first = max(self.first, block)


async def load_blocks(rpc, memory: ChainMemory, start: int, end: int, concurrency: int = 32) -> None:
    """Fill `memory` with blocks start..end, as a monitor that had been running would hold them. Only a creation's
    receipt is fetched, for the address of the contract it made."""
    gate = asyncio.Semaphore(concurrency)

    async def one(number: int) -> tuple[dict, list[dict]]:
        async with gate:
            block = await rpc.call("eth_getBlockByNumber", [hex(number), True], cached=False)
            receipts = {}
            for tx in block["transactions"]:
                if not tx.get("to"):
                    receipts[tx["hash"]] = await rpc.call("eth_getTransactionReceipt", [tx["hash"]], cached=False)
            return block, [receipts.get(tx["hash"], {}) for tx in block["transactions"]]

    for low in range(start, end + 1, 256):
        for block, receipts in await asyncio.gather(*(one(n) for n in range(low, min(low + 256, end + 1)))):
            memory.add_block(block, receipts)

"""What a monitor remembers between blocks must answer exactly as the explorer lookups it replaces."""

import asyncio

import pytest

from jevscan_chainmonitor import enrich
from jevscan_chainmonitor.facts import extract
from jevscan_chainmonitor.memory import ChainMemory
from tests.helpers import SENDER, WALLET, addr, chain_data, frame

CONTRACT = addr(300)


def block(number: int, calls: list[tuple[str | None, str]]) -> tuple[dict, list[dict]]:
    """A block whose transactions are (target, sender) pairs; a target of None creates a contract."""
    txs = [{"to": target, "from": sender, "transactionIndex": hex(i), "hash": f"0x{number:032x}{i:032x}"}
           for i, (target, sender) in enumerate(calls)]
    receipts = [{"contractAddress": addr(900 + number)} if target is None else {} for target, _ in calls]
    return {"number": hex(number), "transactions": txs}, receipts


def test_recent_callers_are_the_newest_calls_in_the_range_like_the_explorer_list():
    memory = ChainMemory()
    for number in range(10, 16):
        memory.add_block(*block(number, [(CONTRACT, addr(number)), (WALLET, SENDER), (CONTRACT.upper().replace("0X", "0x"), addr(50))]))
    assert memory.covers(10, 15) and not memory.covers(9, 15)
    assert memory.recent_callers(CONTRACT, 11, 13, 100) == [addr(50), addr(13), addr(50), addr(12), addr(50), addr(11)]
    assert memory.recent_callers(CONTRACT, 11, 13, 2) == [addr(50), addr(13)]
    assert memory.recent_callers(addr(301), 10, 15, 100) == []


def test_a_creation_counts_toward_the_new_contract():
    memory = ChainMemory()
    memory.add_block(*block(20, [(None, SENDER)]))
    assert memory.recent_callers(addr(920), 20, 20, 100) == [SENDER]


def test_blocks_must_arrive_in_order_and_old_ones_can_be_forgotten():
    memory = ChainMemory()
    memory.add_block(*block(30, [(CONTRACT, SENDER)]))
    with pytest.raises(ValueError, match="does not follow"):
        memory.add_block(*block(32, []))
    memory.add_block(*block(31, [(CONTRACT, WALLET)]))
    memory.forget_before(31)
    assert memory.recent_callers(CONTRACT, 0, 40, 100) == [WALLET] and not memory.covers(30, 31)


def test_a_wallets_first_funding_is_looked_up_once_and_reused_later():
    asked = []

    class Explorer:
        async def etherscan(self, params):
            asked.append(params["action"])
            return [{"blockNumber": "5", "transactionIndex": "0", "to": SENDER, "from": addr(7), "value": "1",
                     "timeStamp": "1000", "isError": "0"}] if params["action"] == "txlist" else []

    memory = ChainMemory()
    earlier = extract(*chain_data(frame(SENDER, WALLET), index=1))
    later = extract(*chain_data(frame(SENDER, WALLET), index=5))
    first = asyncio.run(enrich.fetch_funding(Explorer(), earlier, memory=memory))
    again = asyncio.run(enrich.fetch_funding(Explorer(), later, memory=memory))
    assert first == again == {"timestamp": 1000, "funder": addr(7)}
    assert asked == ["txlist", "txlistinternal"]  # the later transaction asked nothing

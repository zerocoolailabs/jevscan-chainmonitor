"""Every fixed value the extractor uses: the facts version, known event and function signatures, and the threshold
of each heuristic. Changing any value that affects a record requires a new FACTS_VERSION."""

import json
from pathlib import Path

FACTS_VERSION = 13  # release hardening changes aliases and excludes external NFT names
HERE = Path(__file__).resolve().parent
SIGNATURES = json.loads((HERE / "signatures.json").read_text())
TOPIC: dict[str, str] = SIGNATURES["events"]
SELECTOR: dict[str, str] = SIGNATURES["functions"]
EVENT_NAME = {topic: sig.split("(")[0] for sig, topic in TOPIC.items()}
FUNCTION_NAME = {selector: sig.split("(")[0] for sig, selector in SELECTOR.items()}

ETH = "ETH"
ZERO = "0x" + "0" * 40
WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
VALUE_KINDS = {"CALL", "CREATE", "CREATE2", "SELFDESTRUCT"}  # DELEGATECALL repeats its parent's value; nothing moves
CREATE_KINDS = {"CREATE", "CREATE2"}
INHERITS_CONTEXT = {"DELEGATECALL", "CALLCODE"}
PRECOMPILE_LIMIT = 0x400

TRANSFER = TOPIC["Transfer(address,address,uint256)"]
WETH_DEPOSIT = TOPIC["Deposit(address,uint256)"]
WETH_WITHDRAWAL = TOPIC["Withdrawal(address,uint256)"]
NFT_BATCH_TOPICS = {TOPIC["TransferSingle(address,address,address,uint256,uint256)"],
                    TOPIC["TransferBatch(address,address,address,uint256[],uint256[])"]}
INTERNAL_BALANCE_CHANGED = TOPIC["InternalBalanceChanged(address,address,int256)"]
SWAP_TOPICS = {topic for sig, topic in TOPIC.items() if sig.startswith(("Swap(", "TokenExchange"))}
NOISE_TOPICS = {TRANSFER, TOPIC["Approval(address,address,uint256)"], TOPIC["ApprovalForAll(address,address,bool)"],
                TOPIC["Sync(uint112,uint112)"], WETH_DEPOSIT, WETH_WITHDRAWAL} | NFT_BATCH_TOPICS
UNISWAP_V3_FLASH = TOPIC["Flash(address,address,uint256,uint256,uint256,uint256)"]
# topic -> (where the asset is, where the amount is). ("topic", i) is topics[i]; ("data", i) is the i-th data word.
FLASH_LOAN_EVENTS = {
    TOPIC["FlashLoan(address,address,address,uint256,uint256,uint16)"]: (("topic", 3), ("data", 0)),  # Aave V2
    TOPIC["FlashLoan(address,address,address,uint256,uint8,uint256,uint16)"]: (("topic", 2), ("data", 1)),  # Aave V3
    TOPIC["FlashLoan(address,address,uint256,uint256)"]: (("topic", 2), ("data", 0)),  # Balancer V2, Maker (below)
    TOPIC["FlashLoan(address,address,uint256)"]: (("topic", 2), ("data", 0)),  # Morpho
}
# topic -> where the address that gains the power is, or None when the event names nobody
PRIVILEGED_EVENTS = {
    TOPIC["OwnershipTransferred(address,address)"]: ("topic", 2),
    TOPIC["OwnershipTransferStarted(address,address)"]: ("topic", 2),
    TOPIC["Upgraded(address)"]: ("topic", 1),
    TOPIC["BeaconUpgraded(address)"]: ("topic", 1),
    TOPIC["AdminChanged(address,address)"]: ("data", 1),
    TOPIC["RoleGranted(bytes32,address,address)"]: ("topic", 2),
    TOPIC["RoleRevoked(bytes32,address,address)"]: ("topic", 2),
    TOPIC["NewAdmin(address,address)"]: ("data", 1),
    TOPIC["NewPendingAdmin(address,address)"]: ("data", 1),
    TOPIC["NewImplementation(address,address)"]: ("data", 1),
    TOPIC["ChangedMasterCopy(address)"]: ("data", 0),
    TOPIC["EnabledModule(address)"]: ("data", 0),
    TOPIC["DisabledModule(address)"]: ("data", 0),
    TOPIC["ChangedGuard(address)"]: ("data", 0),
    TOPIC["Initialized(uint8)"]: None,
    TOPIC["Initialized(uint64)"]: None,
    TOPIC["Paused(address)"]: None,
    TOPIC["Unpaused(address)"]: None,
    TOPIC["AddedOwner(address)"]: None,
    TOPIC["RemovedOwner(address)"]: None,
    TOPIC["ChangedThreshold(uint256)"]: None,
}
TOKEN_SELECTORS = {SELECTOR[s] for s in (
    "transfer(address,uint256)", "transferFrom(address,address,uint256)", "approve(address,uint256)",
    "balanceOf(address)", "allowance(address,address)", "decimals()", "symbol()", "name()", "totalSupply()",
    "permit(address,address,uint256,uint256,uint8,bytes32,bytes32)", "deposit()", "withdraw(uint256)")}
# An entry point whose whole design is to call the caller back and be called again: flash accounting (Uniswap V4's and
# Balancer V3's unlock). Re-entering through it is how it is used, like repaying a flash loan inside its callback.
REENTRANT_BY_DESIGN = {SELECTOR["unlock(bytes)"]}
PRICE_READS = {selector for sig, selector in SELECTOR.items() if selector not in TOKEN_SELECTORS | REENTRANT_BY_DESIGN
               and not sig.startswith("uniswapV")}

ESTABLISHED_SECONDS = 30 * 86400  # the 30-day rule, for labels and for calling a contract established
SLOT_SECONDS = 12  # turns a distance in blocks into a time
LEDGER_PARTIES = 8
DRAIN_CANDIDATES = 3
DRAIN_MIN_USD = 1_000.0
NEW_WALLET_CHECKS = 3
REPEAT_MIN = 3
REPEATS_SHOWN = 5
REENTRY_CAP = 50
PUBLIC_SENDERS = 3  # distinct wallets calling an entry contract in the prior day that make it public infrastructure
HIGH_VOLUME_TXS = 100_000  # prior transactions from which the views call a wallet very high-volume
TRANSFER_FROM = SELECTOR["transferFrom(address,address,uint256)"]
APPROVAL = TOPIC["Approval(address,address,uint256)"]
PULL_RECIPIENTS_SHOWN = 3
PULL_MIN_USD = 1_000.0  # a pull below this is protocol plumbing, not a sweep or a drain
PROCEEDS_MIN_USD = 1_000.0  # a gain below this is not "proceeds" worth attributing to anyone
PROCEEDS_SHARE = 0.5  # a party taking at least this share of the largest loss, while the sender's side keeps little
SIDE_KEEPS_SHARE = 0.1
IMPLIED_MIN_USD = 1_000.0  # an exchange this small says nothing about an unpriced asset's value
IMPLIED_PASSES = 3
IMPLIED_REACH = 10  # an implied price holds for amounts up to this many times the quantity that was exchanged
FRESH_CODE_SECONDS = 86400  # a delegatecall into code created within a day of the call
LOGIC_EVENTS = {"Upgraded", "BeaconUpgraded", "AdminChanged", "NewImplementation", "NewAdmin", "OwnershipTransferred",
                "ChangedMasterCopy", "EnabledModule", "DisabledModule", "ChangedGuard", "RoleGranted"}
WALLET_KINDS = ("wallet", "delegated wallet")
MULTISIG_EVENTS = {"ExecutionSuccess", "ExecutionFailure"}  # a Safe executing a signed transaction: its owners' wallet, nobody's bot
NEW_WALLET_NONCES = 5  # a wallet with fewer prior transactions than this is new
EVENTS_SHOWN = 12
PROTOCOLS_SHOWN = 8
TREE_TOKEN_CAP = 4_800  # estimated tokens; keeps the call tree readable next to the fact sheet
TREE_MAX_DEPTH = 12

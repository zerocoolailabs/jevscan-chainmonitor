# Jevscan Chain Monitor

Jevscan scans every transaction in a block for possible smart-contract exploits. It reconstructs what happened, derives the economic facts, and asks [Jev](https://typesafe.ai/), a language-model classifier, whether those facts describe an attack.

In our benchmarking, Jevscan caught 56 of 60 known hacks (93.3%). Across 36,357 transactions, it raised 21 potential false positives (0.058%).

Scanning a block took an average of 2.7 seconds with supporting data, such as contract history and historical prices, pre-cached. The block itself, its receipts and call traces were fetched during processing. See the [benchmark results and methodology](docs/RESULTS.md).

## How it works

1. **Collect.** Fetch complete blocks, receipts and call traces from an Ethereum RPC node with tracing support.
2. **Extract.** Calculate gains and losses, identify the sender's contracts, and record borrowing, token issuance, reentrancy and control changes.
3. **Enrich.** Add historical prices, contract history, address labels and mixer funding.
4. **Classify.** Send each transaction's fact sheet to Jev and flag possible attacks.

## Another use for protocol teams

We built Jevscan to scan every transaction in every block. A protocol team could also use it to watch its own contracts, adding invariants, permissions and important addresses to the transaction facts. It could monitor relevant storage changes each block, giving Jev more context to assess activity against the protocol's rules.

## Run

Requires macOS or Linux, Python 3.11–3.14, an Ethereum RPC endpoint with tracing support, and Etherscan and TypeSafe API keys. From the repository directory:

```sh
pip install .

export MAINNET_RPC_URL="https://eth-mainnet.g.alchemy.com/v2/YOUR_KEY"
export ETHERSCAN_API_KEY="YOUR_KEY"
export TYPESAFE_API_KEY="YOUR_KEY"

jevscan-chainmonitor scan --block 22785461 --budget-usd 1 --output scan.json
```

`scan` collects, enriches and classifies automatically. To keep following newly finalized blocks:

```sh
jevscan-chainmonitor monitor --budget-usd 10 --output alerts.jsonl
```

The first run builds local indexes. Etherscan supplies missing contract and wallet history; caching reduces those requests but does not eliminate them. `--budget-usd` is the workspace's cumulative classifier budget; RPC and explorer costs are separate. Fact sheets are sent to TypeSafe.

See the [usage guide](docs/USAGE.md) for ranges, caching, costs, library use and benchmark reproduction.

## License

MIT

# Usage guide

Install and set the three API keys as shown in the [README](../README.md). Credentials come from the process environment; the application does not load `.env` automatically.

The RPC endpoint must provide blocks, receipts, `debug_traceBlockByNumber` and state queries for the blocks being scanned. Use an archive-capable endpoint when scanning old historical blocks; the requirement is access to the necessary data, not a particular node deployment.

## Scan blocks

`scan` collects the block data, extracts and enriches the facts, and classifies every transaction. No separate collection command is needed.

```sh
jevscan-chainmonitor scan --block 22785461 --budget-usd 1 --output scan.json
jevscan-chainmonitor scan --start-block 22785461 --end-block 22785480 --budget-usd 5 --output scan-20-blocks.json
```

Ranges can contain up to 20 consecutive finalized blocks. The output lists each transaction, its scores and whether it was flagged. Flagged transactions include the fact sheet Jev read. Choose a fresh output filename; existing files are never overwritten.

If any fact sheet exceeds the classifier's 48 KB request limit, scoring stops without writing a complete result. No transaction is silently skipped.

To collect and score separately, for example to inspect the estimated classifier cost:

```sh
jevscan-chainmonitor collect --block 22785461 --output resupply.json
jevscan-chainmonitor score --input resupply.json --dry-run
jevscan-chainmonitor score --input resupply.json --budget-usd 1 --output resupply-scores.json
```

Commands print the reason for a failure. Add `--debug` for a traceback; inspect it for sensitive information before sharing it.

## Monitor the chain

```sh
jevscan-chainmonitor monitor --budget-usd 10 --output alerts.jsonl
```

The monitor starts at the finalized head and loads the preceding day of blocks into memory. It then scores each newly finalized block and writes one JSON line containing the transaction count, collection and classification times, and flagged transactions with their fact sheets. `--start-block` starts earlier; `--blocks` stops after a specified number of blocks.

This follows finalized blocks, not pending transactions or the unfinalized head. Finalization and polling delays are additional to processing time. Finalized batches can also queue behind blocks still being processed.

## Caching

See the [benchmark results and timing methodology](RESULTS.md#timing-methodology) for measured performance and cache-preparation details.

### Why an Etherscan key is still needed

The monitor remembers recent contract activity and a wallet's first funding once found, and caches contract deployers across runs. New contracts, wallets and uncached historical queries still require Etherscan. A cached benchmark is therefore faster to enrich than fresh live traffic and does not remove the key requirement for general use.

The first run downloads address labels and builds the historical mixer-payout index. Later runs extend the index and reuse cached lookups. Caches, indexes and the spending ledger live in `~/.local/share/jevscan-chainmonitor`; set `JEVSCAN_DATA_DIR` to choose another directory.

The default Etherscan pace is two requests per second. Set `JEVSCAN_ETHERSCAN_CALLS_PER_SECOND` only within your plan's rate and daily quotas. Faster permitted lookups and better cache coverage should reduce collection time; sustained four-second live processing has not been demonstrated by these measurements.

## Costs and data

`--budget-usd` caps cumulative classifier spending in the workspace using an assumed price of $0.042 per million input tokens. Set provider-side quotas as well. RPC and Etherscan costs are separate. Reusing the workspace preserves the spending history and cached answers.

The rendered fact sheets go to TypeSafe for classification. They use aliases and descriptions rather than addresses or transaction hashes. An Alchemy endpoint also supports the NFT floor-price enrichment used in the benchmark.

## Use as a library

```python
import asyncio
import jevscan_chainmonitor as jcm

results = asyncio.run(jcm.scan(22785461, 22785461, budget_usd=1))
for row in results:
    if row["flagged"]:
        print(row["transaction"], row["scores"], row["fact_sheet"]["largest_losses"])
```

`collect_facts(start, end)` returns facts without classification; `render(record)` creates a fact sheet. `score(records, classifier)` accepts an object with an async `classify(state, questions, *, input_version)` method, allowing a different classifier.

The model, questions and threshold are in [detector.json](../src/jevscan_chainmonitor/data/detector.json). Pass `load_detector(path)` to `score` or `scan`, or `--detector path` to the CLI, to use another configuration.

## Reproduce the benchmark

Check the stored score digests and recompute the benchmark metrics without network calls:

```sh
jevscan-chainmonitor results
```

Collect and classify the historical benchmark using the current extractor:

```sh
jevscan-chainmonitor benchmark --budget-usd 5 --output benchmark.json
jevscan-chainmonitor benchmark --incidents evidence/held-out-incidents.json --budget-usd 1 --output held-out.json
```

These commands reuse cached classifier answers when available; a cached replay is not a fresh model measurement. The evaluation groups and repeat runs are explained in [benchmark results](RESULTS.md).

## Development

```sh
pip install '.[test]'
pytest
ruff check .
```

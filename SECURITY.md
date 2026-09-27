# Security

## Reporting a vulnerability

Report vulnerabilities privately through GitHub's **Report a vulnerability** button on this repository's Security tab. Do not open a public issue for a vulnerability, and do not post credentials, workspace files or details that endanger a live protocol.

## Using the scores

A flag is evidence for a human to review, not proof of an attack, and an unflagged transaction is not proven safe. Do not connect scores directly to signing keys, contract administration, automatic pauses or other irreversible actions. The package has no transaction-submission feature.

## Credentials and data

- Credentials come only from the process environment. No `.env` file is loaded. Use scoped API keys with provider-side quotas, and keep them out of command arguments, commits and reports.
- Collection sends requests to your RPC endpoint, Etherscan, DefiLlama, the Sourcify signature database and GitHub (for the pinned label dump). Scoring sends rendered fact sheets and the detector's questions to TypeSafe. Fact sheets contain aliases and descriptions, not addresses or transaction hashes.
- The workspace (`~/.local/share/jevscan-chainmonitor` or `JEVSCAN_DATA_DIR`) holds cached provider responses and the spending ledger. Keep it private and do not share it between users.
- Error messages replace configured credentials with their variable names and neutralize control characters from remote text. That is defense in depth, not a guarantee that arbitrary output is safe to publish.

## Untrusted input

Transaction data, contract-chosen names and external labels are attacker-influenced. Labels and token symbols reach the classifier only after allowlist, denylist and character filters, and only for contracts older than 30 days; every other party is a numbered alias. Function names resolve only for calls into labeled, established contracts. These measures reduce exposure to prompt injection; they do not prove resistance to it.

Every block, receipt and trace is checked for consistency before extraction, and a block that fails is not evaluated. Trace limits accommodate large transactions, but a rendered fact sheet above the classifier's 48 KB request limit stops scoring. The tool does not silently omit that transaction or report the block as fully evaluated.

## Spending

`--budget-usd` caps cumulative classifier spending for a workspace, assuming $0.042 per million input tokens. Each request records a reservation of 55,000 input tokens in the ledger before it is sent, and the budget check and reservation cannot interleave between concurrent requests. A request refused with a rate limit or a gateway error is retried up to twice, and every attempt keeps its own reservation. A request that times out or returns a malformed answer may already have been billed, so it keeps its reservation and is not retried. These are local estimates, not the provider's billing: set a provider-side quota as well.

# Notices

The code and documentation in this repository are offered under the MIT license in [LICENSE](LICENSE).

## External data and services

- **Address labels.** Collection downloads the public [dawsbot/eth-labels](https://github.com/dawsbot/eth-labels) dataset (MIT) at the commit pinned in `src/jevscan_chainmonitor/labels.py` and keeps a filtered copy in the local workspace. The dataset is not bundled. Check its license before redistributing a derived label file.
- **Provider APIs.** RPC, Etherscan, DefiLlama, Sourcify, Alchemy NFT and TypeSafe responses remain subject to each provider's terms. This license grants no rights to those services or their data.
- **Benchmark evidence.** `evidence/` contains transaction hashes, incident names and dates, links to public incident reports, detector questions and derived scores. The linked articles, audit reports and provider responses are not reproduced. A link does not imply the source's endorsement.

## Dependencies

Python dependencies keep their own licenses. The lock files record the exact versions and hashes, and each installed distribution includes its license notice.

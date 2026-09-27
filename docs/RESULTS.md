# Benchmark results and methodology

## Combined evaluation

Across 36,357 transactions in the published historical, ordinary-block and live-monitor evaluations, the latest benchmark repeat plus the ordinary and live results produced 21 potential false positives (0.058% of all evaluated transactions). The detector caught 56 of 60 known hacks (93.3%), flagging 70 of their 80 attack transactions.

| Evaluation | Transactions | Known attack transactions caught | Potential false positives |
|---|---:|---:|---:|
| Original 50 hacks, latest repeat | 13,017 | 60 of 70 | 6 |
| Additional 10 hacks, latest repeat | 1,032 | 10 of 10 | 0 |
| 20 ordinary blocks | 5,420 | Not labeled as an attack set | 0 |
| 80 live blocks | 16,888 | Not labeled as an attack set | 15 |
| Total | 36,357 | 70 of 80 known attack transactions | 21 |

The historical groups and ordinary sample have disjoint transaction hashes. Their block ranges also precede the live sample. Repeated classifications of the same transactions count once, not as additional coverage. This total covers the published evaluation datasets, not incidental performance probes or blocks fetched only for context.

The README uses the latest repeat, which also had fewer potential false positives. Substituting the first September 26 benchmark run yields 23 potential false positives (0.063%) on the same 36,357 transactions, with the same 56 hacks caught. This variation is retained below rather than combining the best answer for each transaction. Potential false positives are alerts outside the known-attack labels, not all independently confirmed benign transactions; the percentage is their share of the full evaluated sample.

## Historical runs

Jevscan Chain Monitor was tested on 60 historical Ethereum exploits. In the first September 26, 2026 run, it caught 56 of them, including all 10 exploits held out from tuning. It raised 8 potential false positives among the 13,969 other transactions in those exploits' blocks (0.06%), and none among 5,420 transactions in 20 consecutive ordinary blocks.

| | Sept 26, 2026 (this release) | Sept 22–23, 2026 (research) |
|---|---:|---:|
| Hacks caught, all 60 | 56 | 49 |
| Calibration hacks caught | 46 of 50 | 42 of 50 |
| Held-out hacks caught | 10 of 10 | 7 of 10 |
| Attack transactions flagged, calibration hacks | 60 of 70 | 55 of 70 |
| Potential false positives, calibration blocks | 7 of 12,947 | 5 of 12,947 |
| Potential false positives, held-out blocks | 1 of 1,022 | 0 of 1,022 |
| Alerts in 20 ordinary blocks | 0 of 5,420 | 0 of 5,420 |

Catching a hack means flagging at least one of its attack transactions; some hacks took several. The 50 calibration hacks were used while the detector's questions were written. The 10 held-out hacks were admitted afterwards, each named by two independent public sources, and none shaped a question, the threshold or a fact. Each hack's facts were built from its attack blocks and the five blocks on either side, and every transaction in the attack blocks was scored.

## Why the two runs differ

The change from eight to six potential false positives in the same-day repeat came from two score changes: the Aave V4 borrowing transaction moved from 0.70 to 0.69, and the additional alert beside the Aave ParaSwap exploit moved from 0.73 to 0.68. Both crossed below the unchanged 0.70 threshold. The five-potential-false-positive figure belongs to the older research run, not this repeat.

The two runs scored almost the same input. Of the 13,017 fact sheets in the calibration blocks, 12,857 are byte-identical between the research extractor and this release. The other 160 differ because this release no longer shows NFT marketplace names (118), numbers aliases so two parties never share one (26), or lists some lines in a different order.

The classifier's answers differ more. A second full run on September 26 reproduced the first almost exactly: the same 46 and 10 hacks, one flag in the 13,017 calibration transactions changed, and it raised 6 potential false positives instead of 8. Between the research run and September 26, about half of the scores above 0.4 moved by more than 0.05, in both directions. Two causes are likely. The research scored each question in its own request, while this release asks both in one request. And hosted models answer identical requests slightly differently depending on server load and deployment ([Thinking Machines, 2025](https://thinkingmachines.ai/blog/defeating-nondeterminism-in-llm-inference/); [Chen, Zaharia and Zou, 2023](https://arxiv.org/abs/2307.09009)). The held-out hacks were requested the same way both times, and three near misses (0.57 to 0.64) still crossed the 0.7 threshold.

Every change in outcome came from transactions scoring near the threshold. Each figure here is a dated measurement, and both runs are in `evidence/`, where `jevscan-chainmonitor results` recomputes them.

## The 50 calibration hacks

The counts show attack transactions caught out of those tested. Transaction links and [source reports](../evidence/incidents.json) identify the examples.

| Hack | Date | Sept 26 | Sept 22 | Transactions |
|---|---|---:|---:|---|
| Resupply | 2025-06-26 | 1/1 | 1/1 | [1](https://etherscan.io/tx/0xffbbd492e0605a8bb6d490c3cd879e87ff60862b0684160d08fd5711e7a872d3) |
| Conic ETH omnipool | 2023-07-21 | 1/1 | 1/1 | [1](https://etherscan.io/tx/0x8b74995d1d61d3d7547575649136b8765acb22882960f0636941c44ec7bbe146) |
| Pike Finance | 2024-04-30 | 1/1 | 1/1 | [1](https://etherscan.io/tx/0xe2912b8bf34d561983f2ae95f34e33ecc7792a2905a3e317fcc98052bce66431) |
| Socket/Bungee | 2024-01-16 | 1/1 | 1/1 | [1](https://etherscan.io/tx/0xc6c3331fa8c2d30e1ef208424c08c039a89e510df2fb6ae31e5aa40722e28fd6) |
| Hedgey | 2024-04-19 | 1/2 | 1/2 | [1](https://etherscan.io/tx/0xa17fdb804728f226fcd10e78eae5247abd984e0f03301312315b89cae25aa517), [2](https://etherscan.io/tx/0x2606d459a50ca4920722a111745c2eeced1d8a01ff25ee762e22d5d4b1595739) |
| Summer.fi Lazy Summer | 2026-07-06 | 1/1 | 1/1 | [1](https://etherscan.io/tx/0x0db528c44f23fc7fa4544684a2fab81096450a14aae8bc89f42cd0592d43da12) |
| Flamincome VaultYUSDT | 2026-09-16 | 1/1 | 1/1 | [1](https://etherscan.io/tx/0x5ff8150482f5473bff16b4a142a98a7f72b159df5e9dd38afd90470551640d37) |
| rsETH Safe module | 2026-09-15 | 0/1 | 0/1 | [1](https://etherscan.io/tx/0x0e7680b06cb8a6f86c149d9ba90d98e3d334e7b072dde03909d43fcfd98a8705) |
| Notional V1 escrow | 2026-09-03 | 1/2 | 1/2 | [1](https://etherscan.io/tx/0xe1589a19fe742f0d553889214abade69551fe944acffac014c28cc07b325d60a), [2](https://etherscan.io/tx/0xc3f3e318f7ab2d0daaba59e6ec901d25d1fe8a89aafe2b2b62e3b9aee1a24efa) |
| Ajna v2 | 2026-08-28 | 1/1 | 1/1 | [1](https://etherscan.io/tx/0x12dfde527ef62882bfabb64362c9ae0e6bfb628363bd298d0d0956c9a114e4f5) |
| TrustedVolumes | 2026-05-07 | 1/1 | 1/1 | [1](https://etherscan.io/tx/0xc5c61b3ac39d854773b9dc34bd0cdbc8b5bbf75f18551802a0b5881fcb990513) |
| Ekubo EVM v2 | 2026-05-05 | 1/1 | 1/1 | [1](https://etherscan.io/tx/0x770bc9a1f7c32cb63a5002b9ceb5c7994cd3af0fc6b2309cb32d3c46f629daa0) |
| Aztec V1 escape hatch | 2026-06-17 | 3/3 | 3/3 | [1](https://etherscan.io/tx/0xab306cd2184d23b6ba3e151b10b3b9a0b81f211cc16f4f3b0c79f0b17a59c2b5), [2](https://etherscan.io/tx/0x5c196c37a109d74c9797254287a0331f30e0daa637af241bd28fdc43774705c3), [3](https://etherscan.io/tx/0x9e1d6ab7c20ae235409d7dd3a9cd47c04f07293585b3498b8beed82d6f6b03ca) |
| Token of Power | 2026-06-09 | 1/1 | 1/1 | [1](https://etherscan.io/tx/0x967aa34c69b7775c718545c7f94d92e965eb5fc553c0f27f6f1a9c65c93ac156) |
| Yearn yETH | 2025-11-30 | 1/1 | 1/1 | [1](https://etherscan.io/tx/0x53fe7ef190c34d810c50fb66f0fc65a1ceedc10309cf4b4013d64042a0331156) |
| Balancer V2 | 2025-11-03 | 1/2 | 1/2 | [1](https://etherscan.io/tx/0x6ed07db1a9fe5c0794d44cd36081d6a6df103fab868cdd75d581e3bd23bc9742), [2](https://etherscan.io/tx/0xd155207261712c35fa3d472ed1e51bfcd816e616dd4f517fa5959836f5b48569) |
| Abracadabra | 2025-10-04 | 1/1 | 1/1 | [1](https://etherscan.io/tx/0x842aae91c89a9e5043e64af34f53dc66daf0f033ad8afbf35ef0c93f99a9e5e6) |
| SuperRare | 2025-07-28 | 1/1 | 1/1 | [1](https://etherscan.io/tx/0xd813751bfb98a51912b8394b5856ae4515be6a9c6e5583e06b41d9255ba6e3c1) |
| Silo pre-release leverage contract | 2025-06-25 | 1/1 | 1/1 | [1](https://etherscan.io/tx/0x1f15a193db3f44713d56c4be6679b194f78c2bcdd2ced5b0c7495b7406f5e87a) |
| Cork | 2025-05-28 | 1/1 | 0/1 | [1](https://etherscan.io/tx/0xfd89cdd0be468a564dd525b222b728386d7c6780cf7b2f90d2b54493be09f64d) |
| Bybit Safe | 2025-02-21 | 4/5 | 4/5 | [1](https://etherscan.io/tx/0x46deef0f52e3a983b67abf4714448a41dd7ffd6d32d32da69d62081c68ad7882), [2](https://etherscan.io/tx/0xb61413c495fdad6114a7aa863a00b2e3c28945979a10885b12b30316ea9f072c), [3](https://etherscan.io/tx/0xbcf316f5835362b7f1586215173cc8b294f5499c60c029a3de6318bf25ca7b20), [4](https://etherscan.io/tx/0xa284a1bc4c7e0379c924c73fcea1067068635507254b03ebbbd3f4e222c1fae0), [5](https://etherscan.io/tx/0x847b8403e8a4816a4de1e63db321705cdb6f998fb01ab58f653b863fda988647) |
| vETH/Vista | 2024-11-14 | 3/3 | 3/3 | [1](https://etherscan.io/tx/0x900891b4540cac8443d6802a08a7a0562b5320444aa6d8eed19705ea6fb9710b), [2](https://etherscan.io/tx/0x1ae40f26819da4f10bc7c894a2cc507cdb31c29635d31fa90c8f3f240f0327c0), [3](https://etherscan.io/tx/0x90db330d9e46609c9d3712b60e64e32e3a4a2f31075674a58dd81181122352f8) |
| Onyx DAO | 2024-09-26 | 1/1 | 1/1 | [1](https://etherscan.io/tx/0x46567c731c4f4f7e27c4ce591f0aebdeb2d9ae1038237a0134de7b13e63d8729) |
| Shezmu | 2024-09-20 | 0/1 | 0/1 | [1](https://etherscan.io/tx/0x39328ea4377a8887d3f6ce91b2f4c6b19a851e2fc5163e2f83bbc2fc136d0c71) |
| Penpie | 2024-09-03 | 2/3 | 2/3 | [1](https://etherscan.io/tx/0x56e09abb35ff12271fdb38ff8a23e4d4a7396844426a94c4d3af2e8b7a0a2813), [2](https://etherscan.io/tx/0x7e7f9548f301d3dd863eac94e6190cb742ab6aa9d7730549ff743bf84cbd21d1), [3](https://etherscan.io/tx/0x42b2ec27c732100dd9037c76da415e10329ea41598de453bb0c0c9ea7ce0d8e5) |
| LI.FI | 2024-07-16 | 1/1 | 1/1 | [1](https://etherscan.io/tx/0xd82fe84e63b1aa52e1ce540582ee0895ba4a71ec5e7a632a3faa1aff3e763873) |
| Floor Protocol | 2023-12-17 | 3/3 | 3/3 | [1](https://etherscan.io/tx/0xa329b27fbe0f7b7f92060a9e5370fdf03d60e5c4835f09d7234e5bbecf417ccf), [2](https://etherscan.io/tx/0xec8f6d8e114caf8425736e0a3d5be2f93bbea6c01a50a7eeb3d61d2634927b40), [3](https://etherscan.io/tx/0xfb9942a119c45adab3980639cd829e57b41449e3b82d610892da4bb921e81d9c) |
| GoodDollar | 2023-12-16 | 1/1 | 1/1 | [1](https://etherscan.io/tx/0x726459a46839c915ee2fb3d8de7f986e3c7391c605b7a622112161a84c7384d0) |
| KyberSwap Elastic | 2023-11-22 | 1/1 | 1/1 | [1](https://etherscan.io/tx/0x485e08dc2b6a4b3aeadcb89c3d18a37666dc7d9424961a2091d6b3696792f0f3) |
| Raft | 2023-11-10 | 1/1 | 1/1 | [1](https://etherscan.io/tx/0xfeedbf51b4e2338e38171f6e19501327294ab1907ab44cfd2d7e7336c975ace7) |
| MEV bot 0x05f016…924a5 | 2023-11-07 | 1/1 | 1/1 | [1](https://etherscan.io/tx/0xbc08860cd0a08289c41033bdc84b2bb2b0c54a51ceae59620ed9904384287a38) |
| Orbit Chain | 2023-12-31 | 3/3 | 3/3 | [1](https://etherscan.io/tx/0xe0bada18fdc56dec125c31b1636490f85ba66016318060a066ed7050ff7271f9), [2](https://etherscan.io/tx/0x639d27e564214411ad8eb06cf00d85cd90f83503a53ab5bf35dd5c6e1148ae0a), [3](https://etherscan.io/tx/0x64a6f486c20671e1389b3c7948d46733325c407245a86bf510cb69ef401a3f0e) |
| Rubic | 2022-12-25 | 2/2 | 1/2 | [1](https://etherscan.io/tx/0x9a97d85642f956ad7a6b852cf7bed6f9669e2c2815f3279855acf7f1328e7d46), [2](https://etherscan.io/tx/0x6551b933b984342fd353d4b522aee7db500900e208dc1337b0c1f17647e36e56) |
| ElasticSwap | 2022-12-13 | 1/1 | 1/1 | [1](https://etherscan.io/tx/0xb36486f032a450782d5d2fac118ea90a6d3b08cac3409d949c59b43bcd6dbb8f) |
| DFX | 2022-11-10 | 2/2 | 2/2 | [1](https://etherscan.io/tx/0x390def749b71f516d8bf4329a4cb07bb3568a3627c25e607556621182a17f1f9), [2](https://etherscan.io/tx/0x6bfd9e286e37061ed279e4f139fbc03c8bd707a2cdd15f7260549052cbba79b7) |
| Team Finance | 2022-10-27 | 1/1 | 1/1 | [1](https://etherscan.io/tx/0xb2e3ea72d353da43a2ac9a8f1670fd16463ab370e563b9b5b26119b2601277ce) |
| TempleDAO | 2022-10-11 | 0/1 | 0/1 | [1](https://etherscan.io/tx/0x8c3f442fc6d640a6ff3ea0b12be64f1d4609ea94edd2966f42c01cd9bdcf04b5) |
| Beanstalk | 2022-04-17 | 1/1 | 1/1 | [1](https://etherscan.io/tx/0xcd314668aaa9bbfebaf1a0bd2b6553d01dd58899c508d4729fa7311dc5d33ad7) |
| Value DeFi | 2020-11-14 | 1/1 | 0/1 | [1](https://etherscan.io/tx/0x46a03488247425f845e444b9c10b52ba3c14927c687d38287c0faddc7471150a) |
| Warp Finance | 2020-12-17 | 1/1 | 1/1 | [1](https://etherscan.io/tx/0x8bb8dc5c7c830bac85fa48acad2505e9300a91c3ff239c9517d0cae33b595090) |
| Cheese Bank | 2020-11-06 | 1/1 | 0/1 | [1](https://etherscan.io/tx/0x600a869aa3a259158310a233b815ff67ca41eab8961a49918c2031297a02f1cc) |
| Revest | 2022-03-27 | 1/1 | 1/1 | [1](https://etherscan.io/tx/0xe0b0c2672b760bef4e2851e91c69c8c0ad135c6987bbf1f43f5846d89e691428) |
| Inverse Frontier | 2022-06-16 | 1/1 | 0/1 | [1](https://etherscan.io/tx/0x958236266991bc3fe3b77feaacea120f172c0708ad01c7a715b255f218f9313c) |
| bZx Fulcrum | 2020-02-15 | 0/1 | 1/1 | [1](https://etherscan.io/tx/0xb5c8bd9430b6cc87a0e2fe110ece6bf527fa4f170a4bc8cd032f768fc5219838) |
| bZx oracle manipulation | 2020-02-18 | 1/1 | 1/1 | [1](https://etherscan.io/tx/0x762881b07feb63c436dee38edd4ff1f7a74c33091e534af56c9f7d49b5ecac15) |
| Balancer V1 STA/STONK | 2020-06-28 | 1/2 | 1/2 | [1](https://etherscan.io/tx/0x013be97768b702fe8eccef1a40544d5ecb3c1961ad5f87fee4d16fdc08c78106), [2](https://etherscan.io/tx/0xeb008786a7d230180dbd890c76d6a7735430e836d55729a3ff6e22e254121192) |
| Pickle pDAI | 2020-11-21 | 1/1 | 0/1 | [1](https://etherscan.io/tx/0xe72d4e7ba9b5af0cf2a8cfb1e30fd9f388df0ab3da79790be842bfbed11087b0) |
| Cream yUSD | 2021-10-27 | 1/1 | 1/1 | [1](https://etherscan.io/tx/0x0fe2542079644e107cbf13690eb9c2c65963ccb79089ff96bfaf8dced2331c92) |
| xToken xBNTa/xSNXa | 2021-05-12 | 1/1 | 1/1 | [1](https://etherscan.io/tx/0x7cc7d935d895980cdd905b2a134597fb91004b5d551d6db0fb265e3d9840da22) |
| xToken xSNX | 2021-08-29 | 1/1 | 1/1 | [1](https://etherscan.io/tx/0x924e6a6288587b497f73ddcf6ae3c184f15ab35dfcb85f3074b55266974029ef) |

## Missed attacks

On September 26, four hacks produced no alert. Three were also missed in the research run; bZx Fulcrum scored 0.70 then and 0.67 now.

| Hack | What was missed |
|---|---|
| rsETH Safe module | Caller-controlled delegatecall through an enabled module into a victim Safe. A permitted execution path need not represent the owner's intent. |
| Shezmu | Borrowing against collateral the caller could fabricate. A recorded borrow does not prove sound collateral. |
| TempleDAO | An unprotected migration path created a withdrawable balance without the required prior position. |
| bZx Fulcrum | A near miss: 0.67, against 0.70 when the research run caught it. |

Five hacks missed in the research run were caught on September 26, each after scoring 0.65 to 0.69 before: Cork (crafted market data leading to redemption-asset issuance), Value DeFi (manipulated pool valuation), Cheese Bank (manipulated collateral valuation), Inverse Frontier (manipulated valuation enabling undercollateralized borrowing) and Pickle pDAI (a controller path that gave a malicious jar access to vault assets).

Every missed hack turned on a protocol-specific question: whether a valuation, a collateral position, an issuance, a migration or an authorization was valid. A deployment that knows a protocol's own rules can supply that evidence directly.

Six hacks were partially caught on September 26: Hedgey, Notional, Balancer V2, Bybit, Penpie and Balancer V1. For example, Bybit's initial logic replacement was missed, while four subsequent asset sweeps were caught. Detecting a later transaction does not mean the initial loss could have been prevented.

## Calibration

Broad detection rules caught more attacks but also flagged ordinary borrowing, minting and other activity. Requiring stronger evidence reduced that noise at the cost of some coverage.

| Change | Attack transactions caught | Potential false positives |
|---|---:|---:|
| Initial broad detection | 61/70 | 66 |
| Remove the broad extraction rule | 57/70 | 19 |
| Remove the self-referential-price rule | 56/70 | 10 |
| Require stronger evidence around internal claims | 55/70 | 7 |
| Recognize lending-accounting token issuance | 55/70 | 5 |

The lending change connected a lender's Borrow event with tokens issued to the borrower, reducing alerts that treated those tokens as an unexplained payment. It kept the total at 55 attack transactions, but changed which ones were caught: Yearn yETH was gained and Balancer V2's first transaction was lost.

## Potential false positives

The September 26 run raised seven alerts among the 12,947 other transactions in the calibration blocks. Four were also raised in the research run and were reviewed then; three have not been reviewed yet:

- [Circle CCTP redemption](https://etherscan.io/tx/0x702533f7bef69458e82061d5a6ddafff4bc69e04f8eab627d6a58a9e1e2a34a0), [Alephium redemption](https://etherscan.io/tx/0x60720a5a46a40dd43b1124657e06f87ca0f5d7e0dfeb754f6a01dae7918749eb), [Aave V4 borrowing](https://etherscan.io/tx/0x7aa4993b5ceabfbb679882e05460b4292bf8f50e27878bec56eb9b97d7e29771) and [PYUSD supply increase](https://etherscan.io/tx/0x001b48416f93297ddc8d6d8f74e64173caf9c41656f645a582b38b6f67544d3e): reviewed below.
- Not yet reviewed: [a transaction in the Ajna block](https://etherscan.io/tx/0xf81484e6e439eaa04dff67435128cd8237499716357d8f1999e9603fdb4ea051), [one in the Beanstalk block](https://etherscan.io/tx/0x43125a9f55b568222bfa24219f4427b3c16ab8d83d05b506d27720c5da12f30e) and [one in the Pike block](https://etherscan.io/tx/0xcef5799a52168eb7921a4de38e5b82bb7b4ae460ddecd979a74c8a64171ab894).

In the held-out blocks, one alert was raised, on [a transaction beside the Aave ParaSwap exploit](https://etherscan.io/tx/0x878c2566b25df61cc6d01afa2d977643c27f50cf77996e779d6ee65eefa9056e); it has not been reviewed.

The research run's five alerts were reviewed as follows. The Aave V3 borrowing no longer alerts.

| Transaction | Why it alerted | Follow-up interpretation |
|---|---|---|
| [Circle CCTP redemption](https://etherscan.io/tx/0x702533f7bef69458e82061d5a6ddafff4bc69e04f8eab627d6a58a9e1e2a34a0) | A 2 million USDC mint looked unsupported. | Source burn, message, recipient, and amount matched. Likely ordinary redemption. |
| [Alephium redemption](https://etherscan.io/tx/0x60720a5a46a40dd43b1124657e06f87ca0f5d7e0dfeb754f6a01dae7918749eb) | A 20,000 wrapped-ALPH mint looked unsupported. | Source custody increase and message matched the destination. Likely ordinary redemption. |
| [Aave V4 borrowing](https://etherscan.io/tx/0x7aa4993b5ceabfbb679882e05460b4292bf8f50e27878bec56eb9b97d7e29771) | A 120,000 USDT payout looked uncompensated. | Matching borrowing, debt shares, and later repayment support a loan explanation. Collateral provenance and authorization remain unresolved. |
| [Aave V3 borrowing](https://etherscan.io/tx/0x7dc0bea6bc48ee58dce85e56b5adc753884535e44576422bdaf389688c638736) | A 500,000 USDG payout still looked suspicious despite debt evidence. | Borrowing records and account state support a loan explanation. A healthy-looking account does not prove legitimate collateral provenance. |
| [PYUSD supply increase](https://etherscan.io/tx/0x001b48416f93297ddc8d6d8f74e64173caf9c41656f645a582b38b6f67544d3e) | About 829,162 PYUSD was minted to the caller without an observed payment. | The caller held the supply-controller role; later explorer attribution supports routine issuer activity. Off-chain backing and operator intent remain unverified. |

## Held-out hacks

The detector caught all 10 held-out hacks on September 26 and 7 on September 23. Scores are in parentheses.

| Hack | Date | Sept 26 | Sept 23 | Transaction |
|---|---|---|---|---|
| Meta Pool mpETH | 2025-06-17 | caught (0.72) | missed (0.57) | [1](https://etherscan.io/tx/0x57ee419a001d85085478d04dd2a73daa91175b1d7c11d8a8fb5622c56fd1fa69) |
| Fire Token | 2024-10-01 | caught (0.82) | caught (0.77) | [1](https://etherscan.io/tx/0xd20b3b31a682322eb0698ecd67a6d8a040ccea653ba429ec73e3584fa176ff2b) |
| Aave ParaSwap repay adapter | 2024-08-28 | caught (0.80) | missed (0.64) | [1](https://etherscan.io/tx/0xc27c3ec61c61309c9af35af062a834e0d6914f9352113617400577c0f2b0e9de) |
| Seneca Protocol | 2024-02-28 | caught (0.71) | caught (0.74) | [1](https://etherscan.io/tx/0x23fcf9d4517f7cc39815b09b0a80c023ab2c8196c826c93b4100f2e26b701286) |
| Uwerx | 2023-08-02 | caught (0.85) | caught (0.83) | [1](https://etherscan.io/tx/0x3b19e152943f31fe0830b67315ddc89be9a066dc89174256e17bc8c2d35b5af8) |
| Yearn iEarn yUSDT | 2023-04-13 | caught (0.90) | caught (0.88) | [1](https://etherscan.io/tx/0xd55e43c1602b28d4fd4667ee445d570c8f298f5401cf04e62ec329759ecda95d) |
| Orion Protocol | 2023-02-02 | caught (0.87) | caught (0.88) | [1](https://etherscan.io/tx/0xa6f63fcb6bec8818864d96a5b1bb19e8bd85ee37b2cc916412e720988440b2aa) |
| Origin Dollar OUSD | 2020-11-17 | caught (0.87) | caught (0.88) | [1](https://etherscan.io/tx/0xe1c76241dda7c5fcf1988454c621142495640e708e3f8377982f55f8cf2a8401) |
| Akropolis Delphi savings pools | 2020-11-12 | caught (0.73) | missed (0.58) | [1](https://etherscan.io/tx/0xe1f375a47172b5612d96496a4599247049f07c9a7d518929fbe296b0c281e04d) |
| Harvest Finance USDC vault | 2020-10-26 | caught (0.80) | caught (0.73) | [1](https://etherscan.io/tx/0x35f8d2f572fceaac9288e5d462117850ef2694786992a8c3f6d02612277b0877) |

On September 23 the three misses were Meta Pool (the facts showed a fresh contract minting with flash liquidity, but not the protocol state that made the mint unsupported), the Aave ParaSwap adapter (the borrowing context explained the Aave loan but not the adapter's loss) and Akropolis (DAI went unpriced). Meta Pool and Akropolis crossed the threshold on September 26 with identical fact sheets.

## Live traffic

On September 26, 2026, the `monitor` command followed 80 consecutive finalized blocks (26,064,418 to 26,064,497; 16,888 transactions) and flagged 15 transactions (0.089%, about 1 in 1,100). Their fact sheets suggest five patterns. These are possible benign explanations, not full adjudications of the transactions:

| Pattern | Alerts | Transactions |
|---|---:|---|
| One bot's repeating SKY-wrapper routine: about $9.1 million of a wrapper minted and the same SKY pulled back, with no gain | 7 | [0x688a5ad8](https://etherscan.io/tx/0x688a5ad8f6312f78b80e01ce74676a59e1e213a328e4d9c9d7a263e9ddf92314), [0xdcb3cd99](https://etherscan.io/tx/0xdcb3cd992b406b0265c48e9fd5758e62e45108ce72cccab0c5bcdd748827689a), [0xea996f97](https://etherscan.io/tx/0xea996f978fd7041ce9a87a9867437a80291bc8dccbd4092bf0064838e9cc6c9f), [0x3dd6104f](https://etherscan.io/tx/0x3dd6104fc917aa02b1f2245dec8ba98a273b7bc84c5b49e9e9d67109dc317d19), [0xf4230c62](https://etherscan.io/tx/0xf4230c622cbed48ab9ccad86c123206e68b29490033f7631772d31a4dca60dfa), [0x428d4c52](https://etherscan.io/tx/0x428d4c5247ca6d4067b04f1f6c0c05b068c262670c8f86945c730d208772583c), [0x4273fc73](https://etherscan.io/tx/0x4273fc73010177f503e93851e9f393871388eaf664ef5ff2c2061f652124059b) |
| USDC minted to the caller by a contract that received nothing from it, the shape of a cross-chain USDC redemption | 5 | [0x80bf740e](https://etherscan.io/tx/0x80bf740e9c8e2f9c6344707db7794845f40b26437d57fadb9d360f2ba598d34a), [0x16fa874d](https://etherscan.io/tx/0x16fa874d4a5f9ea57d2abfaaf5f3026843f48ddd6359e7135fdd1f2f4c62f3f4), [0x030a5dab](https://etherscan.io/tx/0x030a5dab1ceb2c61243fe8c02ffc4854bdab53c3545f3214840aa082cd114651), [0x5196e19e](https://etherscan.io/tx/0x5196e19e80c31a2575b893594e9ef924bcce4a2fa02ac85305fb59a38751fb06), [0xe4a9ea3f](https://etherscan.io/tx/0xe4a9ea3f55633fa25f68525026286e720198b8c4ab692afb11b2f797684905fa) |
| A Morpho collateral withdrawal; the fact sheet alone does not verify the user's earlier deposit or entitlement | 1 | [0xc4494b71](https://etherscan.io/tx/0xc4494b71b249fe15ca15798ce25fbfac534899fb6b03aa3b8eb135de598dc530) |
| An operation of Spark's Liquidity Layer by a wallet with over 92,000 transactions | 1 | [0xe44a1feb](https://etherscan.io/tx/0xe44a1feb7d2c802b69f1041b7716c44168fa95b8ba8c0afb43d7ba3d5ae4f656) |
| A bot removing Uniswap liquidity it had added earlier in the same block | 1 | [0x422a7cc9](https://etherscan.io/tx/0x422a7cc9277fec12ec4ef2f09ca2b320a61d30bce995903a6a24ee1ed2f43334) |

All 15 scored between 0.70 and 0.82. Grouping repeated alerts from the same sender and contract would leave nine. Most patterns turn on facts a single transaction does not show, such as an earlier deposit or what a protocol's wrapper is meant to mint, which a protocol-specific deployment can supply. The monitor's full output, with each alert's fact sheet, is in [`evidence/live-2026-09-26.jsonl`](../evidence/live-2026-09-26.jsonl).

## Are alerts concentrated around known hacks?

The 20-block sample had zero alerts in 5,420 transactions, but the later 80 live blocks had 15 in 16,888. Across both samples that were not selected around known hacks, the rate is 15 of 22,308 (0.067%), compared with 6 of 13,969 (0.043%) non-attack-labeled transactions in the latest historical repeat. The observed alerts are therefore not confined to hack-containing blocks.

The zero-alert sample is small for such a rare event. At the original historical rate of 5 in 12,947, a simple independent-trial calculation gives about a 12% chance of zero alerts in 5,420 transactions. That calculation is only a sanity check: transactions cluster by protocol and sender. In the live sample, seven alerts came from one repeated wrapper routine and five resembled bridge redemptions. Different traffic windows need not contain the same mix.

An input review of all eight historical alerts from the first September 26 run found empty prior-sender preparation and recent-contract-change fields in every case. The benchmark's incident name and known-attack label are used for evaluation, not sent to Jev; each transaction is classified in a separate request. Some transaction context is shared through the extractor, so this check is not proof that every cross-transaction effect is absent, but those warning fields do not explain these alerts.

The recorded facts instead show large token issuance, apparently uncompensated transfers, and trading activity, patterns also present in the live alerts. The current evidence favors missing authorization, backing or accounting context and clustered activity over a general effect from merely sharing a block with a hack. It does not establish that every additional alert is benign. Proving a causal explanation would require a matched comparison of the same transactions with and without surrounding context; that experiment has not been run.

## Timing methodology

### Pre-cached processing: 2.7 seconds per block

Five selected hack-containing blocks averaged 2.74 seconds per block across two complete passes, with a median of 2.59 seconds and a range of 2.07–3.65 seconds. Each pass scanned all 829 transactions, caught all five known attacks and flagged the same two additional transactions. The 1,658 classifier requests were fresh, with no answer-cache hits; their combined token cost was $0.1133 at the configured price, excluding RPC and explorer costs.

| Hack | Block | Transactions | First pass | Repeat |
|---|---:|---:|---:|---:|
| Resupply | 22,785,461 | 209 | 2.57 s | 3.65 s |
| Conic | 17,740,955 | 149 | 2.99 s | 2.48 s |
| Pike | 19,771,059 | 146 | 2.48 s | 2.54 s |
| Socket | 19,021,454 | 133 | 2.67 s | 2.60 s |
| Beanstalk | 14,602,790 | 192 | 2.07 s | 3.35 s |

| Stage | Total across both five-block passes | Average per block |
|---|---:|---:|
| Block retrieval and collection overhead | 11.20 s | 1.12 s |
| Validate, extract and assemble facts | 0.53 s | 0.05 s |
| Enrich from the supporting-data cache | 8.96 s | 0.90 s |
| Render and classify with Jev | 6.70 s | 0.67 s |
| Combined processing | 27.39 s | 2.74 s |

The five blocks were selected before timing. An unscored preparation pass filled missing lookups for those blocks only, taking 72.89 seconds in an existing workspace with labels, mixer data and some metadata already cached. This preparation figure is not a cold-start installation time.

During timing, the production pipeline fetched each block's headers, receipts and call traces afresh, rebuilt its facts, and called Jev. Supporting Etherscan, price and historical-state responses came from local disk. The measurement stopped on any supporting-data cache miss: none occurred. Rebuilt records matched the preparation records byte-for-byte by digest. Classifier answers were preserved separately between passes so the repeat made fresh paid requests while retaining the cumulative spending ledger.

The timer excludes cache preparation, index construction, connection setup, finalization wait and output-file writing. This measures the ideal case in which an ongoing service already has all required supporting lookups. It does not demonstrate that a live service can always prefetch data for new addresses before they appear. Both passes and their request counts are in the [measurement record](../evidence/precache-five-blocks.json). These are repeat scans of existing benchmark transactions and do not increase the headline coverage denominator.

### Live processing with cache misses

The saved [80-block live run](../evidence/live-2026-09-26.jsonl) covered 16,888 transactions on an Apple M3 Ultra with an Alchemy endpoint and an Etherscan key paced at three requests per second. These measurements used the monitor's memory and caches, but still included lookups for addresses it had not seen before.

| Measured work | Total across 80 blocks | Average per block |
|---|---:|---:|
| Collect, extract and enrich, measured together | 795.04 s | 9.94 s |
| Render and classify | 50.84 s | 0.64 s |
| Combined processing | 845.88 s | 10.57 s |

Median combined processing was 10.40 seconds; 90% of blocks finished within 16.97 seconds. The run also spent 45 seconds loading recent chain history before block processing. The table excludes startup, index preparation, waiting for finalization and polling. The saved run did not time collection, extraction and enrichment separately, so separate stage averages cannot be recovered from it.

A separate three-block simulation took 3.1, 3.2 and 4.3 seconds with all required explorer answers already cached, while refreshing chain reads and prices. That shows a possible warm-cache speed, not measured sustained live performance. Those three blocks matched the reference explorer path's records. Performance-probe transactions are not added to the published evaluation total.

## Extractor versions

The September 26 figures come from this release, fact extractor version 13. In the research run, the calibration hacks (scored September 22) and the ordinary blocks (September 23) used version 10, and the held-out hacks (September 23) used version 12. Version 12 changed the facts of six calibration transactions, and rescoring them left every figure unchanged.

## Benchmark data

The [September 26 scores](../evidence/historical-v13.jsonl), [research-run scores](../evidence/historical.jsonl), held-out scores for [September 26](../evidence/held-out-v13.jsonl) and [September 23](../evidence/held-out.jsonl), the [same-day repeat](../evidence/historical-v13-repeat.jsonl), and the [detector configuration](../evidence/detector.json) accompany these results. Each September 26 row records the digest of the fact sheet it scored. `jevscan-chainmonitor results` recomputes every figure offline, and `jevscan-chainmonitor benchmark` reruns the benchmark with the current extractor.

# Event archive migration audit

> This report is review-only. It does not modify `gh-pages` or production data.

## Snapshot

- Source revision: `ebabcd313633767126e49370cb1a47622b9e78d8`
- Reviewed through: `2026-09-02`
- Archive fingerprint: `9a7b432021bcb475a0c0c32ab224b399718e32b7668ee5d5953f3409efcf2603`
- Reviewed archive records: 178
- Public legacy threads reviewed: 22
- Plan approval: `approved`
- Resulting events: 152
- Records covered by explicit review: 69
- Conservative singleton defaults: 109

## Review summary

| Legacy URL | Decision | New targets | URL handling | Reason |
|---|---:|---:|---|---|
| `/threads/t0b68bfec21/` | `split_groups` | 2 | `retired_index` | 前四条是 Coinbase 在 Base 推出代币化美股的重复报道；8 月 31 日的行业总市值报道不是该发布事件的进展。 |
| `/threads/t10692996cb/` | `split_all` | 3 | `retired_index` | Sonnet 5、Fable 5、Mythos 5 和 Fable 5.1 是不同模型发布，不能仅因同属 Anthropic/Claude 而合并。 |
| `/threads/t13857e9e03/` | `progression` | 1 | `redirect` | 两条报道指向同一笔 4 亿 FOGO 异常转账和同一次主网停机；第二条增加了停机持续 46 小时的状态变化。 |
| `/threads/t250c9d6a2c/` | `split_all` | 2 | `retired_index` | Kalshi 的具体法院裁决与博彩行业针对预测市场的游说行动是相关但独立的事件。 |
| `/threads/t3000507936/` | `split_all` | 2 | `retired_index` | CFTC 与士兵的 Polymarket 争议和康涅狄格州起诉 Kalshi 涉及不同当事方、诉因和程序。 |
| `/threads/t320d763eee/` | `collapse_duplicates` | 1 | `redirect` | 两条报道复述 Deribit 将客户资产迁往 Coinbase 并停止每日储备证明的同一事实，没有新增进展。 |
| `/threads/t46141326bb/` | `collapse_duplicates` | 1 | `redirect` | 两条报道都已包含 Tectonic 被盗、Cronos 停机和回滚，没有形成两个独立时间节点。 |
| `/threads/t481f08bd31/` | `split_all` | 2 | `retired_index` | 反事实可解释性研究与 AI 对齐安全实践更新是两项独立工作。 |
| `/threads/t4f9d81d5cd/` | `split_all` | 2 | `retired_index` | 银行代币化存款与代币化国债作为加密抵押品不是同一产品、机构或事件。 |
| `/threads/t53fc4330d5/` | `progression` | 1 | `redirect` | 投票前状态与提案正式通过构成同一治理事件的两个真实阶段；三条通过报道折叠为同一更新。 |
| `/threads/t55e85960c2/` | `split_all` | 6 | `retired_index` | 六条记录分别涉及 Hyperliquid、综合政策、融资安全港、比特币永续、托管规则和转让代理规则，只共享监管主题。 |
| `/threads/t66352c3090/` | `progression` | 1 | `redirect` | 这些记录围绕同一个 Cosmos EVM 共享模块漏洞，从单链停机扩展到多链影响，再到责任与影响范围确认。 |
| `/threads/t6bfaf2639f/` | `split_all` | 2 | `retired_index` | 渣打分销港元稳定币与 21 家机构筹划美元稳定币属于不同发行安排。 |
| `/threads/t72b4e44581/` | `split_all` | 2 | `retired_index` | Zilliqa 指控的密钥熵问题与 Ledger 以太坊应用的交易替换漏洞是两起独立安全事件。 |
| `/threads/t747ea63a06/` | `split_groups` | 2 | `retired_index` | Maya Protocol 攻击与比特币抗量子交易无关；后两条是同一笔抗量子主网交易的重复报道。 |
| `/threads/t93b04d9cce/` | `progression` | 1 | `redirect` | 两条记录均围绕 CLARITY Act 的同一立法推进，第二条增加了参议院票数预期和计划日期。 |
| `/threads/t99a010e8f3/` | `collapse_duplicates` | 1 | `redirect` | 四条报道均复述嘉信理财增加 SOL、AVAX 和 LINK 交易支持，没有新的执行阶段。 |
| `/threads/ta1e7eb0d77/` | `split_groups` | 2 | `retired_index` | 两条 Binance Agent OS 报道属于同一产品发布；Coinbase 的 AI 代理支付平台是独立产品。 |
| `/threads/tbc6034e4ae/` | `split_all` | 2 | `retired_index` | Binance 下架 SCRT 与 Secret Network 增发 SCRT 是不同主体作出的不同决定。 |
| `/threads/tbdf211e6dd/` | `progression` | 1 | `redirect` | 该事件应补入旧规则漏掉的提现受限和第二个重组来源，形成重组计划、提现异常、律师与时间表确认三个阶段。 |
| `/threads/te3bc28ddab/` | `split_groups` | 3 | `retired_index` | 旧事件线错误合并了 Term Finance、Moonwell 和 More Markets 三起独立攻击；Term 的停库是实际后续，Moonwell 两条是重复报道。 |
| `/threads/tec8be6673c/` | `split_all` | 3 | `retired_index` | SWIFT 银行间交易、Taurus 接入和数字债券回购是不同参与方完成的三项独立金融基础设施事件。 |

## Detailed decisions

### `t0b68bfec21` — `split_groups`

前四条是 Coinbase 在 Base 推出代币化美股的重复报道；8 月 31 日的行业总市值报道不是该发布事件的进展。

- Event `evt_0655aad2257c6798`: Coinbase 在 Base 推出代币化美股 / Coinbase launches tokenized US stocks on Base
  1. `initial` — Coinbase 在 Base 上线代币化美股，并使用 Chainlink 提供价格数据。 Sources: 2026-08-25 · Coinbase Launches Tokenized Stocks for Nvidia, Apple, Meta, Alphabet on Base | 2026-08-25 · Coinbase launches tokenized US stocks on Base with Chainlink price feeds | 2026-08-25 · Coinbase Launches Tokenized Stocks on Base Network | 2026-08-26 · Coinbase Launches Tokenized US Stocks on Base with Chainlink Price Feeds
- Separate event: 2026-08-31 · Tokenized Stocks Hit $29.5B as Coinbase Joins Base

### `t10692996cb` — `split_all`

Sonnet 5、Fable 5、Mythos 5 和 Fable 5.1 是不同模型发布，不能仅因同属 Anthropic/Claude 而合并。

- Separate event: 2026-08-22 · Anthropic Releases Claude Sonnet 5
- Separate event: 2026-09-02 · Anthropic Unveils Claude Fable 5 and Claude Mythos 5
- Separate event: 2026-09-02 · Anthropic Releases Claude Fable 5.1, Doubling Key Benchmark Score

### `t13857e9e03` — `progression`

两条报道指向同一笔 4 亿 FOGO 异常转账和同一次主网停机；第二条增加了停机持续 46 小时的状态变化。

- Event `evt_338d87d3bef60852`: Fogo 4 亿代币异常转账与主网停机 / Fogo 400M-token incident and mainnet halt
  1. `initial` — 攻击者收到 4 亿 FOGO 后，Fogo 暂停主网。 Sources: 2026-08-30 · Layer 1 blockchain Fogo halts mainnet after attacker receives 400 million FOGO tokens
  2. `confirmation` — Fogo 主网停机已持续 46 小时。 Sources: 2026-09-01 · Fogo Mainnet Halted 46 Hours After 400M FOGO Sent to Attacker

### `t250c9d6a2c` — `split_all`

Kalshi 的具体法院裁决与博彩行业针对预测市场的游说行动是相关但独立的事件。

- Separate event: 2026-08-29 · Court Ruling Deals Legal Blow to Kalshi, Affirming State Powers Over Prediction Markets
- Separate event: 2026-08-31 · Casino Industry Declares 'All-Out War' on Prediction Markets

### `t3000507936` — `split_all`

CFTC 与士兵的 Polymarket 争议和康涅狄格州起诉 Kalshi 涉及不同当事方、诉因和程序。

- Separate event: 2026-08-25 · CFTC and Soldier Spar Over Polymarket Bet Regulation
- Separate event: 2026-08-28 · Connecticut Sues Kalshi in Escalating Prediction Market Legal Fight

### `t320d763eee` — `collapse_duplicates`

两条报道复述 Deribit 将客户资产迁往 Coinbase 并停止每日储备证明的同一事实，没有新增进展。

- Event `evt_0baef65f6c294179`: Deribit 调整托管与储备证明安排 / Deribit changes custody and proof-of-reserves arrangements
  1. `initial` — Deribit 将约 90% 客户资产迁往 Coinbase，并停止每日储备证明。 Sources: 2026-08-30 · Deribit Moves 90% of Client Assets to Coinbase, Drops Daily Proof of Reserves | 2026-08-31 · Deribit moves 90% of client assets to Coinbase, ends daily proof-of-reserves

### `t46141326bb` — `collapse_duplicates`

两条报道都已包含 Tectonic 被盗、Cronos 停机和回滚，没有形成两个独立时间节点。

- Event `evt_7cec54c7d44b7cd5`: Tectonic 遭攻击并触发 Cronos 回滚 / Tectonic exploit triggers Cronos rollback
  1. `initial` — Tectonic 遭窃约 7,500 万美元，Cronos 验证者暂停并回滚链。 Sources: 2026-09-01 · Tectonic Exploit Forces Cronos Halt and Rollback After ~$74M Theft | 2026-09-02 · Cronos validators roll back chain to contain $75M Tectonic exploit

### `t481f08bd31` — `split_all`

反事实可解释性研究与 AI 对齐安全实践更新是两项独立工作。

- Separate event: 2026-08-22 · Anthropic Proposes Counterfactual Experiments to Evaluate LLM Explanations
- Separate event: 2026-09-01 · Anthropic Unveils Enhanced AI Alignment and Security Practices

### `t4f9d81d5cd` — `split_all`

银行代币化存款与代币化国债作为加密抵押品不是同一产品、机构或事件。

- Separate event: 2026-08-27 · Banks build tokenized deposits to stop stablecoins draining loan funding
- Separate event: 2026-09-02 · Tokenized Treasuries as Crypto Collateral Raise Systemic Stakes

### `t53fc4330d5` — `progression`

投票前状态与提案正式通过构成同一治理事件的两个真实阶段；三条通过报道折叠为同一更新。

- Event `evt_89466240c898fb47`: Solana 首次约束性通胀递减治理投票 / Solana's first binding disinflation governance vote
  1. `initial` — Solana 即将举行首次约束性治理投票，议题涉及通胀递减和销毁机制。 Sources: 2026-08-28 · Solana Rallies 44% Ahead of First Binding Governance Vote on Inflation and Burns
  2. `resolution` — 验证者通过提案，将通胀递减率提高至 30%。 Sources: 2026-08-29 · Solana Approves Doubled Disinflation, Slashing SOL Issuance by 2029 | 2026-08-29 · Solana validators approve doubling disinflation to 30% in first binding vote | 2026-08-29 · Kraken Tips Solana's Razor-Thin Inflation Vote

### `t55e85960c2` — `split_all`

六条记录分别涉及 Hyperliquid、综合政策、融资安全港、比特币永续、托管规则和转让代理规则，只共享监管主题。

- Separate event: 2026-08-21 · Trump Says CFTC Working to Bring Hyperliquid to US
- Separate event: 2026-08-22 · Washington Goes All-In on Crypto: Trump, SEC, CFTC Advance New Rules
- Separate event: 2026-08-23 · SEC proposes $75M crypto fundraising path with safe harbor to end securities contract
- Separate event: 2026-08-23 · CFTC Clears Bitcoin Perpetual Futures for US Markets
- Separate event: 2026-08-27 · SEC revives crypto custody rule that previously failed to pass
- Separate event: 2026-09-02 · SEC Proposes Modernizing Transfer Agent Rules to Embrace Blockchain

### `t66352c3090` — `progression`

这些记录围绕同一个 Cosmos EVM 共享模块漏洞，从单链停机扩展到多链影响，再到责任与影响范围确认。

- Event `evt_e76fdfcc6ef4904a`: Cosmos EVM 共享模块漏洞与多链损失 / Cosmos EVM shared-module flaw and multi-chain losses
  1. `initial` — MANTRA 因 Cosmos EVM 模块事件暂停网络。 Sources: 2026-08-22 · MANTRA halts network over Cosmos EVM module incident
  2. `escalation` — Cosmos Labs 要求采用该 EVM 模块的链暂停运行，已确认至少三条网络受损。 Sources: 2026-08-26 · Cosmos Labs Urges EVM Chains to Halt as Shared Bug Drains Three Networks
  3. `aftermath` — 后续调查称漏洞曾被低估数月，影响扩大到六条链，Cosmos Labs 承认判断失误。 Sources: 2026-08-29 · Cosmos misjudged critical EVM bug for 4 months before $6M cross-chain exploit | 2026-08-30 · Cosmos Labs admits fault in clearing bug behind $5.7M six-chain hack | 2026-08-31 · Vulnerability Reported in Six Cosmos EVM Chains

### `t6bfaf2639f` — `split_all`

渣打分销港元稳定币与 21 家机构筹划美元稳定币属于不同发行安排。

- Separate event: 2026-08-25 · Standard Chartered First Bank to Distribute HKD Stablecoin
- Separate event: 2026-09-02 · 21 global banks including BofA, Citi, Goldman plan USD stablecoin

### `t72b4e44581` — `split_all`

Zilliqa 指控的密钥熵问题与 Ledger 以太坊应用的交易替换漏洞是两起独立安全事件。

- Separate event: 2026-08-25 · Zilliqa: Ledger Bug Exposed 6,772 Keys, Enabled 683M ZIL Theft
- Separate event: 2026-08-26 · Ledger Patches Ethereum App Bug That Could Swap Signed Transactions

### `t747ea63a06` — `split_groups`

Maya Protocol 攻击与比特币抗量子交易无关；后两条是同一笔抗量子主网交易的重复报道。

- Event `evt_917f3bdc9fc15588`: 比特币首笔抗量子主网交易 / Bitcoin's first quantum-resistant mainnet transaction
  1. `initial` — 比特币主网挖出首笔抗量子交易。 Sources: 2026-08-28 · Bitcoin Executes First Quantum-Safe Mainnet Transaction; 7M BTC Still Exposed | 2026-08-31 · First Quantum-Resistant Bitcoin Transaction Mined on Mainnet
- Separate event: 2026-08-22 · Maya Protocol Exploit Leaves $11M Pool Damage Unresolved; Attacker Still Holds 20.83 BTC

### `t93b04d9cce` — `progression`

两条记录均围绕 CLARITY Act 的同一立法推进，第二条增加了参议院票数预期和计划日期。

- Event `evt_42bb993a2d68e300`: 美国 CLARITY Act 参议院推进 / US CLARITY Act Senate process
  1. `initial` — 特朗普在与加密行业高管会面时公开支持 CLARITY Act。 Sources: 2026-08-21 · Trump 'bullish' on Clarity Act in Oval Office meeting with crypto CEOs
  2. `confirmation` — Coinbase CEO 预计法案可获得 60 票以上，并给出 9 月 15 日的推进节点。 Sources: 2026-08-22 · Coinbase CEO: CLARITY Act Set to Secure 60+ Senate Votes on Sept. 15

### `t99a010e8f3` — `collapse_duplicates`

四条报道均复述嘉信理财增加 SOL、AVAX 和 LINK 交易支持，没有新的执行阶段。

- Event `evt_785313a9b4e42f05`: 嘉信理财增加 SOL、AVAX 和 LINK 交易支持 / Schwab adds SOL, AVAX and LINK trading
  1. `initial` — 嘉信理财宣布为其加密交易平台增加 SOL、AVAX 和 LINK。 Sources: 2026-08-28 · Charles Schwab to Add Solana, Avalanche, Chainlink to Crypto Platform | 2026-08-29 · Schwab Plans to Add SOL, AVAX, and LINK Trading Across 39.9 Million Accounts | 2026-08-29 · Charles Schwab Expands Crypto Trading to Solana, Avalanche, Chainlink | 2026-08-29 · Schwab Plans to Add SOL, AVAX, LINK Trading Across 39.9M Accounts

### `ta1e7eb0d77` — `split_groups`

两条 Binance Agent OS 报道属于同一产品发布；Coinbase 的 AI 代理支付平台是独立产品。

- Event `evt_4873b155da2f630f`: Binance 发布 Agent OS / Binance launches Agent OS
  1. `initial` — Binance 发布 Agent OS，让 AI 代理在用户授权范围内连接交易和金融服务。 Sources: 2026-08-21 · Binance launches Agent OS, opening crypto trading to AI agents with user-set controls | 2026-09-01 · Binance Launches Agent OS Platform Connecting AI Agents to Financial Services
- Separate event: 2026-08-22 · Coinbase Launches AI Agent Platform for Crypto Payments, COIN Rises 3%

### `tbc6034e4ae` — `split_all`

Binance 下架 SCRT 与 Secret Network 增发 SCRT 是不同主体作出的不同决定。

- Separate event: 2026-08-21 · Binance to Delist ICX, SCRT, and STORJ in September 2026
- Separate event: 2026-08-24 · Secret Network mints 1.079B SCRT, diluting holders by 75% after lead developer exits

### `tbdf211e6dd` — `progression`

该事件应补入旧规则漏掉的提现受限和第二个重组来源，形成重组计划、提现异常、律师与时间表确认三个阶段。

- Event `evt_09f87331a0893067`: BitMart 停运、提现限制与重组进展 / BitMart shutdown, withdrawal restrictions and restructuring
  1. `initial` — BitMart 在此前宣布关闭后，开始考虑部分重启和债权人偿付方案。 Sources: 2026-08-23 · BitMart weighs partial restart and creditor payouts weeks after shutdown announcement
  2. `escalation` — 多种资产的提现被限制，且当时没有官方解释。 Sources: 2026-08-24 · BitMart Blocks Withdrawals for Many Coins, Sparking Security Fears
  3. `confirmation` — BitMart 聘请 White & Case 评估重组，并承诺最迟 9 月 9 日给出路线图。 Sources: 2026-08-25 · BitMart suggests restructuring weeks after closure announcement | 2026-08-25 · BitMart weighs restructuring amid unresolved withdrawals and shutdown

### `te3bc28ddab` — `split_groups`

旧事件线错误合并了 Term Finance、Moonwell 和 More Markets 三起独立攻击；Term 的停库是实际后续，Moonwell 两条是重复报道。

- Event `evt_8e3439db94125c2a`: Term Finance 治理攻击与 Meta Vaults 关闭 / Term Finance governance exploit and Meta Vaults shutdown
  1. `initial` — Term Finance 遭治理攻击，损失约 850 万美元。 Sources: 2026-08-24 · Term Finance loses $8.5M in governance exploit despite safeguards | 2026-08-25 · Ethereum DeFi Protocol Term Finance Hit by Governance Exploit Draining Millions | 2026-08-25 · Ethereum Lending App Term Finance Loses $8.5M in Governance Exploit
  2. `remediation` — Term Finance 在攻击后永久关闭 Meta Vaults。 Sources: 2026-08-26 · Term Finance Permanently Shuts Meta Vaults After $8.5M Exploit
- Event `evt_b970d58089c37786`: Moonwell MAMO 价格操纵攻击 / Moonwell MAMO price-manipulation exploit
  1. `initial` — Moonwell 在 Base 上因 MAMO 价格操纵损失约 870 万美元。 Sources: 2026-08-28 · Moonwell Loses $8.7M to MAMO Price Manipulation on Base | 2026-08-31 · Moonwell Loses $8.7M in MAMO Price Manipulation Attack
- Separate event: 2026-09-01 · More Markets reserve drained of ~$9.3M in WFLOW via E-mode exploit

### `tec8be6673c` — `split_all`

SWIFT 银行间交易、Taurus 接入和数字债券回购是不同参与方完成的三项独立金融基础设施事件。

- Separate event: 2026-08-23 · HSBC and Standard Chartered Complete First Interbank Transaction on SWIFT Ledger
- Separate event: 2026-08-27 · Taurus links digital asset platforms to Swift's blockchain ledger
- Separate event: 2026-08-28 · Virtu, Tradeweb Complete First Onchain Repo Using Marshall Islands Digital Bond


## Approval gate

The owner approved this reviewed plan. Production writes still occur only through the guarded `apply` command in GitHub Actions; the archive fingerprint must match before any file is written.

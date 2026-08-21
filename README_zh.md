<div align="center">
<h1>🛰️ BMTNews</h1>

<p><strong>AI 策划的每日情报简报：加密市场、AI 与政策。</strong></p>

[![License](https://img.shields.io/badge/license-MIT-green.svg?style=for-the-badge&logo=opensourceinitiative&logoColor=white)](LICENSE)
[![Tool uv](https://img.shields.io/badge/Tool-uv-4B275F?style=for-the-badge&logo=uv&logoColor=white)](https://github.com/astral-sh/uv)
[![Website](https://img.shields.io/badge/Website-bmt.news-263238?style=for-the-badge&logo=homepage&logoColor=white)](https://bmt.news/)
[![Daily](https://img.shields.io/github/actions/workflow/status/ohxiyu/bmtnews-standalone/daily-summary.yml?branch=main&label=Daily&style=for-the-badge&logo=date-fns&logoColor=white)](https://bmt.news/)
[![Commit](https://img.shields.io/github/commit-activity/m/ohxiyu/bmtnews-standalone?label=Commit&style=for-the-badge&logo=github&logoColor=white)](https://github.com/ohxiyu/bmtnews-standalone/commits/main)

📡 每天一期，中英双语 · [**在线阅读 →**](https://bmt.news/)

[📖 在线站点](https://bmt.news/) · [📋 配置说明](project-docs/configuration.md) · [🧵 归档与事件线](project-docs/archive-and-threads.md) · [✍️ 编辑层](project-docs/editorial.md) · [English](README.md) · [日本語](README_ja.md)

</div>

## BMTNews 是什么

加密行业的信息量早已超过任何人的阅读能力。BMTNews 持续监听交易所公告频道、
协议发布、监管机构、加密与 AI 媒体，每天早上 **08:30（东八区）出一期排好序的
日报**——通常 7 到 14 条真正重要的内容，每条附带背景、市场影响分析和来源链接。

整个系统跑在 GitHub Actions 和 GitHub Pages 上：**没有服务器、没有数据库、
没有需要维护的常驻服务**。git 就是存储层，所有产物都是静态文件。

## 一期日报是怎么来的

```
每 4 小时采集 ─► 固定 24 小时窗口 ─► AI 评分 ─► 去重 ─► 配额平衡
                                                          │
                    归档 ◄── 发布 ◄── 背景补充 ◄──────────┘
                     │        │
     事件线 · 实体页 · JSON API · 分类订阅 · 周报
```

- **固定窗口**：每期严格覆盖当地时间 08:00→08:00，不重不漏
- **评分而非堆量**：每条 0-10 分，有校准锚点，达标才发
- **两道去重**：先合并相同链接，再由 AI 合并「同一事件、不同媒体」，
  并记录有几家媒体报道过
- **配额平衡**：分类和来源都有上限，单一交易所或媒体刷不了屏
- **绝不空刊**：无内容达标时，改发标注为「低信号日」的精选短刊

## 功能

- **📡 冗余化的信息源** — 交易所 Telegram 公告、协议 GitHub 发布、监管机构
  （SEC / CFTC / 美联储）、加密媒体、AI 实验室、Hacker News、GDELT、Google News
- **📄 全文阅读** — 主力信息源抓取全文，而不是只读 RSS 摘要
- **🧵 事件线** — 跨天串联持续事件，事故与后续读起来是一条时间线
- **🏷️ 实体页** — 按公司、协议、监管机构聚合全部历史报道
- **🔍 背景与市场影响** — 每条附带经检索的背景，以及影响传导路径分析
  （只做分析，不构成投资建议）
- **✍️ 编辑层** — 表单化后台插入自定义新闻、投放带标识的广告位、压掉误判内容
- **🌐 中英双语** — 同一套源产出两种语言
- **🔌 机器可读** — 每期 `edition.json`、`latest.json`、分类 Atom 订阅
- **📬 多渠道分发** — 站点、Telegram、邮件、Webhook，以及按高峰时段分时投放的 X

## 快速开始

```bash
# 1. 安装（推荐 uv）
uv sync --extra trafilatura

# 2. 配置
cp data/config.example.json data/config.json
cp .env.example .env          # 填入 AI 服务商 API Key
uv run bmtnews-wizard         # 或直接编辑 data/config.json

# 3. 出一期
uv run bmtnews --mode publish --hours 24 --cutoff-hour 8
```

其他模式：

| 命令 | 作用 |
|---|---|
| `uv run bmtnews --mode fetch` | 只采集进暂存缓存，不调用 AI |
| `uv run bmtnews --mode publish` | 构建并发布一期固定窗口日报 |
| `uv run bmtnews --mode weekly` | 从归档生成周报 |
| `uv run bmtnews --mode x-post` | 发布分时队列中的下一条 X 内容 |
| `uv run bmtnews-mcp` | 以 MCP 方式提供管线与归档查询 |

完整配置见 [project-docs/configuration.md](project-docs/configuration.md)。

## 自动化

| Workflow | 时间 | 用途 |
|---|---|---|
| `feed-collection` | 每约 4 小时 | 采集信息源到暂存缓存 |
| `daily-summary` | 08:30（东八区） | 构建并发布日报 |
| `weekly-review` | 周一 09:30 | 周报与评分校准复盘 |
| `x-distribution` | 每天 4 次 | 按高峰时段分时投放 X |
| `editorial-rebuild` | 编辑触发 | 编辑层改动后自动重刊 |

## 文档

- [配置说明](project-docs/configuration.md)
- [归档、事件线、实体与 JSON API](project-docs/archive-and-threads.md)
- [编辑层与网页后台](project-docs/editorial.md)
- [X 分发](project-docs/x-distribution.md)
- [信息源](project-docs/scrapers.md) · [评分](project-docs/scoring.md) · [正文抽取](project-docs/extractors.md)

## 参与

欢迎推荐信息源和提交 PR，见 [CONTRIBUTING.md](CONTRIBUTING.md)。
安全问题请见 [SECURITY.md](SECURITY.md)。

## 许可

BMTNews 源代码采用 MIT 许可，见 [LICENSE](LICENSE)。生成的日报和第三方
新闻材料不属于软件许可范围，详见[内容与数据权利说明](CONTENT-LICENSE.md)和
[第三方声明](THIRD_PARTY_NOTICES.md)。

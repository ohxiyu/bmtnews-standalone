# 归档层、事件线与对外接口

日报从"每天一次性消费品"变成"可持续累积的情报资产"，靠的是一个跨天归档层。
所有派生内容（事件线、实体页、周报、JSON API、分类订阅）都从它生成，
不引入任何服务器或数据库——归档文件随站点一起发布到 `gh-pages`。

## 数据流

```
每日出刊
   └── docs/_data/archive/YYYY-MM.jsonl   每条展示新闻一行
          ├── 事件线   docs/threads/<id>.html
          ├── 实体页   docs/entity/<slug>.html
          ├── JSON API docs/editions/<date>/edition.json + docs/api/latest.json
          ├── 分类订阅 docs/feeds/<category>-<lang>.xml
          └── 周报     docs/weekly/<date>.md（每周一单独任务）
```

发布前 workflow 从 `gh-pages` 恢复 `_data/archive/`，出刊后重新写回，
和已有的 `bmtnews_state.json` 是同一套「git 即数据库」模式。
本地运行产生的这些文件都在 `.gitignore` 里，不会误提交到 `main`。

## 事件线（Story Threads）

跨天追踪同一事件：Bybit 被盗 → Bybit 起诉朝鲜，会归到同一条事件线，
页面上显示「事件线 · 第 N 天」并链到时间线页面。

匹配**完全离线、无额外 AI 调用**。参与比较的有三种信号：

| 信号 | 来源 |
|---|---|
| **主体（anchor）** | 标题和摘要里的专有名词：英文大写词与缩写、中文里的拉丁品牌名 |
| **标签** | `ai_tags` 归一化后的 slug |
| **上下文** | 标题**和摘要**的分词（英文按词、中文按二元字组） |

满足以下任一条即判为同一事件：

- 共享 ≥2 个主体，且共享上下文 ≥2 个词
- 共享 ≥1 个主体，且共享上下文 ≥6 个词
- 共享 ≥2 个标签，且词重合度 ≥0.30
- 词重合度 ≥0.55

几个关键约束，都是踩过的坑：

- **摘要必须参与比较**。只比标题时，第二天的报道换一套措辞，两条之间
  除了公司名以外几乎没有交集，重合度类的规则一次都不会触发——
  「Bybit 被盗 → Bybit 起诉」就是这么漏掉的
- **共享主体至少要有一个出现在双方标题里**。只在正文里被顺带提一句的
  名字（「……和 Hyperliquid 一样」）不代表这条新闻是关于它的
- **上下文按「稀有词」计数**。中文切成二元字组后，两条毫无关系的加密
  新闻也稳定共享十几个「美元 / 代币 / 协议」这种词。因此每次匹配前先用
  语料统计出现在 >25% 文档里的词并剔除，而不是手工维护中英双语停用词表
- **英文标题会被识别为 Title Case 并跳过**。`Bybit Wins US Court Order`
  里每个词都大写，大小写在这里不携带任何信息，主体从句式正常的摘要里取
- 超过 14 天没有新进展的事件线不再接续，避免旧新闻被复活
- 阈值整体偏保守：漏判只是少一个角标，误判会把无关新闻并到一起
- 事件线 ID 由首条新闻 URL 的哈希决定，稳定且不会碰撞
- 只有跨 ≥2 天的事件线才会生成页面并显示角标

## 实体页（Entities）

从 `ai_tags` 提取重复出现的公司、协议、监管机构，累计 ≥2 次的实体生成
聚合页。这也是站点主要的 SEO 入口：没人搜"8 月 9 日日报"，
但有人搜某个实体的历史脉络。

**一个标签只有在标题真的点了名的时候才算实体。** 模型给出的标签里既有
`coldcard`、`bybit` 这种主体，也有 `exploits`、`market-shakeout` 这种
描述词；不加这一条，实体索引会退化回一堆标签。中文命名的实体
（`美联储`）没有拉丁形式可比对，改为直接在中文标题里查子串。

索引页不是标签云：每张卡片带最新一条标题、累计条数、跨越天数、最近报道
日期和最高评分，并按「近 7 天是否仍在更新」排序——还在发展的主体排在
只剩历史记录的前面。

标签由 AI 生成，会进入页面 `<title>`，因此在入库时就剥离标记字符
（`clean_label`），而不依赖下游每个渲染点各自转义；同时把 `lazarus-group`
这样的 slug 还原成 `Lazarus Group` 再展示。

## 对外接口

| 路径 | 内容 |
|------|------|
| `/api/latest.json` | 最新一期完整数据 |
| `/editions/<date>/edition.json` | 指定某期 |
| `/api/editions.json` | 可用刊期索引 |
| `/feeds/crypto-zh.xml` 等 | 分类 Atom 订阅（crypto / technology / policy × zh / en） |

`edition.json` 含每条新闻的双语标题摘要、评分、分类、来源、标签、
多源确认数、事件线链接，以及当期行情快照和导语。

## 周报与评分校准

`uv run bmtnews --mode weekly`（每周一 09:13 东八区自动触发，也可手动 dispatch）：

- **周报**：从归档取过去 7 天，AI 按「本周主线 / 持续追踪 / 值得记住」
  三段成文，发布到 `/weekly/<date>/`
- **评分校准复盘**：把上周高分和低分新闻与"后来是否发展成多天事件线"
  对照，产出评分偏差分析和 2-4 条可执行的调整建议，写入
  `docs/_data/calibration/<date>.md`（不对外链接，供你调 prompt 参考）

校准复盘是**建议性**的：它不会自动改评分规则，改不改由你决定。

### 散文类调用必须显式要求 text

周报、评分校准、日报导语、X 文案这四处产出的是散文，不是 JSON。
它们调用 `ai_client.complete(...)` 时**必须传 `response_format="text"`**：

供应商的 JSON 模式在散文 prompt 上有两种失败方式，而且都不明显——

- prompt 里没有 "json" 这个词 → 直接 **400 拒绝**
  （`Prompt must contain the word 'json' in some form to use 'response_format'`）
- prompt 里碰巧有这个词（比如导语 prompt 写了「不要返回 JSON」）→ 请求通过，
  但模型被**强制**包成 JSON，`{"lede": "..."}` 就这样上了页面

这两种症状看起来毫无关系，根因是同一个。`tests/test_weekly_and_x.py` 里有一条
断言直接盯住这四个调用点，新增散文类调用时会被它拦住。

## 多源确认

同一条新闻被多个来源报道时，跨源去重会记录 `merged_sources`，
页面来源行显示「N 源确认」（绿色）或「单一来源」，给读者一个
可信度信号。数据本来就有，只是以前没展示。

## X（Twitter）自动分发

**默认关闭，且双重开关**：`data/config.github.json` 里
`x_delivery.enabled` 必须为 `true`，**并且**四个 OAuth 1.0a 密钥
（`X_CONSUMER_KEY` / `X_CONSUMER_SECRET` / `X_ACCESS_TOKEN` /
`X_ACCESS_SECRET`）都要配置到仓库 secrets。缺任何一项都只会在 run report
里记一条 skip，不会发帖。

开启后每期发一条推：标题 + 前 3 条新闻 + 回链，字数按 X 的计数规则
（URL 固定占 23 字符）裁剪。失败只记录 HTTP 状态码，不回显响应体。

## MCP 历史查询

MCP server 新增只读工具，可以直接问历史问题：

- `bmt_search_archive(query, since, until, category, min_score, limit)`
- `bmt_get_thread(thread_id)` / `bmt_list_threads(days, limit)`
- `bmt_get_entity(name, limit)` / `bmt_list_entities(days, limit)`

这些工具只读归档，不抓取、不调用 AI、不写任何文件。

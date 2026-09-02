# 归档层、事件线与对外接口

日报从"每天一次性消费品"变成"可持续累积的情报资产"，靠的是一个跨天归档层。
所有派生内容（事件线、实体页、周报、JSON API、分类订阅）都从它生成，
不引入任何服务器或数据库——归档文件随站点一起发布到 `gh-pages`。

## 数据流

```
每日出刊
   └── docs/_data/archive/YYYY-MM.jsonl   每条展示新闻一行
          ├── 事件目录 docs/_data/events.json
          ├── 事件页面 docs/events/<event_id>.html
          ├── 旧链接   docs/threads/<legacy_id>.html
          ├── 实体页   docs/entity/<slug>.html
          ├── JSON API docs/editions/<date>/edition.json + docs/api/latest.json
          ├── 分类订阅 docs/feeds/<category>-<lang>.xml
          └── 周报     docs/weekly/<date>.md（每周一单独任务）
```

发布前 workflow 从 `gh-pages` 恢复 `_data/archive/`，出刊后重新写回，
和已有的 `bmtnews_state.json` 是同一套「git 即数据库」模式。
本地运行产生的这些文件都在 `.gitignore` 里，不会误提交到 `main`。

## Event Timeline v2 迁移状态

截至 2026-09-02 的生产归档已经逐条审计。迁移计划以完整归档指纹为写入
前置条件：标题、摘要、标签、来源、分类、评分或旧事件线关系发生变化时，
迁移会在写文件前停止。历史记录新增 `event_id` 与 `event_update_id`，同一事实
的多来源报道折叠进一个更新节点，只有真实的新事实才增加时间线节点。

旧 `/threads/<id>/` 不会直接消失。一对一迁移的旧链接跳转到稳定的
`/events/<event_id>/`；发生拆分的旧链接保留为说明页，列出所有修正后的事件，
避免旧收藏、搜索结果或外部引用落入 404。事件时间标记为 `edition` 精度，明确
表示历史数据只知道刊期日期，不把日报边界伪装成真实发生时刻。

PR 3 已把事件目录接入日内采集：事件页会在四小时任务完成后独立发布，日报仍维持
08:00→08:00 的固定刊期，不会因为事件页提前更新而改变排行或出刊边界。

## 事件线（Story Threads）

每次日内采集只分析新 URL；同一输入的评分直接读取 `analysis-cache.json`，不会在
日报阶段再次消耗模型。达到展示阈值的条目先用硬标识、明确主体或至少两个具体主题
检索少量候选事件，通用的 `crypto`、`security`、`regulation` 等标签不能单独打开
候选门。只有候选对才调用事件关系分类器。

分类结果分为 `same_event_update`、`duplicate_coverage`、
`related_but_distinct` 和 `unrelated`。前两类只有在置信度 `>= 0.90` 且不存在近似
并列候选时才自动附着；低置信度和歧义项保留为独立事件。重复报道必须指向已有的
确切 `update_id`，只增加 `story_ids` 与来源依据，不增加实质进展数。

事件索引只展示至少有两次实质进展的事件，并按最近变化排序。详情页固定显示稳定
标题、当前状态、首次追踪、最近变化、来源数，以及从旧到新的时间线；`correction`
使用独立样式，历史迁移节点标为「历史刊期」，新节点则保留实际报道时间。

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
| `/api/events.json` | 至少有两次实质进展的事件索引 |
| `/api/events/<event_id>.json` | 单个事件的完整双语时间线和来源依据 |
| `/feeds/crypto-zh.xml` 等 | 分类 Atom 订阅（crypto / technology / policy × zh / en） |

`edition.json` 含每条新闻的双语标题摘要、评分、分类、来源、标签、
多源确认数、精确 `event_id` / `update_id` 链接，以及当期行情快照和纯文本版「今日脉络」。网页还会把
今日脉络渲染为一句主线和 1-3 条可跳转到对应排行的关键信号。

## 周报与评分校准

`uv run bmtnews --mode weekly`（每周一 09:13 东八区自动触发，也可手动 dispatch）：

- **周报**：从归档取过去 7 天，AI 按「本周主线 / 持续追踪 / 值得记住」
  三段成文，发布到 `/weekly/<date>/`
- **评分校准复盘**：把上周高分和低分新闻与"后来是否发展成多天事件线"
  对照，产出评分偏差分析和 2-4 条可执行的调整建议，写入
  `docs/_data/calibration/<date>.md`（不对外链接，供你调 prompt 参考）

校准复盘是**建议性**的：它不会自动改评分规则，改不改由你决定。

### AI 输出模式必须和提示结构一致

周报、评分校准和 X 文案产出的是散文，调用
`ai_client.complete(...)` 时**必须传 `response_format="text"`**。
首页「今日脉络」则返回 `headline + signals + item_rank` 的结构化对象，必须使用
`response_format="json"`；页面只接受存在的新闻序号，并在异常时回退为纯文本主线。

供应商的 JSON 模式在散文 prompt 上有两种失败方式，而且都不明显——

- prompt 里没有 "json" 这个词 → 直接 **400 拒绝**
  （`Prompt must contain the word 'json' in some form to use 'response_format'`）
- 散文 prompt 里碰巧有这个词 → 请求通过，但模型被**强制**包成 JSON，
  包装对象可能直接进入页面

这两种症状看起来毫无关系，根因是同一个。`tests/test_weekly_and_x.py` 里有一条
断言同时盯住散文和结构化调用，避免两种模式再次混用。

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

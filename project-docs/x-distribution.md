# X（Twitter）分发

两种模式，都默认关闭，且都需要四个 OAuth 1.0a 密钥齐全才会真正发帖。

## 模式对比

| | `digest` | `drip`（当前配置） |
|---|---|---|
| 时机 | 日报发布完成后 | 日报发布后立即发 top1，隔 3–6 小时发 top2 |
| 内容 | 一条推，含前 3 条标题 + 站点链接 | 每条推一个故事，AI 按账号口吻成文 |
| 条数 | 每天 1 条（每语言） | 每天 2 条（`drip_items`） |
| 执行者 | 日报 workflow 尾部 | 日报触发 + 独立的 `x-distribution` workflow |

## 先计划、后发送（drip）

代码在 `src/x_queue.py`，状态在独立的 `x-queue` 分支（`data/x-queue.json`，v2）。

**计划**：当天日报第一次被看到时，一次性选出当天要发的故事、写好正文、定好时间，
全部落盘后才开始发送。

- 故事用规范 URL 的 sha256（`story_key`）标识，不用排名。重排、删条都不会把
  已发的故事换成别的
- 过去 7 天内已发（或结果未知、已失败、人工作废）的故事不会再选，顺延到下一名
- 日报重发（`updated_at` 变化）只会重写**还没尝试过**的任务，保留原时间表，
  detail 记 `replanned`；已尝试的任务是历史，不改

**时间表**：

- top1：日报发布即到期
- top2：top1 **实际发送时间**之后随机 180–360 分钟（按日期+语言+序号做种子，
  重算结果不变）。top1 过期或被跳过时，以它的到期时间为基准
- 每条的截止时间 = min(到期 + 6 小时, 当天 23:30)，过了截止还没发就 `expired`，不补发
- 日报首次发布晚于 07:26 + 6 小时（即 13:26）时，整期标记 `skipped_late`，
  当天 X 不发任何内容，网站照常
- 只推当天（东八区）的日报；过了零点，前一天没发完的直接作废

**发送**：每次运行最多发一条。

1. 先把任务改成 `pending` 并 **push 到 `x-queue` 分支**（普通 push，不 force）。
   push 失败则本次运行报错退出，**不发请求**
2. 发送持久化的原文（发前校验 `text_sha256`）
3. 按 X 的返回归类，再 push 一次：

| 结果 | 状态 | 后续 |
|---|---|---|
| 2xx 且拿到推文 id | `sent` | 记录 `tweet_id` |
| 连接没建立（ConnectError/ConnectTimeout） | 回到 `planned` | 截止前下次运行用同一正文重试 |
| 429 | 回到 `planned` | 同上 |
| 401 / 403 / 其他 4xx | `failed` | 该语言当天停止推送，运行变红 |
| 超时、5xx、2xx 但无 id | `unknown` | **永不自动重发**，运行变红 |
| 运行在 `pending` 后中断 | 下次运行改成 `unknown` | 同上 |

top1 是 `unknown` 时 top2 照常按计划发（以 top1 的尝试时间为基准）。

## 需要人工处理时

只要队列里有 `pending`/`unknown`/`failed`，每次 X workflow 都会在最后一步变红，
提醒有人看账号。处理方法：

1. 登录 X 账号，确认那条推文到底发没发
2. 在 `x-queue` 分支编辑 `data/x-queue.json`，找到对应任务：
   - 实际已发 → `"status": "sent"`，并填上 `"tweet_id"`
   - 实际没发、也不想补 → `"status": "void"`
   - 实际没发、想在截止前补发 → `"status": "planned"`（`failed` 的任务先修好凭证）
3. 直接提交到 `x-queue` 分支（不要 force push）

`void`/`sent` 的故事 7 天内都不会再选。超过 7 天的记录会被自动清掉。

## 定时与门控

`x-distribution.yml` 每 20 分钟轮询一次（东八区 07:07–23:47，
cron `7-59/20 23,0-15 * * *`，避开整点）。每次先用系统 Python 跑
`python3 -m src.x_queue` 这个只依赖标准库的门控：只有新日报/日报重发、有任务到期、
有截止时间已过、或有中断的 `pending` 时才安装依赖并执行，否则几秒内结束。

队列恢复是 fail-closed 的：`git ls-remote` 失败（网络/权限）直接报错，
绝不会当成空队列从头发。队列文件解析失败同样拒绝执行。

日报在 Pages 部署成功后会触发一次该 workflow（`kickoff_only` 参数只为兼容保留，
与普通运行完全相同），所以 top1 通常在发布后一两分钟内发出。触发失败只记 warning，
不会让日报变红，20 分钟内的轮询会接上。

## 文案生成

`compose: "ai"`（默认）时，每条推由 AI 按账号口吻单独成文，在**计划阶段**写好。
写的是**紧凑信息推**：读者看完能掌握完整事件，但不展开非必要背景。

- **90-150 汉字**，严格 2 段，段间空一行
- 第一段只能有一句话：用一句事件摘要交代材料中已有的时间、地点或场合、
  人物或机构、事件和当前结果；材料缺失的要素直接省略，不能推测补全
- 第二段用 1-2 句话补关键数字、机制、因果或后续状态，不重复第一段
- **不带链接、不带话题标签、不提媒体来源**（事件当事人姓名照常写）
- 不提问、不求转发、不喊单、不预测价格

**素材只用已发布字段**：标题、详细摘要、背景、市场影响、社区讨论——即读者在
日报页上能看到的内容。原文正文不再喂给模型，避免推文里出现页面上没有的说法。

**数字校验**：AI 正文里的每个数字、金额、百分比都必须能在上述字段里找到
（允许换单位和四舍五入，如 1.46 billion → 14.6 亿 / 15 亿；日期和个位数计数不查）。
对不上就回落到模板，`fallback_reason` 记 `unsupported_figures`。

生成失败或产出不合格（太短、超长、清理后为空）时同样回落到模板拼装
（标题 + 一句摘要），`fallback_reason` 记 `compose_failed`，run report 记
`x_compose_fallback`。

`compose: "template"` 则完全不调用 AI。

字数按 X 官方规则计（`twitter-text` v3）：**中文每字计 2**，拉丁字符计 1，
URL 一律按 23 计。`max_post_chars` 是加权上限，默认 400，标准账号请改成 280 ——
超过标准账号上限时应同时把 `compose` 改成 `template`。产出低于 **150 加权单位**
会被判为生成失败并回落到模板。

## 配置

```json
"x_delivery": {
  "enabled": true,
  "mode": "drip",
  "drip_items": 2,
  "drip_gap_min_minutes": 180,
  "drip_gap_max_minutes": 360,
  "expected_publish_time": "07:26",
  "max_publish_delay_minutes": 360,
  "expire_after_minutes": 360,
  "window_end": "23:30",
  "link_target": "none",
  "compose": "ai",
  "max_post_chars": 400,
  "languages": ["zh"],
  "site_url": "https://bmt.news/",
  "max_items": 3
}
```

- `drip_items`：一天发几条（1-8），默认 2
- `drip_gap_min_minutes` / `drip_gap_max_minutes`：相邻两条的随机间隔
- `expected_publish_time` + `max_publish_delay_minutes`：晚于这个时间才发布的日报整期不推
- `expire_after_minutes` / `window_end`：单条的截止规则（东八区，`filtering.daily_timezone`）
- `history_days`：去重与保留天数，默认 7
- `link_target`：`none`（默认，不带链接）、`site` 链回日报页、`source` 直接链原文
- `languages`：每种语言独立计划与发送——**不建议**加 `"en"`，容易被判定刷屏
- `max_items`：只在 `digest` 模式下生效

## 启用步骤

1. X Developer Portal 建 App，权限选 **Read and Write**，生成四个凭证
2. 仓库 Secrets 添加 `X_CONSUMER_KEY`、`X_CONSUMER_SECRET`、
   `X_ACCESS_TOKEN`、`X_ACCESS_SECRET`
3. 把 `data/config.github.json` 的 `x_delivery.enabled` 改为 `true`

凭证缺失时任务保持 `planned`，只在 run report 记一条 skip，不会发帖，也不会产生未知状态。

## 手动运行

Actions 里手动运行 `BMTNews X Distribution` 和定时运行完全相同：只会发已到期的
任务，不会多发。`edition_date` 只能是今天，其他日期只记一条提示。

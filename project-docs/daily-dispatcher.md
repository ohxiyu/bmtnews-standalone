# BMTNews 08:30 日报调度

## 目标与时间边界

BMTNews 每天生成一期早间日报，业务时区固定为 `Asia/Shanghai`。日报的数据窗口为 `[前一天 08:00，当天 08:00)`，08:00 截止，08:30 开始生成；`edition_date` 等于窗口结束日，例如 `2026-07-31` 代表 `[2026-07-30 08:00, 2026-07-31 08:00)`。

发布工作流不再依赖 GitHub `schedule` 作为主触发源，而是只接受带明确 `edition_date` 的 `workflow_dispatch`。这样即使补跑发生在数小时之后，任务仍会生成原定期号，不会因“当前时间”变化而错误跨期。

## 多路调度与恢复链路

| 上海时间 | 调度源 | 行为 |
| --- | --- | --- |
| 08:30 | Cloudflare Cron | 主触发；当期未发布且没有运行中任务时，触发日报。 |
| 08:37 | GitHub Feed Collection | 独立采集并在任务结束后调用共享刊期检查接口。 |
| 08:40–11:50 | Cloudflare Cron | 每 10 分钟检查；缺失时按共享锁、冷却期和重试预算补发。 |
| 08:47 | GitHub Actions | 独立备用 Watchdog；Cloudflare 主链路失效时补触发。 |
| 09:17–15:17 | GitHub Actions | Watchdog 每小时复查，恢复被 GitHub 延迟或丢弃的早期事件。 |
| 12:00–23:00 | Cloudflare Cron | 每小时整点检查；上午漏触发后继续自动恢复。 |

Cloudflare 每天共 33 次检查，08:30 前和 23:00 后不安排新的 Cron 检查。正常检查仅读取发布状态和页面，不调用 AI；增加检查频率不会增加每期的自动派发上限。仅使用现有 Cloudflare 和 GitHub，不接入 cron-job.org 等第三方定时服务，也不新增通知通道。

Cloudflare Worker 同时验证生成物和实际生产页面：`gh-pages/api/latest.json` 的刊期与非空条目、中英文 Markdown、生产 `/api/latest.json` 的刊期和条目数、首页第一天的日期及文章数量，以及中英文详情页的日期和文章数量。探测使用独立查询参数避免命中旧缓存；不是 HTTP 200 或 GitHub 成功记录就算发布完成。

所有自动入口（Cloudflare Cron、GitHub Watchdog、Feed Collection 恢复检查）共用按刊期命名的 Durable Object 锁。每次检查持有最长 2 分钟的租约；日报最多尝试 3 次、Pages 最多尝试 2 次，两类操作各有 30 分钟冷却期。派发前先持久化预算，即使请求超时也不立即重试，避免响应丢失造成重复派发。任何 main 日报任务处于队列或运行中都不再提交；持续超过 45 分钟报卡住，不自动取消人工或生产任务。

内容已生成但生产页面未确认时，先留出 15 分钟部署时间，再调用仅绑定 `gh-pages` 的 Pages Deploy Hook，不重跑 AI。两次重建后仍未恢复转人工处理。空日报、上游 5xx、无效 JSON 或认证失败不会被当作成功；探测故障不会绕过共享锁直接补发。手动发布仍是显式人工入口，不受自动恢复次数限制，正常的发布工作流并发控制继续保留。

GitHub 官方说明 `schedule` 事件在高负载时可能延迟或被丢弃。因此不能把同一个 Watchdog 的多个 cron 当作完全独立的冗余。`feed-collection` 在 08:37 增加了另一条调度事件，并在采集任务完成或失败后都运行心跳检查；其他日内采集任务完成后也会复查。最终日报仍会执行一次 24 小时补采，因此暂存采集失败不会阻止日报生成。

## 首次切换

从旧的 20:00 截止切换到 08:00 截止时，第一期新窗口会与最后一期旧窗口重叠 12 小时。发布状态保留最近两天的已发布 URL，重叠内容会在 AI 分析前被剔除，因此实际新增内容自然形成 `[最后一次 20:00 截止，下一次 08:00 截止)` 的 12 小时桥接；不要为首次切换启用 `force_publish`。

## Cloudflare 部署

Worker 位于 `ops/daily-dispatcher/`。生产部署前需要一个仅限 `ohxiyu/bmtnews-standalone` 仓库的 GitHub fine-grained personal access token，Repository permissions 只授予 `Actions: Read and write`；令牌只写入 Cloudflare Secret，不进入 Git、Wrangler 配置或日志。

```bash
cd ops/daily-dispatcher
npm ci
npx wrangler login
npx wrangler secret put GITHUB_DISPATCH_TOKEN
npx wrangler secret put RECOVERY_CHECK_TOKEN
npx wrangler secret put PAGES_DEPLOY_HOOK
npm run check
npx wrangler deploy
```

`wrangler.jsonc` 通过 `secrets.required` 强制校验令牌，缺少 Secret 时生产部署会失败。Cloudflare Cron 使用 UTC，四组表达式为 `30 0 * * *`、`40,50 0 * * *`、`*/10 1-3 * * *`、`0 4-15 * * *`，分别对应上海时间 08:30、08:40/08:50、09:00–11:50 每 10 分钟、12:00–23:00 每小时。修改后读取生产 schedules API 核对，并验证实际 Cron 记录；`/health` 只反映代码声明，不证明调度已经触发。配置传播期间继续兼容旧 Cron 事件。

Worker 当前没有仓库内的自动部署流程。修改或合并 `ops/daily-dispatcher/` 后，必须执行上述部署命令并验证 `/ready`；只合并代码不会更新生产 Worker。若 `/ready` 失败，先修复 Cloudflare Secret 中的 GitHub fine-grained token，再等待下一次 Cron。

## 验证与排障

1. 访问 Worker 的 `/health`，确认静态配置返回 `status: ok`；再访问 `/ready`，确认返回 `dispatch_permission: actions:write`。`/ready` 会用一个不可能成立的 Git ref 调用 dispatch API：具有 Actions 写权限时 GitHub 在 ref 校验阶段返回 422，Worker 据此确认权限，但不会创建 workflow run。两个端点都不允许通过 HTTP 触发日报。
2. 在 08:30 后检查 Cloudflare Workers Logs 的 `publication_check` 事件，字段包含 `edition_date`、`status`、`raw_ready`、`public_ready`、`items`、`overdue` 和可选的 `active_run_url`。
3. 在 GitHub Actions 中确认日报运行名包含明确期号和来源，例如 `Daily 2026-07-31 via cloudflare-primary`。
4. 检查 `gh-pages/_posts/YYYY-MM-DD-summary-{zh,en}.md`，再检查站点 `/YYYY/MM/DD/summary-{zh,en}.html`。
5. 如果 09:15 后仍未确认发布，接口返回 HTTP 503。优先区分 GitHub API/令牌问题、日报 workflow 失败、`gh-pages` 提交失败和 Pages 渲染失败；不要直接使用 `force_publish`，除非确认需要覆盖已发布期号。

## GitHub 备用检查与静默恢复

新增的受保护接口为 `POST /publication/check`，请求头必须携带 `Authorization: Bearer <RECOVERY_CHECK_TOKEN>`。不能用 GET、查询参数令牌或 GitHub PAT 替代；令牌只允许检查并按固定策略恢复当前刊期，不能指定仓库、历史日期或任意工作流。同一个随机令牌存入 Worker Secret、GitHub Actions 仓库 Secret。GitHub 的两个恢复入口必须使用 `--coordinator`，接口故障时记录失败，不降级为无锁直接派发。

外部独立定时方案已取消，无需注册或登录第三方账号。受保护的 HTTP 接口继续供现有 GitHub 备用检查及管理员验收使用，不删除其 Secret。09:15 仅用于后台逾期状态判定，不接入邮件或消息通知。

响应语义：

| 响应 | 含义 |
| --- | --- |
| 200 `healthy` | 当期已在生产页面验证，无须补发。 |
| 200 `not_due` | 当天尚未到 08:30，不触发提前生成。 |
| 202 | 未到逾期时限，正在生成、等待部署或恢复冷却中。 |
| 503 | 09:15 后仍未确认发布、任务卡住、次数耗尽或检查本身失败。 |
| 401 / 405 | 密钥错误或请求方法错误，属于配置故障。 |

按管理员要求，不接入新的邮件或消息通知服务。系统静默检查并自动补发，异常和重试耗尽保留后台日志。验收需确认正常 200、未授权 401、模拟故障恢复和实际定时执行记录。两套现有平台增加检查机会，但不构成第三方独立调度；GitHub 和 Cloudflare 同时异常时仍可能延迟，也不无限重试付费 AI 任务。

## 发布顺序与回滚

GitHub 检查客户端必须发送 `User-Agent: bmtnews-schedule-watchdog`。生产验证发现 Cloudflare 会在 Worker 执行前拒绝默认的 `Python-urllib/3.12` 客户端标识（HTTP 403 / 1010）；这里使用应用标识，不关闭 Cloudflare 安全检查。若调用失败，先查看 HTTP 状态，再核对 Secret，不绕过共享锁直接补发。

先配置 Worker 的两个新 Secret 和 GitHub 的 `RECOVERY_CHECK_TOKEN`，运行 Worker 检查并部署，再验证生产 `/publication/check` 返回正确刊期；随后合并启用共享接口的 GitHub 工作流；无需接入任何外部定时服务。Durable Object 使用 SQLite 首次迁移 `recovery-v1`，后续修改不要删除已部署的迁移记录。若回滚业务代码，保留绑定和迁移，避免丢失重试预算；若暂时停止自动恢复，应同时停用 Cloudflare Cron 和 GitHub 的自动恢复入口，不要删除锁数据后继续派发。

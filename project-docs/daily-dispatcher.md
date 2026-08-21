# BMTNews 08:30 日报调度

## 目标与时间边界

BMTNews 每天生成一期早间日报，业务时区固定为 `Asia/Shanghai`。日报的数据窗口为 `[前一天 08:00，当天 08:00)`，08:00 截止，08:30 开始生成；`edition_date` 等于窗口结束日，例如 `2026-07-31` 代表 `[2026-07-30 08:00, 2026-07-31 08:00)`。

发布工作流不再依赖 GitHub `schedule` 作为主触发源，而是只接受带明确 `edition_date` 的 `workflow_dispatch`。这样即使补跑发生在数小时之后，任务仍会生成原定期号，不会因“当前时间”变化而错误跨期。

## 双调度与恢复链路

| 上海时间 | 调度源 | 行为 |
| --- | --- | --- |
| 08:30 | Cloudflare Cron | 主触发；当期未发布且没有运行中任务时，触发日报。 |
| 08:40 | Cloudflare Cron | 第一次检查；失败或未创建运行时补触发。 |
| 08:47 | GitHub Actions | 独立备用 Watchdog；Cloudflare 主链路失效时补触发。 |
| 08:55 | Cloudflare Cron | 第二次检查；继续按“已发布、运行中、缺失”三态去重。 |
| 09:10 | Cloudflare Cron | 最终检查；缺失时再补触发一次并将 Cron 事件标记失败。 |

Cloudflare Worker 同时检查两层结果：`gh-pages` 分支中的中英文 Markdown 代表“日报已生成并提交”，GitHub Pages 中的中英文 HTML 代表“站点已渲染”。前者成功而后者未就绪时不会重复调用 AI，只记录 Pages 渲染预警；日报缺失但已有运行中任务时也不会重复触发。

日内原始内容仍由 GitHub Actions 在 00:30 和 16:30 暂存，最终日报会再执行一次 24 小时补采。暂存任务是覆盖率增强项，不是日报按时生成的单点依赖。

## 首次切换

从旧的 20:00 截止切换到 08:00 截止时，第一期新窗口会与最后一期旧窗口重叠 12 小时。发布状态保留最近两天的已发布 URL，重叠内容会在 AI 分析前被剔除，因此实际新增内容自然形成 `[最后一次 20:00 截止，下一次 08:00 截止)` 的 12 小时桥接；不要为首次切换启用 `force_publish`。

## Cloudflare 部署

Worker 位于 `ops/daily-dispatcher/`。生产部署前需要一个仅限 `ohxiyu/bmtnews-standalone` 仓库的 GitHub fine-grained personal access token，Repository permissions 只授予 `Actions: Read and write`；令牌只写入 Cloudflare Secret，不进入 Git、Wrangler 配置或日志。

```bash
cd ops/daily-dispatcher
npm ci
npx wrangler login
npx wrangler secret put GITHUB_DISPATCH_TOKEN
npm run check
npx wrangler deploy
```

`wrangler.jsonc` 通过 `secrets.required` 强制校验令牌，缺少 Secret 时生产部署会失败。Cloudflare Cron 使用 UTC，因此 08:30、08:40、08:55、09:10 分别配置为 `00:30`、`00:40`、`00:55`、`01:10` UTC；配置变更后应在 Dashboard 的 Cron Events 中确认四个触发器已生效。

## 验证与排障

1. 访问 Worker 的 `/health`，确认服务返回 `status: ok`；该端点只读，不允许通过 HTTP 触发日报。
2. 在 08:30 后检查 Cloudflare Workers Logs，结构化字段包含 `edition_date`、`stage`、`raw_posts_ready`、`rendered_posts_ready`、`active_run_url` 和 `outcome`。
3. 在 GitHub Actions 中确认日报运行名包含明确期号和来源，例如 `Daily 2026-07-31 via cloudflare-primary`。
4. 检查 `gh-pages/_posts/YYYY-MM-DD-summary-{zh,en}.md`，再检查站点 `/YYYY/MM/DD/summary-{zh,en}.html`。
5. 如果 09:10 最终检查失败，优先区分 GitHub API/令牌问题、日报 workflow 失败、`gh-pages` 提交失败和 Pages 渲染失败；不要直接使用 `force_publish`，除非确认需要覆盖已发布期号。

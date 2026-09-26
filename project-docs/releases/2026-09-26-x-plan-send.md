# X 分发改为「先计划、后发送」

- Issue: [#131](https://github.com/ohxiyu/bmtnews-standalone/issues/131)
- Branch: `agent/x-plan-send`
- Baseline: `879ec3e2e66071d48ba0b28ece54f983a5c6c9ce`
- Scope: X drip 分发（`src/x_queue.py`、`run_x_slot`、`x_delivery`、X 文案 prompt、配置、`x-distribution.yml`、日报 kickoff 失败处理）。没有修改 `gh-pages`、`staging-cache`、`square-queue`、调度 Worker；`x-queue` 只由合并后的正常运行写入。digest 模式、Telegram、币安广场行为不变。

## 修复的问题

| 问题（基线） | 现在 |
| --- | --- |
| 超时/5xx 被当失败，下个时段重新生成另一段文案再发，可能重复发帖 | 发前先把任务标 `pending` 并 push；结果按 sent / not_sent / rate_limited / failed / unknown 归类；unknown 与中断的 pending 永不自动重发，workflow 变红交人工 |
| `x-queue` 拉取失败时当成空队列从第 1 条重发，收尾 `push -f` 覆盖 | `git ls-remote` fail-closed 恢复；每次状态变化普通 push，被拒则本次不发请求；删除 force push |
| 重刊改变前 3 条时当天静默停发，job 仍绿 | 以规范 URL 哈希标识故事；重刊只重写未尝试的任务并保留时间表 |
| 文案喂 6000 字原文，只查格式 | 只用已发布字段；AI 正文中的数字必须在这些字段中找到（允许换单位/四舍五入），否则回落模板 |
| 日报 kickoff 触发失败会让已成功的日报变红 | 改为 warning，20 分钟轮询接上 |

## 新规则（维护者决定）

- 每期 2 条：top1 发布即发；top2 在 top1 实际发出后随机 180–360 分钟（种子固定、落盘）。
- 首次发布晚于 07:26 + 6h（13:26）整期不发 X；单条截止 = min(到期 + 6h, 当天 23:30)。
- 只推当天刊期；过去 7 天发过（含 unknown/failed/void）的故事不再选。
- 401/403/其他 4xx → `failed`，该语言当天停止；429 与未建立连接 → 截止前同文重试。
- top1 unknown 时 top2 照常。人工处理步骤见 [x-distribution.md](../x-distribution.md#需要人工处理时)。

## 迁移

合并后第一次运行把 v1 队列（`posted` 序号 + `selection_keys`）迁移为 v2：有身份的序号记为 `sent`（`migrated_v1`），无法对应故事的记为 `unknown` 交人工。
用 2026-09-26 生产 `x-queue`（已发 rank 1）和生产 `bmtnews_state.json` 本地模拟（假发布器，模板文案）：rank 1 保持 `sent` 不重发，top2 选 rank 2，按首次运行时间 + 347 分钟排期，截止早于 23:30；全天只发 1 条新推。

## 验证

- `uv sync --frozen --extra dev`、`uv run pytest`（858 项通过，全部离线；没有真实 AI 或 X 调用）、`uv run python scripts/check_governance.py`。
- 新增 `tests/test_x_queue.py`：准点/迟到、6h 过期与 23:30 上限、unknown 不重试且 top2 照发、中断 pending→unknown、checkpoint 失败不发请求、401 停发、429 同文重试、重刊只改未尝试任务、7 天去重、数字不符回落模板、v1 迁移、门控、真实 git 非 force push、HTTP 响应分类（响应体不进日志）。
- 门控用系统 Python（无依赖）对生产数据运行：`work=true attention=0`。

## 尚未验证

- 合并、生产部署、第一次生产运行（迁移、top2 实发）均待记录；五个交付状态分开跟踪，见 handoff。
- 真实 X API 的 2xx 响应体结构只按官方文档 `data.id` 实现，首条实发后核对 `tweet_id`。

## 合并与上线（2026-09-26）

- [PR132](https://github.com/ohxiyu/bmtnews-standalone/pull/132) 在 test、analyze、governance、CodeQL、Cloudflare Pages 全部通过后于 03:08 UTC 合并，合并提交 `7e8498414bc536d7503bd7c34d493e2c46f3f146`；远端任务分支已删除。
- 合并后 40 分钟内新 X workflow 一次都没运行：本仓库 GitHub 自带 cron 基本不触发（广场的 5 分钟 cron 累计只有 62 次 schedule 运行，实际靠调度 Worker 每 5 分钟派发）。只靠日报 kickoff 的话 top2 几乎永远发不出去。
- 后续修复（分支 `agent/x-drip-trigger`）：X 改由广场 workflow 的完成事件驱动（Worker 每 5 分钟派发广场），并从广场的触发列表里移除 X 以免循环；cron 保留作兜底。Worker 本身不改、不需要重新部署。
- 会话里的 GitHub 集成没有 `actions:write` 权限（手动派发返回 403），所以首次生产运行只能等修复合并后由广场完成事件触发。

Source commit: `7e8498414bc536d7503bd7c34d493e2c46f3f146` (PR132)；触发修复的合并提交另行记录
Worker version: not changed（调度 Worker 代码与部署均未改动）
Deployment: GitHub Actions 从 main 读取 workflow，合并即生效；无额外部署步骤
Verification: pending — 首次 X 运行后核对 `x-queue` 为 v2（rank 1 `sent`/`migrated_v1`，slot 2 `planned` 且有 due_at/deadline）及 top2 实发结果
Rollback: revert PR132 与触发修复 PR；回滚前先把 `x-queue` 的 `data/x-queue.json` 改回记录当天已发序号的 v1 内容（v1 代码读到 v2 会拒绝执行，不会重发）

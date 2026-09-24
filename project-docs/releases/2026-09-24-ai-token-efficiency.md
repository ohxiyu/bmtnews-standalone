# AI 用量归因与精确粗筛缓存

- Issue: [#127](https://github.com/ohxiyu/bmtnews-standalone/issues/127)
- Branch: `agent/ai-token-efficiency`；PR: pending
- Source baseline: `f2a286594e910fad295f332816b90d07be909f3a`
- Deployment authority: PR only；没有合并、出刊、真实模型调用或渠道发送授权。

## 为什么先做这两项

[2026-09-24 自动日报](https://github.com/ohxiyu/bmtnews-standalone/actions/runs/35933583563) 的运行报告记录 202,507 AI tokens，其中 `other` 35 次、66,553 tokens，与 35 次分析缓存未命中吻合。直接评分的系统提示会动态拼接新闻窗口规则，因此原有精确字符串阶段识别把它误归为 `other`。本 PR 只修正**用量标签**，保持原有 `max_tokens`、思考模式、模型、评分阈值和提示词完全不变。

预筛会对同一批尚未完整分析的候选再次请求模型。新增缓存仅在模型、提示版本、完整系统与用户提示（含顺序、类别、标题、节选）完全相同，且前次返回每个预期索引的有效分数时命中。部分响应、失败批次和损坏条目继续走原模型调用或原有 fail-open 路径；类别保留、排序和分析调用仍按原逻辑执行。缓存独立于原有 4,000 条分析/扩写池，最多 256 批、有效期至多一天，不挤掉已有评分结果。运行报告区分粗筛缓存命中与未命中批数。

这不是普遍跳过预筛：新批次或变化内容仍会消耗 token。无需立刻承诺节省比例；上线后用数期运行报告比较相同候选规模下的调用、token、缓存命中和内容质量。后续输入裁剪或分阶段思考强度 A/B 需另开任务，并对标题、关键事实、排序、去重及中英内容进行抽样验收；本 PR 不做该实验。

## 验证与发布状态

- `uv sync --frozen --extra dev`：通过。
- `uv run pytest`：838 项通过；新增测试使用 mock 模型，覆盖请求预算不变、完整批次持久化、输入/模型变化失效、部分响应不缓存、独立容量及报告显示。
- `uv run python scripts/check_governance.py`、`git diff --check`：通过。
- 当前生产仍使用前一版。2026-09-24 公网 `/api/latest.json` 为 14 条，源提交 `f2a286594e910fad295f332816b90d07be909f3a`，日报产物提交 `1c8624f3f2adba6170735f2636d85baf3650d328`；这不是本任务的生产验证。Worker 未变，版本本次未核验。
- 状态：代码完成、测试通过；PR、合并、部署和线上质量/节省验收均待后续证据。回退当前任务只需经授权 revert 本 PR；不要手改 `main`、`gh-pages`、`staging-cache` 或分发队列。

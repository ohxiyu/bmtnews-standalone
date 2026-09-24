# AI 用量归因与精确粗筛缓存

- Issue: [#127](https://github.com/ohxiyu/bmtnews-standalone/issues/127)
- Branch: `agent/ai-token-efficiency`；PR: [#128](https://github.com/ohxiyu/bmtnews-standalone/pull/128)
- Source baseline: `f2a286594e910fad295f332816b90d07be909f3a`
- Deployment authority: 开发阶段仅 PR；用户随后明确要求“合并部署”，授权本次应用 PR 合并与生产接入。没有强制重刊已发布日报或部署未改动 Worker。
- Rollout evidence: [Issue #129](https://github.com/ohxiyu/bmtnews-standalone/issues/129) / [PR #130](https://github.com/ohxiyu/bmtnews-standalone/pull/130)。

## 为什么先做这两项

[2026-09-24 自动日报](https://github.com/ohxiyu/bmtnews-standalone/actions/runs/35933583563) 的运行报告记录 202,507 AI tokens，其中 `other` 35 次、66,553 tokens，与 35 次分析缓存未命中吻合。直接评分的系统提示会动态拼接新闻窗口规则，因此原有精确字符串阶段识别把它误归为 `other`。本 PR 只修正**用量标签**，保持原有 `max_tokens`、思考模式、模型、评分阈值和提示词完全不变。

预筛会对同一批尚未完整分析的候选再次请求模型。新增缓存仅在模型、提示版本、完整系统与用户提示（含顺序、类别、标题、节选）完全相同，且前次返回每个预期索引的有效分数时命中。部分响应、失败批次和损坏条目继续走原模型调用或原有 fail-open 路径；类别保留、排序和分析调用仍按原逻辑执行。缓存独立于原有 4,000 条分析/扩写池，最多 256 批、有效期至多一天，不挤掉已有评分结果。运行报告区分粗筛缓存命中与未命中批数。

这不是普遍跳过预筛：新批次或变化内容仍会消耗 token。无需立刻承诺节省比例；上线后用数期运行报告比较相同候选规模下的调用、token、缓存命中和内容质量。后续输入裁剪或分阶段思考强度 A/B 需另开任务，并对标题、关键事实、排序、去重及中英内容进行抽样验收；本 PR 不做该实验。

## 验证与发布状态

- `uv sync --frozen --extra dev`：通过。
- `uv run pytest`：838 项通过；新增测试使用 mock 模型，覆盖请求预算不变、完整批次持久化、输入/模型变化失效、部分响应不缓存、独立容量及报告显示。
- `uv run python scripts/check_governance.py`、`git diff --check`：通过。
- PR #128 的 `test`、`analyze`、`governance`、CodeQL 和 Cloudflare Pages Preview 检查：通过；Preview 成功不等于生产部署。
- PR #128 于 2026-09-24 11:20 Asia/Shanghai 合并为 `d236333b4e0ac5a3a74c75e01c173b4a5561b5cb`；生产 [Feed Collection](https://github.com/ohxiyu/bmtnews-standalone/actions/runs/35951132730) 在同一提交上成功，Actions 写出 gh-pages 事件页提交 `48342b4974bed6169f3f19de155260a8185af2f7`。没有直接编辑 `gh-pages` 或 `staging-cache`。
- 采集报告为 warning：112 条原始候选、11 条新增暂存；RSS 中 Wu Blockchain 与 Bitcoin Magazine 返回 HTTP 403，但顶层来源 6/6 可继续使用。正文分析 11 次均正确归为 `content_analysis`，输入 15,498、输出 4,283 tokens；报告另有 `event_classifier_errors=1`，该采集运行仍成功。此次采集没有触发预筛，不能用它推断缓存命中或节省比例。
- 2026-09-24 11:27 Asia/Shanghai 核对 `https://bmt.news/` 与 `https://bmt.news/api/latest.json` 均为 HTTP 200；后者仍是合并前 07:28 左右生成的 14 条日报，不是本改动的日报质量验收。Cloudflare Pages 精确生产部署 ID 未核验；站点 Worker 与独立调度 Worker 均未修改。
- 状态：代码、测试、应用 PR 合并、生产 Actions 接入完成；预筛缓存实际命中率、token 节省、排行和内容质量仍待下一期自动日报与后续 3–7 天观察。不要为制造数据而强制重刊今天日报。

Source commit: `d236333b4e0ac5a3a74c75e01c173b4a5561b5cb`
Worker version: not changed / independent dispatcher version unverified; PR #128 未触及 `ops/` 或 `docs/_worker.js`
Deployment: [Feed Collection run 35951132730](https://github.com/ohxiyu/bmtnews-standalone/actions/runs/35951132730)；Actions 事件页产物 `48342b4974bed6169f3f19de155260a8185af2f7`；Cloudflare Pages 精确 ID 未核验
Verification: 2026-09-24 11:27 Asia/Shanghai，生产运行成功，`content_analysis` 归因 11 次，公网首页和 `/api/latest.json` 返回 200；预筛缓存和下一期日报尚未验证
Rollback: 已知上一版源码 `f2a286594e910fad295f332816b90d07be909f3a`；如新日报出现回归，经授权 revert PR #128 并走正常 PR/Actions 路径，不手动覆盖生产数据或队列

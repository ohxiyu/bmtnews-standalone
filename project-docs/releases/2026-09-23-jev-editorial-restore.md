# JEV 新闻稿恢复：交付与验收记录

- Issue: [#114](https://github.com/ohxiyu/bmtnews-standalone/issues/114)
- Branch: `agent/jev-editorial-restore`
- PR: [#115](https://github.com/ohxiyu/bmtnews-standalone/pull/115)
- Source base: `1e171e06363368fa5b378718a05c6da234e84112`
- Authority: User authorized merge and deployment on 2026-09-23 (see [Issue #114 owner update](https://github.com/ohxiyu/bmtnews-standalone/issues/114#issuecomment-5788560351)); gh-pages remains Actions-only.

## 原因与改动

2026-09-23 的 [Daily Edition 运行](https://github.com/ohxiyu/bmtnews-standalone/actions/runs/35800042365)显示候选 309、已分析 140、已展示 11，但 11 条全是 `enrichment_degraded`。JEV 分析路径清空 `ai_tags`，并将 `ai_summary` 设置为原标题；扩写通过一整份 JSON 核验，一旦任一附加分析不合格，就改写标题与正文为双语短版。页面、API 与分享图只是呈现了该结果。

改动恢复新闻式提示词，英文标题保留原来源字面、中文忠实翻译。完整稿通过 JEV 核验时保留正文分段、背景、讨论、市场影响、验证过的搜索链接和标签；完整稿未通过时单独核验事实核心，保留已核实新闻正文，剔除未核实的附加字段；核心也未通过才使用原有短版翻译并再次核验。JEV 仍独占评分和去重判断，核验门槛不变。缓存版本更新，避免旧短版复用；回退原因只保存固定错误码。

为本次已发布期号重建补上 Telegram 防重复：仅当同一期已经发布且显式 `force_publish` 时跳过再次发送，并在运行报告标记；正常每日首次发布保持原行为。X 与币安广场继续使用各自持久化队列的重复保护。

## 五阶段状态

| 阶段 | 状态 | 证据或待办 |
| --- | --- | --- |
| 代码完成 | complete | 本任务分支的源代码与测试 |
| 测试通过 | complete | `uv sync --frozen --extra dev`、`uv run pytest -q`；提交前复核 |
| PR 合并 | pending | 待审查与 GitHub checks |
| 部署成功 | pending | 已授权；需核对 Actions 构建与 Pages 部署 |
| 线上验收 | pending | 对 `https://bmt.news/api/latest.json` 验证 JEV 评分、正文分段、背景/讨论/引用/标签；对不支持字段留空而不编造 |

## 边界与下一步

本地测试无法证明生产模型生成质量、JEV 完整稿通过率或旧日报自动修复。合并后需要授权重建相关日报，再检查 run report 中 `enrichment_degraded`、`enrichment_fallback_reasons` 与页面/API/分享图字段；若来源本身只有标题且无可靠外部证据，仍应保留短版而非填充虚构背景。PR113 也修改交接指针，合并时必须人工协调，不能覆盖其独立的历史发布证据。

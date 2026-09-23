# JEV 背景与参考资料独立核验交付

- Issue: [#116](https://github.com/ohxiyu/bmtnews-standalone/issues/116)
- Branch: `agent/jev-context-salvage`
- PR: pending
- Base source: `507a62d1febb1084a48663c423f0b1e45f89a4e0`
- Authority: 用户本轮要求合并并部署；仍须绿灯 PR，禁止直接提交 main 或手改 gh-pages。

## 事实与修复

[PR115](https://github.com/ohxiyu/bmtnews-standalone/pull/115) 已在 [2026-09-23 正式重建](https://github.com/ohxiyu/bmtnews-standalone/actions/runs/35815874196) 中发布。公网 `/api/latest.json` 生成时间为 `2026-09-23T03:55:16.493312Z`，10 条中 7 条恢复了分段正文和标签；但运行报告 `enrichment_degraded=10`，`optional_context_unverified=7`，页面背景和参考链接仍缺失。因此本任务单独把附加字段拆成解释、背景及引用、市场影响、社区讨论四组，在一次 JEV 多问题请求中分别判断。每组仍需 `supported` 且概率至少 90%；只将通过的字段放回已核实新闻正文，引用 URL 必须来自实际搜索结果。无评论时不生成讨论。附加核验接口不可用时仅保留已核实事实正文，不绕过门槛。

## 验证与状态

| 阶段 | 状态 | 证据或待办 |
| --- | --- | --- |
| 代码完成 | complete | 独立核验、缓存版本与回归测试 |
| 测试通过 | complete | `uv sync --frozen --extra dev`、`uv run pytest`（887 项）及治理检查 |
| PR 合并 | pending | 等待 GitHub checks |
| 部署成功 | pending | 合并后从 main 显式重建 2026-09-23 期；Actions 更新 gh-pages |
| 线上验收 | pending | 对比工作流、gh-pages、公网 HTML/API 的生成时间、正文、背景、影响、引用、标签及 Telegram 跳过记录 |

与 PR113 的历史发布证据分开，不能用本任务交接覆盖其独立记录。若来源本身没有背景证据或搜索结果，允许背景/引用保持空值，不因想填充页面而编造内容。部署后使用后续文档 PR 记录准确源码提交、产物提交、页面验收和回退点。

# 当前交接

当前任务：恢复 JEV 接管后丢失的完整新闻稿及参考资料，保持唯一评分和 90% 核验门槛。上次部署证据由待合并的 [PR113](https://github.com/ohxiyu/bmtnews-standalone/pull/113) 单独维护；本任务不得覆盖它。

<!-- execution-pointer -->
```json
{
  "goal": "保留 Jev 评分，恢复有来源支持的完整新闻稿、参考资料和标签",
  "issue": "https://github.com/ohxiyu/bmtnews-standalone/issues/114",
  "owner": "Codex / jev-editorial-restore",
  "branch": "agent/jev-editorial-restore",
  "last_verified_commit": "bf33324662745262b900e6fc262545a4adc60870",
  "pr": "https://github.com/ohxiyu/bmtnews-standalone/pull/115",
  "completed": [
    "定位线上 2026-09-23 日报 11 条全为短版、标签为空",
    "区分完整稿、经核验新闻核心和短版回退；保留英文来源标题与正文分段",
    "有来源支持的背景、讨论、市场影响、引用和标签继续发布",
    "更换扩写缓存版本并记录脱敏回退原因",
    "已发布期号强制重建时跳过重复发送 Telegram，正常首发不变"
  ],
  "unfinished": [
    "等待最终回归及 PR 检查",
    "按用户当前任务授权合并、重建当期日报并完成线上验收"
  ],
  "validation": [
    "uv sync --frozen --extra dev 通过",
    "uv run pytest -q 全量测试通过（提交前将重跑）"
  ],
  "unverified": [
    "未调用生产模型验证新版完整稿通过率",
    "未合并、未部署、未重新生成日报"
  ],
  "production": {
    "source_commit": "1e171e06363368fa5b378718a05c6da234e84112",
    "artifact_commit": "unknown; see PR113 for prior deployment evidence",
    "edition": "2026-09-23 latest.json, verified before this code change",
    "generated_at": "2026-09-23T00:07:39.217506Z",
    "worker_version": "not changed; independent dispatcher version unknown",
    "verified_at": "2026-09-23 Asia/Shanghai; API and Actions run 35800042365"
  },
  "blockers": [],
  "next_action": "审查并合并本任务 PR 后，经授权触发日报重建并核对内容；协调 PR113 的交接文档冲突",
  "states": {
    "code": "complete",
    "tests": "complete",
    "pr_merged": "pending",
    "deployed": "pending",
    "production_verified": "pending"
  },
  "evidence": "project-docs/releases/2026-09-23-jev-editorial-restore.md"
}
```

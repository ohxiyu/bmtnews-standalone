# 当前交接

当前目标：按 [Issue123](https://github.com/ohxiyu/bmtnews-standalone/issues/123) 移除 JEV 接入，逐功能恢复其首次引入前的评分、去重及扩写行为；只交付目标为 main 的 PR，不合并、不部署、不运行生产工作流。历史线上状态仍是 2026-09-23 日报，不能把本分支的本地测试当作上线验收。

<!-- execution-pointer -->
```json
{
  "goal": "移除 JEV，恢复基线 DeepSeek 评分和语义去重，保留后续独立改进",
  "issue": "https://github.com/ohxiyu/bmtnews-standalone/issues/123",
  "owner": "Codex / remove-jev",
  "branch": "agent/remove-jev",
  "last_verified_commit": "75052e895eec4df6a2b9dbf425048d985608a887",
  "pr": "pending creation against main",
  "completed": [
    "确认 JEV 首次引入提交 1e41ec1，其父提交 c0f37bef 为行为基线",
    "按接入点移除独立评分、语义去重和扩写后核验；恢复生成模型直接评分及原有去重",
    "保留后续独立的新闻式写作提示、原文标题、标签、报告来源统计及 Telegram 重建防重发"
  ],
  "unfinished": [
    "创建 PR 并核验 GitHub test/analyze 等必需检查",
    "等待用户另行决定是否合并及何时切换生产日报；未获部署授权"
  ],
  "validation": [
    "uv sync --frozen --extra dev 通过；本地全量 pytest 833 项通过；治理检查通过",
    "所有新增测试使用 mock 客户端，没有真实 AI 或渠道调用"
  ],
  "unverified": [
    "真实 DeepSeek 首期分数分布、7.0 门槛命中率、去重质量及可选内容覆盖率未经生产验证",
    "任何日报、X、币安广场、Telegram 生产工作流均未触发"
  ],
  "production": {
    "source_commit": "8e4447ba5ade934b2bcbc5be58a0908729c8a120",
    "artifact_commit": "58bf9d1372a117b179c70154df886eec713585c5",
    "edition": "2026-09-23 latest.json, 9 items, still the old production policy",
    "generated_at": "2026-09-23T10:17:32.934485Z",
    "worker_version": "not changed; independent dispatcher version unverified",
    "verified_at": "2026-09-23; read-only public API check, current task not deployed"
  },
  "blockers": [
    "PR 合并与生产切换未获本任务授权；本任务仅交付 PR"
  ],
  "next_action": "审核 PR 与 CI；决定合并窗口后另行授权生产切换，并观察首期评分及内容质量",
  "states": {
    "code": "complete",
    "tests": "complete",
    "pr_merged": "pending",
    "deployed": "pending",
    "production_verified": "pending"
  },
  "evidence": "project-docs/releases/2026-09-24-remove-jev.md"
}
```

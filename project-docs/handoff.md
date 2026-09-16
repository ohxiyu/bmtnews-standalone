# 当前交接

这里只维护一份当前状态。历史事实移入 [发布记录](releases/0.2.0.md)，待办放入 [backlog](backlog.md)。以下 JSON 是唯一 Current execution pointer；文字、聊天与旧发布记录不得替代它。

<!-- execution-pointer -->
```json
{
  "goal": "07:00截止/07:26启动、AI节流；补齐脱敏诊断并修复实证去重故障",
  "issue": "https://github.com/ohxiyu/bmtnews-standalone/issues/90",
  "owner": "Codex / morning-ai-economy",
  "branch": "agent/morning-ai-economy",
  "last_verified_commit": "1473b72df7ac2dc47736d32292acfc48fb5c119e",
  "pr": "https://github.com/ohxiyu/bmtnews-standalone/pull/91",
  "completed": [
    "用户确认07:00截止、07:26启动；同步主调度、共享恢复门槛、备用采集及Watchdog",
    "官方API名deepseek-flash；配置切换，不混用旧模型缓存",
    "24条有界全覆盖比较、已验证结果缓存、失败工作流也保存成功分析缓存",
    "402/401/403停止单次去重重试并给脱敏原因，保持质量与配额不变",
    "首页只更新出刊文案与逾期判定，不改布局"
  ],
  "unfinished": [
    "受控只读诊断确认具体失败原因并补回归测试",
    "PR91未合并/部署；今日旧日报重复未重刊"
  ],
  "validation": [
    "fetch/merge main、uv sync frozen dev通过；809 pytest通过（1既有warning）",
    "48 Worker测试、56 Node测试、类型检查、部署dry-run、治理及diff检查通过"
  ],
  "unverified": [
    "真实失败schema/provider原因待诊断",
    "新调度与模型未上线"
  ],
  "production": {
    "source_commit": "bd6f5c307b14c9f26d5cd5fc157b168c6118d8b7",
    "artifact_commit": "527f82e86a1c8769e8aaa5a2bee128736ce19c2f",
    "edition": "2026-09-16",
    "generated_at": "2026-09-16T00:36:20.538116Z (previous edition unchanged)",
    "worker_version": "341dd1ba-4355-42c9-93dc-4133295b53e7; health still08:30",
    "verified_at": "2026-09-16 12:46 Asia/Shanghai; source/edition previous deployment evidence, Worker health refreshed"
  },
  "blockers": [
    "充值后main重跑35057456755仍在早期语义去重失败；旧异常隐藏根因，余额问题未经证实"
  ],
  "next_action": "在agent分支运行最多12次调用的只读缓存诊断；按结果修复，更新PR91，不合并部署。",
  "states": {
    "code": "in_progress",
    "tests": "complete",
    "pr_merged": "pending",
    "deployed": "pending",
    "production_verified": "pending"
  },
  "evidence": "project-docs/releases/2026-09-16-morning-ai-economy.md"
}
```

last_verified_commit 是上一次实际核验的提交，不要求文档包含它自身的最终 SHA（避免自引用循环）；最终 HEAD 和检查结果以 PR 为准。verified_at 是快照日期，不代表此后仍然最新。deployed / production_verified 的 not_required 仅指本次文档与检查工具变更，不表示应用没有部署。

## 接手顺序

1. 阅读 [AGENTS.md](../AGENTS.md)、本指针、Issue 及相关规范。
2. 核验 `git status -sb`、远端身份、`git fetch origin`、`origin/main`、开放 Issue/PR 和负责人；不能覆盖别人的未提交工作。
3. 用线上 API、gh-pages 生成提交、Actions 运行与必要时 Worker 版本核对记录。HTTP 200、Preview 成功和 main 合并均不等于生产验收。
4. 告知用户当前状态、下一步及禁止触碰范围。冲突先查证，不盲目按旧指针执行。
5. 结束时更新 JSON 全部字段，尤其 unfinished、unverified、blockers、next_action。未完成工作推送任务分支并保留 Draft PR，不为交接强行合并。

账号登录不可继承。只记权限名称和检查方法：`gh auth status`、`gh repo view ohxiyu/bmtnews-standalone`；Cloudflare 按 [调度运行手册](daily-dispatcher.md)检查。不得把任何凭据或密钥值写入交接。

# 当前交接

这里只维护一份当前状态。历史事实移入 [发布记录](releases/0.2.0.md)，待办放入 [backlog](backlog.md)。以下 JSON 是唯一 Current execution pointer；文字、聊天与旧发布记录不得替代它。

<!-- execution-pointer -->
```json
{
  "goal": "记录PR79调度器部署与自动发送验收",
  "issue": "https://github.com/ohxiyu/bmtnews-standalone/issues/80",
  "owner": "Codex / square-distribution",
  "branch": "agent/square-scheduler-release",
  "last_verified_commit": "43fb8a0697c4fa0a25d389384179c611cd60593c",
  "pr": "https://github.com/ohxiyu/bmtnews-standalone/pull/81",
  "completed": [
    "确认9月12日14条计划已生成，但11:33前没有任何schedule运行",
    "手动恢复run34670696550成功发送1条，保留昨日7条sent；今日剩余13条",
    "新增Cloudflare共享5分钟触发、queue_only模式、在途任务保护；不改变日报检查频率",
    "PR79按用户本次授权合并；现有Cloudflare Worker已部署并验证health版本和Cron配置"
  ],
  "unfinished": [
    "等待首次自动触发，核验queue_only和发帖结果",
    "部署证据已提交PR81，等待检查与合并"
  ],
  "validation": [
    "Worker typecheck通过，44项Worker测试通过",
    "uv sync frozen dev成功；773项Python测试通过，1既有warning；治理、types check与Worker dry-run通过"
  ],
  "unverified": [
    "等待首次Cloudflare自动触发及全期发送完成",
    "币安平台最终审核展示未人工验收"
  ],
  "production": {
    "artifact_commit": "not_applicable_worker_deployment",
    "generated_at": "not_applicable_worker_deployment",
    "source_commit": "43fb8a0697c4fa0a25d389384179c611cd60593c",
    "worker_version": "341dd1ba-4355-42c9-93dc-4133295b53e7",
    "edition": "2026-09-12",
    "verified_at": "2026-09-12"
  },
  "blockers": [],
  "next_action": "核验真实自动触发并记录结果；不把部署成功等同于整期发送完成。",
  "states": {
    "code": "complete",
    "tests": "complete",
    "pr_merged": "complete",
    "deployed": "complete",
    "production_verified": "pending"
  },
  "evidence": "project-docs/releases/2026-09-12-square-scheduler-recovery.md"
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

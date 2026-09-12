# 当前交接

这里只维护一份当前状态。历史事实移入 [发布记录](releases/0.2.0.md)，待办放入 [backlog](backlog.md)。以下 JSON 是唯一 Current execution pointer；文字、聊天与旧发布记录不得替代它。

<!-- execution-pointer -->
```json
{
  "goal": "修复Square定时漏触发：复用Cloudflare队列检查",
  "issue": "https://github.com/ohxiyu/bmtnews-standalone/issues/78",
  "owner": "Codex / square-distribution",
  "branch": "agent/square-scheduler-recovery",
  "last_verified_commit": "ae5786ff7bb0e256d5da92fd81a4b285208e7691",
  "pr": "pending",
  "completed": [
    "确认9月12日14条计划已生成，但11:33前没有任何schedule运行",
    "手动恢复run34670696550成功发送1条，保留昨日7条sent；今日剩余13条",
    "新增Cloudflare共享5分钟触发、queue_only模式、在途任务保护；不改变日报检查频率"
  ],
  "unfinished": [
    "提交PR；待用户授权合并和部署现有Worker",
    "部署后验证自主触发、剩余队列推进和平台显示"
  ],
  "validation": [
    "Worker typecheck通过，44项Worker测试通过",
    "uv sync frozen dev成功；773项Python测试通过，1既有warning；治理、types check与Worker dry-run通过"
  ],
  "unverified": [
    "新调度器未部署，未验证真实Cloudflare触发和现有token对Square workflow的权限",
    "npm ci提示既有6项开发依赖漏洞，未做越界强制升级"
  ],
  "production": {
    "source_commit": "679ea58cefaa6ae94718ff3c938ad9872e08a2ff",
    "artifact_commit": "3413ae7b54e00c11fb99d15641c4674f6d41d77c",
    "edition": "2026-09-11",
    "generated_at": "2026-09-11T00:34:44.693913Z",
    "worker_version": "Pages 3e5a820e-9491-410a-918d-b1588dd39872；这是 PR70 部署快照，今日日报已有后续产物",
    "verified_at": "2026-09-11"
  },
  "blockers": [
    "合并/部署需要当前任务授权；本地测试不能替代生产定时验收"
  ],
  "next_action": "检查PR与CI；授权后合并并部署现有dispatcher，核验queue_only生产步骤及发帖；不要清空队列。",
  "states": {
    "code": "complete",
    "tests": "complete",
    "pr_merged": "pending",
    "deployed": "pending",
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

# 当前交接

这里只维护一份当前状态。历史事实移入 [发布记录](releases/0.2.0.md)，待办放入 [backlog](backlog.md)。以下 JSON 是唯一 Current execution pointer；文字、聊天与旧发布记录不得替代它。

<!-- execution-pointer -->
```json
{
  "goal": "修复 Square 定时未触发，增加已有发布流程兜底与同小时额度",
  "issue": "https://github.com/ohxiyu/bmtnews-standalone/issues/74",
  "owner": "Codex / square-distribution",
  "branch": "agent/square-trigger-fix",
  "last_verified_commit": "eed8b775a7157f1a5e405df8f2012c176575f411",
  "pr": "pending",
  "completed": [
    "PR #70 已合并并完成真实登录与列表只读验收，证据在 PR 评论",
    "按用户要求删除取消的 Issue #71、任务分支和未提交本地代码",
    "PR73 已合并，用户已配置专用 Secret 并授权启用；SQUARE_ENABLED=true",
    "查明19:22前 Square 工作流零触发；手动生产恢复 run34593750085，API确认首3条成功且有帖子ID",
    "新增日报/X成功完成兜底与同小时额度回归测试"
  ],
  "unfinished": [
    "提交触发修复 PR，待授权合并；今天剩余11条尚未发送",
    "合并后验证 workflow_run 真实触发与同小时额度"
  ],
  "validation": [
    "uv sync --frozen --extra dev 成功；pytest 768 passed、1既有warning（17.46秒）；Square专项20 passed；治理与diff check通过",
    "生产首次分发run34593750085成功，3个帖子ID已持久化，详见发布记录"
  ],
  "unverified": [
    "新增 workflow_run 兜底未上线；API成功不代表已人工检查平台展示/审核状态",
    "Quick Post 生产内容写入仍未验收；本次不改变后台"
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
    "本补丁未获合并授权；GitHub 内部为何漏触发不可直接观测"
  ],
  "next_action": "提交触发修复 PR，审核合并后验证自动兜底。保留 square-queue，不能重发已sent项。",
  "states": {
    "code": "complete",
    "tests": "complete",
    "pr_merged": "pending",
    "deployed": "pending",
    "production_verified": "pending"
  },
  "evidence": "project-docs/releases/2026-09-11-square-trigger-fix.md"
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

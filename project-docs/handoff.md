# 当前交接

这里只维护一份当前状态。历史事实移入 [发布记录](releases/0.2.0.md)，待办放入 [backlog](backlog.md)。以下 JSON 是唯一 Current execution pointer；文字、聊天与旧发布记录不得替代它。

<!-- execution-pointer -->
```json
{
  "goal": "每日全部入选新闻分散发布到币安广场，不增加 AI 调用",
  "issue": "https://github.com/ohxiyu/bmtnews-standalone/issues/72",
  "owner": "Codex / square-distribution",
  "branch": "agent/binance-square",
  "last_verified_commit": "679ea58cefaa6ae94718ff3c938ad9872e08a2ff",
  "pr": "https://github.com/ohxiyu/bmtnews-standalone/pull/73",
  "completed": [
    "PR #70 已合并并完成真实登录与列表只读验收，证据在 PR 评论",
    "按用户要求删除取消的 Issue #71、任务分支和未提交本地代码",
    "新增独立 Square 分发器、持久化发送前检查点、按小时分发工作流与测试"
  ],
  "unfinished": [
    "PR #73 已提交，等待 CI 与用户审核；未合并",
    "Square 专用发布 Key、启用开关和真实发帖验收未完成"
  ],
  "validation": [
    "uv sync --frozen --extra dev 成功；全量 pytest 764 passed、1 个既有弃用警告，10.22 秒",
    "Square 专项 16 passed，含本地 bare Git 远端检查点恢复；治理检查和 diff check 通过"
  ],
  "unverified": [
    "Square 真实账号、发布权限、内容长度限制及链接尚未通过实发验收",
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
    "Square 未配置发布凭据和启用开关；本任务只获开发授权，不合并或部署"
  ],
  "next_action": "审核 PR #73；另行授权合并并配置 Secret/开关后验收真实发布。PR #68 的旧指针不能覆盖本交接。",
  "states": {
    "code": "complete",
    "tests": "complete",
    "pr_merged": "pending",
    "deployed": "pending",
    "production_verified": "pending"
  },
  "evidence": "project-docs/releases/2026-09-11-square-distribution.md"
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

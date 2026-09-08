# 当前交接

这里只维护一份当前状态。历史事实移入 [发布记录](releases/0.2.0.md)，待办放入 [backlog](backlog.md)。以下 JSON 是唯一 Current execution pointer；文字、聊天与旧发布记录不得替代它。

<!-- execution-pointer -->
```json
{
  "goal": "建立仓库内统一的 Agent 交接、任务认领与交付检查",
  "issue": "https://github.com/ohxiyu/bmtnews-standalone/issues/64",
  "owner": "Codex / agent-governance",
  "branch": "agent/agent-governance",
  "last_verified_commit": "fb3152b333be617db8260b04d91f8c6f02b6eba2",
  "pr": "https://github.com/ohxiyu/bmtnews-standalone/pull/65",
  "completed": [
    "统一 AGENTS 与三个短入口；项目状态/规范/历史证据职责分离",
    "新增任务 Issue Form、PR 交付模板与 CI governance job",
    "版本、文件链接、唯一交接和交付证据检查及 11 个回归用例"
  ],
  "unfinished": [
    "等待 PR #65 最终提交的远端检查及用户审阅",
    "用户审阅和合并决定；本任务不合并或部署"
  ],
  "validation": [
    "uv sync --frozen --extra dev: passed",
    "uv run python scripts/check_governance.py: passed",
    "uv run pytest: 740 passed, 1 dependency deprecation warning",
    "git diff --check: passed"
  ],
  "unverified": [
    "最终 PR HEAD 的实时 GitHub 检查：须从 PR checks 核验，不从交接推断",
    "生产 Worker 当前版本和权限（本任务未部署，无需运行时验收）"
  ],
  "production": {
    "source_commit": "950fc42f726be68df51c8217dbb4df29986ae496",
    "artifact_commit": "69d8cf54140f622b6ba05d02af9748e9e0df1402",
    "edition": "2026-09-08",
    "generated_at": "2026-09-08T04:24:17.494842Z",
    "worker_version": "not verified in this task",
    "verified_at": "2026-09-08"
  },
  "blockers": [
    "无开发阻塞；合并/生产部署需本任务明确授权，历史授权不可自动沿用"
  ],
  "next_action": "核验 PR #65 的 governance/test/analyze 后交用户审阅；未经新授权不合并、部署或处理 backlog。",
  "states": {
    "code": "complete",
    "tests": "complete",
    "pr_merged": "pending",
    "deployed": "not_required",
    "production_verified": "not_required"
  },
  "evidence": "project-docs/releases/2026-09-08-agent-governance.md"
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

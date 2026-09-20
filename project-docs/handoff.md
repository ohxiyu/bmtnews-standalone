# 当前交接

这里只维护一份当前状态。历史事实移入 [发布记录](releases/0.2.0.md)，待办放入 [backlog](backlog.md)。以下 JSON 是唯一 Current execution pointer；文字、聊天与旧发布记录不得替代它。

<!-- execution-pointer -->
```json
{
  "goal": "Quick Post 可选刊期位置并实时发布、编辑、停用",
  "issue": "https://github.com/ohxiyu/bmtnews-standalone/issues/94",
  "owner": "Codex / quick-post-immediate",
  "branch": "agent/quick-post-immediate",
  "last_verified_commit": "4e64fda1d4f2f76f8ec78e0121a7b87dd798e3cb",
  "pr": "https://github.com/ohxiyu/bmtnews-standalone/pull/95",
  "completed": [
    "从最新 origin/main 接手续作；当前电脑没有原未提交文件",
    "实时公开读取、固定路径图片读取、刊期内插入位置与历史加载",
    "保留 Access、CSRF、SHA 冲突与幂等保护"
  ],
  "unfinished": [
    "PR95 等待远程 CI 与审阅",
    "合并及生产部署尚未执行"
  ],
  "validation": [
    "uv sync --frozen --extra dev、823 pytest、治理与 diff 检查通过",
    "33 Worker 与 28 分享/PWA/调度 Node 测试通过",
    "390/1280 浏览器模拟验证位置、历史加载、停用、失败与重试；后台草稿恢复与冲突保护通过",
    "真实首页只读加载后本地注入预览，390/1280 正文、排行数量与溢出检查通过；未写生产"
  ],
  "unverified": [
    "真实生产 Access 会话发布、图片与停用尚未验收"
  ],
  "production": {
    "source_commit": "unknown; current source baseline 4e64fda1d4f2f76f8ec78e0121a7b87dd798e3cb",
    "artifact_commit": "unknown; not modified",
    "edition": "2026-09-18 (public edition index)",
    "generated_at": "2026-09-17T23:28:47.562942Z (edition index)",
    "worker_version": "unknown; not deployed",
    "verified_at": "2026-09-18 read-only public API check"
  },
  "blockers": [],
  "next_action": "审阅 PR95 和最新 CI；合并和生产部署需本任务授权，不能发布虚构测试新闻。",
  "states": {
    "code": "complete",
    "tests": "complete",
    "pr_merged": "pending",
    "deployed": "pending",
    "production_verified": "pending"
  },
  "evidence": "project-docs/releases/2026-09-18-quick-post-immediate.md"
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

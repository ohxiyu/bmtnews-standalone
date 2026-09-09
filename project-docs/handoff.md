# 当前交接

这里只维护一份当前状态。历史事实移入 [发布记录](releases/0.2.0.md)，待办放入 [backlog](backlog.md)。以下 JSON 是唯一 Current execution pointer；文字、聊天与旧发布记录不得替代它。

<!-- execution-pointer -->
```json
{
  "goal": "以 Quick Post 替代现有手动插入入口，先确认即时发布的存储边界",
  "issue": "https://github.com/ohxiyu/bmtnews-standalone/issues/66",
  "owner": "Codex / quick-post",
  "branch": "agent/quick-post",
  "last_verified_commit": "3a035c6a191a7431660cac88daf22da3c3b42bec",
  "pr": "https://github.com/ohxiyu/bmtnews-standalone/pull/67",
  "completed": [
    "完整读取用户 Quick Post 需求；核验 main、工作区、开放 Issue/PR 并认领 Issue #66",
    "确认当前 CMS 使用 GitHub Token 写 editorial.json，图片存 Git，发布经整期重建",
    "确认没有内容 D1/KV/R2，也没有现成的 post creation API；记录两条接入路径"
  ],
  "unfinished": [
    "用户决定保留 Git 分钟级生效，或授权在现有 Cloudflare 内增加实时持久化存储",
    "确认后实现 Quick Post、兼容旧内容、接口与安全校验、UI 和功能测试",
    "本任务只有 PR 交付权限，尚未授权合并或生产部署"
  ],
  "validation": [
    "只读代码审查完成；尚未实现功能，不沿用之前任务的测试结果",
    "python3 scripts/check_governance.py 与 git diff --check 通过（仅文档结构检查）",
    "2026-09-10 主站 pwa-version.json 返回 assets sha256-fc44e345414e / build 2026-09-09T09:10:02+00:00"
  ],
  "unverified": [
    "当前浏览器 CMS Token 有效性、生产 Cloudflare 绑定与写入权限未探测",
    "Quick Post 尚未开发，所有功能与移动端测试均待执行",
    "下方 production 为继承的 09-08 快照，不是本次核验的新发布"
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
    "静态 Git 重建无法承诺发布后立即对所有读者生效；需用户确认时效或存储扩展"
  ],
  "next_action": "等待用户选择即时发布接入路径；先更新 Issue #66 范围，再实现。勿继续旧治理任务或合并旧本地 handoff 分支。",
  "states": {
    "code": "pending",
    "tests": "pending",
    "pr_merged": "pending",
    "deployed": "pending",
    "production_verified": "pending"
  },
  "evidence": "project-docs/releases/2026-09-10-quick-post-discovery.md"
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

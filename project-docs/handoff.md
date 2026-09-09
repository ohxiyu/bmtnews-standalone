# 当前交接

这里只维护一份当前状态。历史事实移入 [发布记录](releases/0.2.0.md)，待办放入 [backlog](backlog.md)。以下 JSON 是唯一 Current execution pointer；文字、聊天与旧发布记录不得替代它。

<!-- execution-pointer -->
```json
{
  "goal": "落地 Quick Post 与指定邮箱验证码登录，保留 Git 存储并完成上线验收",
  "issue": "https://github.com/ohxiyu/bmtnews-standalone/issues/66",
  "owner": "Codex / quick-post",
  "branch": "agent/quick-post",
  "last_verified_commit": "3a035c6a191a7431660cac88daf22da3c3b42bec",
  "pr": "https://github.com/ohxiyu/bmtnews-standalone/pull/67",
  "completed": [
    "完整读取用户 Quick Post 需求；核验 main、工作区、开放 Issue/PR 并认领 Issue #66",
    "确认当前 CMS 使用 GitHub Token 写 editorial.json，图片存 Git，发布经整期重建",
    "用户已确认 Git 分钟级发布与 Cloudflare Access 邮箱登录，并提供唯一允许邮箱（仅存平台，不写入仓库）",
    "实现 Quick Post、受保护写入接口、图片上传、旧编辑管理、来源变更申请及无 AI 的独立发布输出",
    "新增 JWT、CSRF、并发、防重复提交、图片与渲染测试；修复治理测试依赖旧指针状态的问题"
  ],
  "unfinished": [
    "完成 Cloudflare Zero Trust / Access 配置及 Pages 生产绑定",
    "用户在平台配置专用受限 GitHub 写入凭据，不复用本机 gh OAuth 或调度 Token",
    "远端 CI、PR 合并、正式部署与真实邮箱端到端验收；未满足前不合并"
  ],
  "validation": [
    "本地 uv sync --frozen --extra dev 成功；完整 pytest 通过，确切计数见发布记录",
    "管理接口 15 项 Node 测试通过，公开 Worker、分享和 PWA 回归测试通过",
    "390px 与 1280px 模拟浏览器通过草稿恢复、冲突保留、保存状态和横向溢出检查"
  ],
  "unverified": [
    "真实邮箱 OTP、生产 Git 写入与发布完成尚未验证；不得把 mock 测试等同线上验收",
    "真实 iPhone/PWA 未验收，生产未配置后台专用 Secrets",
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
    "现有 Cloudflare OAuth 查询 Zero Trust organization 返回 403，需要用户完成平台开通/授权",
    "Pages 当前没有 ADMIN_GITHUB_TOKEN 与 Access 绑定；缺配置时管理路由故意返回 503"
  ],
  "next_action": "按交付记录配置 Access 与受限凭据，再完成 CI、发布与真实 OTP 验收；配置前保持 Draft，不替换生产后台。",
  "states": {
    "code": "complete",
    "tests": "complete",
    "pr_merged": "pending",
    "deployed": "pending",
    "production_verified": "pending"
  },
  "evidence": "project-docs/releases/2026-09-10-quick-post-implementation.md"
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

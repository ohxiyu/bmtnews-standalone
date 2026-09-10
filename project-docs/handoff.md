# 当前交接

这里只维护一份当前状态。历史事实移入 [发布记录](releases/0.2.0.md)，待办放入 [backlog](backlog.md)。以下 JSON 是唯一 Current execution pointer；文字、聊天与旧发布记录不得替代它。

<!-- execution-pointer -->
```json
{
  "goal": "修复 Quick Post 上线验收中的 Worker redirect 模式兼容错误",
  "issue": "https://github.com/ohxiyu/bmtnews-standalone/issues/69",
  "owner": "Codex / quick-post",
  "branch": "agent/access-runtime-fix",
  "last_verified_commit": "3a035c6a191a7431660cac88daf22da3c3b42bec",
  "pr": "https://github.com/ohxiyu/bmtnews-standalone/pull/70",
  "completed": [
    "完整读取用户 Quick Post 需求；核验 main、工作区、开放 Issue/PR 并认领 Issue #66",
    "确认当前 CMS 使用 GitHub Token 写 editorial.json，图片存 Git，发布经整期重建",
    "用户已确认 Git 分钟级发布与 Cloudflare Access 邮箱登录，并提供唯一允许邮箱（仅存平台，不写入仓库）",
    "实现 Quick Post、受保护写入接口、图片上传、旧编辑管理、来源变更申请及无 AI 的独立发布输出",
    "新增 JWT、CSRF、并发、防重复提交、图片与渲染测试；修复治理测试依赖旧指针状态的问题"
  ],
  "unfinished": [
    "PR #70 等待 CI、合并和部署；修复后复验真实邮箱登录",
    "GitHub 写入权限与真实内容发布仍待验收"
  ],
  "validation": [
    "本地 uv sync --frozen --extra dev 成功；pytest 748 passed，1 warning，18.08s",
    "管理接口 16 项 Node 测试通过；真实 workerd 验证有效 JWT 通过、重定向公钥被拒绝",
    "390px 与 1280px 模拟浏览器通过草稿恢复、冲突保留、保存状态和横向溢出检查"
  ],
  "unverified": [
    "真实邮箱 OTP 已通过 Access，但旧 Worker 报 invalid_session；修复后尚未复验",
    "真实 iPhone/PWA 未验收；生产密钥已确认加密保存，但有效性与权限尚未验证",
    "edition/generated_at 为旧内容快照，不是本次验收范围"
  ],
  "production": {
    "source_commit": "04ea98021f5728728b9e98ab11767dce7bdf12d6",
    "artifact_commit": "bf0ed47916d48ca05085f6b9fc864c030a0310fb",
    "edition": "2026-09-08",
    "generated_at": "2026-09-08T04:24:17.494842Z",
    "worker_version": "Pages 995adb9d-a5ea-4aee-b8d7-c36958c778bc",
    "verified_at": "2026-09-11"
  },
  "blockers": [
    "2026-09-11：本机 Cloudflare OAuth 过期；已使用已登录控制台完成 Access 与生产绑定配置",
    "已复现根因：workerd 不支持 redirect:error；PR #70 修复待上线，不需要重新配置密钥"
  ],
  "next_action": "完成 Issue #69 修复测试、CI 与发布后复验真实登录；旧 PR #68 是部署记录，合并前需同步最新交接，不能覆盖本指针。",
  "states": {
    "code": "complete",
    "tests": "complete",
    "pr_merged": "pending",
    "deployed": "pending",
    "production_verified": "pending"
  },
  "evidence": "project-docs/releases/2026-09-11-access-runtime-fix.md"
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

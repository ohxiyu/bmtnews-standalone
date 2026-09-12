# 当前交接

这里只维护一份当前状态。历史事实移入 [发布记录](releases/0.2.0.md)，待办放入 [backlog](backlog.md)。以下 JSON 是唯一 Current execution pointer；文字、聊天与旧发布记录不得替代它。

<!-- execution-pointer -->
```json
{
  "goal": "替换经用户确认的圆润 Logo，更新媒体包并合并上线",
  "issue": "https://github.com/ohxiyu/bmtnews-standalone/issues/82",
  "owner": "Codex / brand-v2（本任务发布整合负责人）",
  "branch": "agent/brand-v2",
  "last_verified_commit": "43fb8a0697c4fa0a25d389384179c611cd60593c",
  "pr": "https://github.com/ohxiyu/bmtnews-standalone/pull/83",
  "completed": [
    "核验远端 main 和开放 PR，认领 Issue #82；用户明确授权本任务合并上线",
    "SVG 母版统一外圆角 64、内凹 32、留白 12；黄色圆环与同心圆点",
    "更新媒体、网站、PWA、favicon 和分享卡；v2 地址独立，旧 v1 文件保留"
  ],
  "unfinished": [
    "提交 PR 并核验最终 HEAD 的远端检查",
    "检查通过后合并，等待 Pages 生产成功并验收公开版本",
    "发布后通过文档 PR 回写最终五阶段证据"
  ],
  "validation": [
    "uv sync --frozen --extra dev --offline 成功；使用锁文件本机缓存",
    "母版生成及 sharp PNG/ICO/ZIP 导出成功；773 项 Python、37 项 Node 测试通过",
    "治理与 diff 检查通过；桌面、390px 手机、深色、媒体页和分享长卡本地验收通过"
  ],
  "unverified": [
    "新 Logo 尚未生产发布；主站替换前资源为 sha256-f2e843a8988f",
    "操作系统已安装图标的刷新时间不能由网站保证",
    "以下 production 为继承的旧快照；不代表调度任务尚未部署，相关 PR #81 #77 #68 由原负责人处理"
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
    "无授权阻塞；仅允许本任务品牌变更，不合并其他发布记录 PR、不改调度或认证"
  ],
  "next_action": "完成品牌测试和视觉验收，再检查 exact-head CI、合并并核验 Cloudflare 生产；使用后续文档 PR 更新证据。",
  "states": {
    "code": "complete",
    "tests": "complete",
    "pr_merged": "pending",
    "deployed": "pending",
    "production_verified": "pending"
  },
  "evidence": "project-docs/releases/2026-09-13-brand-v2.md"
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

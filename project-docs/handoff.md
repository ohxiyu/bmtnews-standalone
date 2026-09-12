# 当前交接

这里只维护一份当前状态。历史事实移入 [发布记录](releases/0.2.0.md)，待办放入 [backlog](backlog.md)。以下 JSON 是唯一 Current execution pointer；文字、聊天与旧发布记录不得替代它。

<!-- execution-pointer -->
```json
{
  "goal": "替换经用户确认的圆润 Logo，更新媒体包并合并上线",
  "issue": "https://github.com/ohxiyu/bmtnews-standalone/issues/82",
  "owner": "Codex / brand-v2（本任务发布整合负责人）",
  "branch": "agent/brand-v2",
  "last_verified_commit": "fc45dba69350a6bdc53752944058a6807d9f4881",
  "pr": "https://github.com/ohxiyu/bmtnews-standalone/pull/83",
  "completed": [
    "核验远端 main 和开放 PR，认领 Issue #82；用户明确授权本任务合并上线",
    "SVG 母版统一外圆角 64、内凹 32、留白 12；黄色圆环与同心圆点",
    "更新媒体、网站、PWA、favicon 和分享卡；v2 地址独立，旧 v1 文件保留",
    "PR #83 全部检查通过并合并；Deploy Docs 与 Cloudflare 生产部署成功",
    "主站首页、媒体页、manifest 和 v2 ZIP 实际验收完成；原开发分支已清理"
  ],
  "unfinished": [
    "Logo 产品变更无未完成项；本次证据由 Issue #84 的纯文档 PR 回写",
    "其他未合并发布记录 PR #68 #77 #81 仍归原任务负责人，不在本次范围"
  ],
  "validation": [
    "uv sync --frozen --extra dev --offline 成功；使用锁文件本机缓存",
    "母版生成及 sharp PNG/ICO/ZIP 导出成功；773 项 Python、37 项 Node 测试通过",
    "治理与 diff 检查通过；桌面、390px 手机、深色、媒体页和分享长卡本地验收通过",
    "生产资源 sha256-7e6b0e219d87；公开 ZIP SHA256 与仓库逐字节一致，详见发布记录"
  ],
  "unverified": [
    "操作系统已安装图标的刷新时间不能由网站保证",
    "独立调度 Worker 版本未在本任务核验；没有修改或部署该 Worker"
  ],
  "production": {
    "source_commit": "fc45dba69350a6bdc53752944058a6807d9f4881",
    "artifact_commit": "589ca7315fc3ae410e13c50bc8f6298829453f30",
    "edition": "2026-09-12",
    "generated_at": "2026-09-12T00:34:14.257428Z（日报数据）；网站构建 2026-09-12T17:05:16+00:00",
    "worker_version": "Pages ef9ec162-fbf7-47b7-bb95-752ce1876c2f；独立 dispatcher not changed / unknown",
    "verified_at": "2026-09-13 01:06 Asia/Shanghai"
  },
  "blockers": [
    "无产品发布阻塞"
  ],
  "next_action": "Logo 已上线，等待用户新任务。新任务先 fetch 并核验 Issue/PR，不把记录的日报日期当作实时最新状态，也不自动处理其他发布记录。",
  "states": {
    "code": "complete",
    "tests": "complete",
    "pr_merged": "complete",
    "deployed": "complete",
    "production_verified": "complete"
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

# 当前交接

这里只维护一份当前状态。历史事实移入 [发布记录](releases/0.2.0.md)，待办放入 [backlog](backlog.md)。以下 JSON 是唯一 Current execution pointer；文字、聊天与旧发布记录不得替代它。

<!-- execution-pointer -->
```json
{
  "goal": "07:00截止/07:26启动、AI节流；补齐脱敏诊断并修复实证去重故障",
  "issue": "https://github.com/ohxiyu/bmtnews-standalone/issues/90",
  "owner": "Codex / morning-ai-economy",
  "branch": "agent/morning-ai-economy",
  "last_verified_commit": "599b6d52ad64f78316e8d98ddc3cedbb84e03772",
  "pr": "https://github.com/ohxiyu/bmtnews-standalone/pull/91",
  "completed": [
    "用户确认07:00截止、07:26启动；同步主调度、共享恢复门槛、备用采集及Watchdog",
    "官方API名deepseek-flash；配置切换，不混用旧模型缓存",
    "24条有界全覆盖比较、已验证结果缓存、失败工作流也保存成功分析缓存",
    "402/401/403停止单次去重重试并给脱敏原因，保持质量与配额不变",
    "首页只更新出刊文案与逾期判定，不改布局",
    "脱敏复现JSON语法错误expected_comma；合法示例+格式错误反馈重试，继续严格拒绝无效结果",
    "三个先前失败批次真实API复测35059029282通过：3批/3调用，无格式重试"
  ],
  "unfinished": [
    "PR91等待授权合并与协调部署，未重刊今日旧日报",
    "PR89为旧部署证据，不能覆盖最新交接；历史08:00窗口重刊须显式cutoff8"
  ],
  "validation": [
    "fetch/merge origin/main、uv sync --frozen --extra dev通过",
    "823 pytest通过（1既有warning）；治理及diff检查通过",
    "只读诊断35058489152、35058682859、35058796024复现格式失败；35059029282三个指定批次修复验证通过，共19次应用层模型调用",
    "本任务原有48 Worker、56 Node测试、类型及dry-run通过；本轮未改Worker/UI"
  ],
  "unverified": [
    "未完整重放失败日报的所有历史输入：诊断只恢复缓存子集",
    "DeepSeek新别名deepseek-flash、24项批次真实质量/费用及新调度尚未上线验收；诊断沿用main旧模型和12项批次",
    "今日线上仍08:36旧版14条，重复尚未通过重刊消除"
  ],
  "production": {
    "source_commit": "bd6f5c307b14c9f26d5cd5fc157b168c6118d8b7",
    "artifact_commit": "d8830f2ee65a8ad1ef4f86f368294adcef57126a (collection updated artifact; edition unchanged)",
    "edition": "2026-09-16",
    "generated_at": "2026-09-16T00:36:20.538116Z (previous edition unchanged)",
    "worker_version": "341dd1ba-4355-42c9-93dc-4133295b53e7; health still08:30",
    "verified_at": "2026-09-16 13:19 Asia/Shanghai API refreshed; Worker version remains previous snapshot"
  },
  "blockers": [
    "下一步合并/部署/重刊需要当前明确授权；本轮不清空任何发送记录"
  ],
  "next_action": "审阅PR91和脱敏诊断证据；获授权后协调合并与Worker部署，以cutoff8重刊2026-09-16并核验前三条不同事件及发送幂等，不无条件重试整期。",
  "states": {
    "code": "complete",
    "tests": "complete",
    "pr_merged": "pending",
    "deployed": "pending",
    "production_verified": "pending"
  },
  "evidence": "project-docs/releases/2026-09-16-morning-ai-economy.md"
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

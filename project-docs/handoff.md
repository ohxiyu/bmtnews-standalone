# 当前交接

这里只维护一份当前状态。历史事实移入 [发布记录](releases/0.2.0.md)，待办放入 [backlog](backlog.md)。以下 JSON 是唯一 Current execution pointer；文字、聊天与旧发布记录不得替代它。

<!-- execution-pointer -->
```json
{
  "goal": "07:00截止/07:26启动、DeepSeek V4.1 Flash及安全节流",
  "issue": "https://github.com/ohxiyu/bmtnews-standalone/issues/90",
  "owner": "Codex / morning-ai-economy",
  "branch": "agent/morning-ai-economy",
  "last_verified_commit": "bd6f5c307b14c9f26d5cd5fc157b168c6118d8b7",
  "pr": "https://github.com/ohxiyu/bmtnews-standalone/pull/91",
  "completed": [
    "用户确认07:00截止、07:26启动；同步主调度、共享恢复门槛、备用采集及Watchdog",
    "官方API名deepseek-flash；配置切换，不混用旧模型缓存",
    "24条有界全覆盖比较、已验证结果缓存、失败工作流也保存成功分析缓存",
    "402/401/403停止单次去重重试并给脱敏原因，保持质量与配额不变",
    "首页只更新出刊文案与逾期判定，不改布局"
  ],
  "unfinished": [
    "提交PR并等待CI；未经本任务授权不合并部署",
    "用户完成AI充值后才可验证真实模型调用；今日旧日报重复未重刊",
    "PR89保留前次部署证据；合并它时不能用旧handoff覆盖本任务指针"
  ],
  "validation": [
    "fetch/merge main、uv sync frozen dev通过；809 pytest通过（1既有warning）",
    "48 Worker测试、56 Node测试、类型检查、部署dry-run、治理及diff检查通过"
  ],
  "unverified": [
    "真实token费用和模型24条判定质量未付费实测",
    "未确认账户余额；用户判断是未充值，不将其伪装成API已核实",
    "07:26自然触发、新窗口日报与X自动发送未线上验证",
    "首页仅时间文案调整，行为测试通过；未做浏览器视觉截图验收"
  ],
  "production": {
    "source_commit": "bd6f5c307b14c9f26d5cd5fc157b168c6118d8b7",
    "artifact_commit": "527f82e86a1c8769e8aaa5a2bee128736ce19c2f",
    "edition": "2026-09-16",
    "generated_at": "2026-09-16T00:36:20.538116Z (previous edition unchanged)",
    "worker_version": "341dd1ba-4355-42c9-93dc-4133295b53e7; health still08:30",
    "verified_at": "2026-09-16 12:46 Asia/Shanghai; source/edition previous deployment evidence, Worker health refreshed"
  },
  "blockers": [
    "线上模型余额需用户自行充值；本次不充值、不调用付费模型、不清空发送记录"
  ],
  "next_action": "PR检查通过后请用户授权合并与协调部署Worker/main，再验证健康端点、实际cron、日报数据及缓存指标；历史08:00刊期重刊要显式保留旧窗口。",
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

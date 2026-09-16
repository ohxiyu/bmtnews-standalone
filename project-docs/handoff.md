# 当前交接

这里只维护一份当前状态。历史事实移入 [发布记录](releases/0.2.0.md)，待办放入 [backlog](backlog.md)。以下 JSON 是唯一 Current execution pointer；文字、聊天与旧发布记录不得替代它。

<!-- execution-pointer -->
```json
{
  "goal": "PR91合并部署、旧窗口重刊与线上去重验收",
  "issue": "https://github.com/ohxiyu/bmtnews-standalone/issues/92",
  "owner": "Codex / morning-ai-release",
  "branch": "agent/morning-ai-release",
  "last_verified_commit": "169d689fdca69be3e32f225dab23d2ebf1c37f7f",
  "pr": "pending",
  "completed": [
    "用户本轮明确授权合并部署；PR91必需检查全部通过，合并169d689",
    "部署Worker c07b2764-9cde-47e6-a66f-21da61a83e04，保留vars/Secrets/DO，显式cutoff7",
    "health/ready通过，实际schedules API确认三组新cron；07:26启动、07:00截止",
    "触发35059398372重刊2026-09-16，显式保留历史cutoff8",
    "35059398372成功重刊；生产Pages 7d0100ec成功，首页/中英详情/API均14条，前三条不同事件且CoinEx仅1条",
    "Crypto10/AI科技2/政策2；Telegram成功发送1条更新版，X因旧rank-only状态安全暂停，未清空记录",
    "原任务分支和工作目录在核验祖先及干净状态后清理，代码保留main"
  ],
  "unfinished": [
    "提交本次证据PR（仅文档，待合并）",
    "今天X历史身份需人工核对后另行授权处理，不自动重发或重置",
    "不覆盖PR89/81/77/68的分支；这些旧证据PR不能覆盖当前指针"
  ],
  "validation": [
    "823pytest、48Worker测试、类型/dry-run/治理通过",
    "GitHub test/analyze/governance/Pages全部通过后才合并PR91",
    "Worker health/ready和schedules API线上核验通过",
    "生产API generated_at=2026-09-16T05:27:38.865023Z；14个不同URL，前三event_id互异",
    "首页/summary-zh/summary-en HTTP200且当日14条、类别10/2/2一致",
    "日报去重48条、最终审计合并1条，2轮审计通过；新模型deepseek-flash真实调用成功，无截断/格式失败日志"
  ],
  "unverified": [
    "明日07:26自然触发和长期token节省比例未观察",
    "Telegram手机端收件未人工确认；X本期因旧记录缺少身份暂停",
    "部分RSS源404/403存在，但未阻断出刊；本次不扩大范围更改信息源"
  ],
  "production": {
    "source_commit": "169d689fdca69be3e32f225dab23d2ebf1c37f7f",
    "artifact_commit": "4588cd99ff7d0d3cbddf778f81ab837e63909884",
    "edition": "2026-09-16",
    "generated_at": "2026-09-16T05:27:38.865023Z",
    "worker_version": "c07b2764-9cde-47e6-a66f-21da61a83e04",
    "verified_at": "2026-09-16 13:31 Asia/Shanghai API/HTML/Pages/Worker verified"
  },
  "blockers": [
    "本期X旧序号记录与重排榜单不能安全映射；保留发送历史，需单独人工核对"
  ],
  "next_action": "审阅合并Issue92部署证据PR。下一期观察07:26自然启动、缓存复用；本期X如需恢复先核对已发内容再授权，不清空记录、不盲重发。",
  "states": {
    "code": "complete",
    "tests": "complete",
    "pr_merged": "complete",
    "deployed": "complete",
    "production_verified": "complete"
  },
  "evidence": "project-docs/releases/2026-09-16-morning-ai-rollout.md"
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

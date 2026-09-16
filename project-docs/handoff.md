# 当前交接

这里只维护一份当前状态。历史事实移入 [发布记录](releases/0.2.0.md)，待办放入 [backlog](backlog.md)。以下 JSON 是唯一 Current execution pointer；文字、聊天与旧发布记录不得替代它。

<!-- execution-pointer -->
```json
{
  "goal": "记录PR87合并部署与重刊阻塞，继续诊断语义去重失败",
  "issue": "https://github.com/ohxiyu/bmtnews-standalone/issues/88",
  "owner": "Codex / x-top3-release",
  "branch": "agent/x-top3-release",
  "last_verified_commit": "bd6f5c307b14c9f26d5cd5fc157b168c6118d8b7",
  "pr": "https://github.com/ohxiyu/bmtnews-standalone/pull/89",
  "completed": [
    "确认生产drip_items=4覆盖digest模式max_items=3，改生产配置和模型默认值为3",
    "诊断今日CoinEx关停三篇重复：预筛same_thread两两false，三个event_id不同",
    "补充生产配置前三条集成测试与旧已发记录保留测试",
    "按用户追加请求补齐榜单跨组核查、补位再核查及有界短版兜底",
    "低信号保底重新经过历史/事件/配额检查，不复活已被去重剔除的达标条目",
    "X前三条绑定有序新闻身份；重排或旧rank-only已发队列暂停，损坏状态不再清零",
    "检查评分排序和分类配额；修复编辑重复URL入口、最终排序与运行报告指标",
    "PR87在test/analyze等全部通过后合并；本地785测试及治理复测通过",
    "main Cloudflare Pages部署成功：fb6f0ff7-5623-474f-bd77-afc6ecbfbfff",
    "正式Daily Edition重刊及一次重试均失败；未写入gh-pages，X已发第1条记录保留"
  ],
  "unfinished": [
    "诊断早期topic_dedup两次重试仍失败的底层原因；当前包装异常抹去了原因",
    "修复并通过PR检查后重新发布2026-09-16，核验榜单跨组去重和配额",
    "今日旧X队列缺少selection_keys，新代码将暂停剩余推送，禁止清空或猜测已发映射"
  ],
  "validation": [
    "uv sync --frozen --extra dev成功；785 passed，1既有warning；治理与diff检查通过",
    "PR87 required checks成功；合并SHA bd6f5c307b14c9f26d5cd5fc157b168c6118d8b7",
    "公开API仍为2026-09-16 00:36:20.538116Z的14条旧数据，前三条重复仍存在"
  ],
  "unverified": [
    "未完成新榜单数据生产验收；不能把Pages部署成功当作数据重刊成功",
    "无法从当前日志区分模型服务异常和响应结构校验异常；报告显示topic_dedup存在成功计量调用",
    "新日期X自动发送尚未观察"
  ],
  "production": {
    "source_commit": "bd6f5c307b14c9f26d5cd5fc157b168c6118d8b7",
    "artifact_commit": "527f82e86a1c8769e8aaa5a2bee128736ce19c2f",
    "edition": "2026-09-16",
    "generated_at": "2026-09-16T00:36:20.538116Z (unchanged edition from previous source)",
    "worker_version": "Pages fb6f0ff7-5623-474f-bd77-afc6ecbfbfff; dispatcher not changed / unknown",
    "verified_at": "2026-09-16 12:36 Asia/Shanghai"
  },
  "blockers": [
    "Daily Edition run35055901908 attempts1/2: Semantic dedup unavailable; failure occurs in filter_items before ranking audit"
  ],
  "next_action": "先补充不泄露模型原文或凭据的结构化失败原因与针对性测试，提交修复PR；不要绕过fail-closed或无依据反复重跑。修复上线后再通过正式Daily Edition重刊并验收，保留所有发送记录。",
  "states": {
    "code": "complete",
    "tests": "complete",
    "pr_merged": "complete",
    "deployed": "complete",
    "production_verified": "pending"
  },
  "evidence": "project-docs/releases/2026-09-16-pr87-deployment.md"
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

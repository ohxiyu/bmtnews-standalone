# 当前交接

这里只维护一份当前状态。历史事实移入 [发布记录](releases/0.2.0.md)，待办放入 [backlog](backlog.md)。以下 JSON 是唯一 Current execution pointer；文字、聊天与旧发布记录不得替代它。

<!-- execution-pointer -->
```json
{
  "goal": "X只推每日榜单前三条；诊断9月16日同事件重复入榜",
  "issue": "https://github.com/ohxiyu/bmtnews-standalone/issues/86",
  "owner": "Codex / x-top3-event-dedup",
  "branch": "agent/x-top3-event-dedup",
  "last_verified_commit": "6c1687c777620f11d0cb1145bc729414fa0beeb4",
  "pr": "pending",
  "completed": [
    "确认生产drip_items=4覆盖digest模式max_items=3，改生产配置和模型默认值为3",
    "诊断今日CoinEx关停三篇重复：预筛same_thread两两false，三个event_id不同",
    "补充生产配置前三条集成测试与旧已发记录保留测试"
  ],
  "unfinished": [
    "提交PR，等待CI及合并授权",
    "去重修复建议发布前跨组语义核查；本次按检查请求只诊断，未修改去重算法或重刊"
  ],
  "validation": [
    "X专项29 passed；全量775 passed、1既有warning；uv sync frozen dev、治理和diff检查通过"
  ],
  "unverified": [
    "未真实发送X；未修改生产队列",
    "今日线上重复仍存在，未撤回已发消息或触发重刊"
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
    "无代码阻塞；合并上线需要当前授权"
  ],
  "next_action": "审核X前三条PR；另确认去重发布前核查方案及今日重刊授权。",
  "states": {
    "code": "complete",
    "tests": "complete",
    "pr_merged": "pending",
    "deployed": "pending",
    "production_verified": "pending"
  },
  "evidence": "project-docs/releases/2026-09-16-x-top3-dedup-diagnosis.md"
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

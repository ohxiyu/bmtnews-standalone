# 当前交接

这里只维护一份当前状态。历史事实移入 [发布记录](releases/0.2.0.md)，待办放入 [backlog](backlog.md)。以下 JSON 是唯一 Current execution pointer；文字、聊天与旧发布记录不得替代它。

<!-- execution-pointer -->
```json
{
  "goal": "X前三条与发布前跨组去重、配额补位和重排发送保护",
  "issue": "https://github.com/ohxiyu/bmtnews-standalone/issues/86",
  "owner": "Codex / x-top3-event-dedup",
  "branch": "agent/x-top3-event-dedup",
  "last_verified_commit": "6c1687c777620f11d0cb1145bc729414fa0beeb4",
  "pr": "https://github.com/ohxiyu/bmtnews-standalone/pull/87",
  "completed": [
    "确认生产drip_items=4覆盖digest模式max_items=3，改生产配置和模型默认值为3",
    "诊断今日CoinEx关停三篇重复：预筛same_thread两两false，三个event_id不同",
    "补充生产配置前三条集成测试与旧已发记录保留测试",
    "按用户追加请求补齐榜单跨组核查、补位再核查及有界短版兜底",
    "低信号保底重新经过历史/事件/配额检查，不复活已被去重剔除的达标条目",
    "X前三条绑定有序新闻身份；重排或旧rank-only已发队列暂停，损坏状态不再清零",
    "检查评分排序和分类配额；修复编辑重复URL入口、最终排序与运行报告指标"
  ],
  "unfinished": [
    "更新PR87并等待CI；未合并部署",
    "授权上线后才能重刊今天内容；需人工核对旧X队列映射，不能清零或自动猜测"
  ],
  "validation": [
    "最终全量785 passed、1既有warning；fetch并合并main、uv sync frozen dev、治理和diff检查通过"
  ],
  "unverified": [
    "语义判断测试使用可控模拟模型；覆盖比较不代表模型判断永不出错",
    "未真实调用模型、发送X或修改生产数据；今日线上重复尚未重刊"
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
  "next_action": "审核PR87；授权合并后使用正规发布工作流重刊，先处理旧X队列身份核对，不把代码修复等同于线上内容已修复。",
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

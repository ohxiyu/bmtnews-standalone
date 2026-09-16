# PR91 部署与重刊验收

Source commit: 169d689fdca69be3e32f225dab23d2ebf1c37f7f (PR91 merge)

Worker version: c07b2764-9cde-47e6-a66f-21da61a83e04

Deployment: 2026-09-16 用户明确授权合并部署；Worker已部署。生产Pages 7d0100ec-254e-4f25-8b69-88f34db5a433于05:29:21Z成功，对应生成物4588cd99ff7d0d3cbddf778f81ab837e63909884。

Verification: 823 pytest、48 Worker测试、类型检查、dry-run、治理通过；PR91 test/analyze/governance/Pages通过后合并。health/ready成功，Cloudflare实际schedules API确认26 23、36,46,56 23、*/5 0-15三组UTC cron，cutoff=7、first_check=07:26。未声称自然07:26已执行。

Rollback: Worker前版341dd1ba-4355-42c9-93dc-4133295b53e7，源码前版bd6f5c307b14c9f26d5cd5fc157b168c6118d8b7。回滚必须协调main与Worker截止/调度，保留Secrets、DO、缓存和已发送记录；需要时另行授权，不手动修改gh-pages。

## 当前结果

- [PR91](https://github.com/ohxiyu/bmtnews-standalone/pull/91)合并于05:24:19Z。原分支代码树与合并提交一致。
- Worker deploy使用--keep-vars并显式非敏感EDITION_CUTOFF_HOUR:7；未新增服务、套餐或清空状态。
- [重刊35059398372](https://github.com/ohxiyu/bmtnews-standalone/actions/runs/35059398372)：edition_date=2026-09-16、cutoff_hour=8、force_publish=true，保留今天历史窗口。成功，generated_at=2026-09-16T05:27:38.865023Z（北京时间13:27）。
- 初始Pages生产构建2a6b0f1f-2dff-4f55-8e31-265d8434428e对应自动生成gh-pages提交ea02bb21082c233db60d1384ecbf4c8b6be58580；最终日报构建7d0100ec-254e-4f25-8b69-88f34db5a433已成功。

## 线上内容验收（13:31 北京时间）

- [首页](https://bmt.news/)、[中文详情](https://bmt.news/2026/09/16/summary-zh.html)、[英文详情](https://bmt.news/2026/09/16/summary-en.html)、[API](https://bmt.news/api/latest.json)均为新日报，14条不同URL；HTML当日条目Crypto10/AI科技2/政策2，符合配额。
- 前三项为CoinEx关停、CLARITY法案参议院事件、币安非法石油资金指控；三个event_id互异，CoinEx仅保留1条。238候选、140分析、78过阈值、48主题去重移除、最终榜单复核再合并1条、2轮复核完成。
- 新模型deepseek-flash在完整流程实际使用，topic_dedup11次+daily_event_dedup3次全部成功，无去重格式失败日志/输出截断。比较缓存首次0命中14未命中，已保存；这不是缓存失效，新模型切换导致冷缓存。
- 本次AI输入309400、输出51840、合计361240 token；140项分析和14项扩写均冷缓存。不能把一次冷启动费用当成长期节省证明，也没有为了验缓存再次重跑付费整期。
- 报告warning来自人工重刊晚325分钟及部分RSS失败：Federal Reserve404、Wu Blockchain/Kraken Blog/Bitcoin Magazine403；0/6顶层来源完全失败，不影响本次14条成刊。未擅自扩展到来源维护。

## 推送与边界

- Telegram回执流程成功发送1条更新版（2652字符），手机端人工收件未验证。
- [X运行35059606589](https://github.com/ohxiyu/bmtnews-standalone/actions/runs/35059606589)正常结束但报告x_selection_changed：旧队列date=2026-09-16、posted.zh=[1]且没有selection_keys。安全暂停本期后续X发送，0 AI token；未把旧序号强配到新榜单，未清空或重放历史。需要人工确认旧推文身份并单独授权恢复；不宣称X已全部发送。
- Square未人为触发、清空或重排已发历史，仍由既有队列定时处理。本次不宣称Square每条新榜单已送达。
- 已核验原PR91分支是main祖先且工作区干净，按协作规则删除远端任务分支、本地工作树及分支；代码可从main/PR91恢复。证据工作树保留至文档PR合并。
- 五阶段状态记录的是已交付的应用PR91；本次Issue92证据PR是独立的仅文档交付，尚待合并。未观察下一日07:26自然触发或长期缓存收益，不将配置核验冒充自然定时验收。

脱敏诊断与修复证据见[实现记录](2026-09-16-morning-ai-economy.md)。本证据任务Issue92、agent/morning-ai-release；不把旧PR的handoff覆盖到当前指针。

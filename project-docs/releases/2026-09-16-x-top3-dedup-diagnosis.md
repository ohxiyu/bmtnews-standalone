# X前三条与9月16日去重诊断

Issue86，分支agent/x-top3-event-dedup，owner Codex。仅PR，不授权合并、部署、真实X发帖或重刊。

## X修改

生产配置使用drip，原drip_items=4；max_items=3属于digest不控制分时队列。改生产drip_items与模型默认值为3，按已发布daily_state.items顺序只发排名1–3，不重新打分，不补发第四条。保留时段作为失败重试机会，不更改排程、正文风格、币安广场或Telegram。历史posted记录不清空；已发第四条不自动删除。每语言分别计数，生产仅zh。

## 去重证据（诊断，尚未修复）

gh-pages 527f82e的9月16日api/latest.json前三条均报道CoinEx关停，分别来自The Defiant、CryptoTicker、The Block，event_id分别为evt_dec763d57c82b3ea、evt_8ae77d62973ef014、evt_18bf166f218f822d。

[日报运行35040329225](https://github.com/ohxiyu/bmtnews-standalone/actions/runs/35040329225)成功，日志显示主题去重确实移除48条，并将另3条CoinEx报道并到The Block代表项，但遗漏前两条。两站正文抓取403是证据不足风险，不是能够直接认定的去重根因。

使用已发布state中的原始title、ai_summary和ai_tags=[]重建富化前fingerprint，三个配对same_thread均为false。merge_topic_duplicates复用保守的事件线匹配作为AI候选门槛，跨簇或单例没有送入AI核查；daily_events仍复用该门槛。后续event_id也不同，因此_distinct_daily_events没有兜底。富化后字段复算仅前两条匹配，说明富化前后的证据强度也不同，不能用页面最终文本假定此前AI见过相同内容。

## 后续建议

在发布前对最终榜单做跨簇、有上限的语义核查，确认同一具体事件只占一席；使用未入榜候选补位后再核查。不要直接按公司名合并。沿用失败停止发布策略，并记录核查/合并数。该方案会增加少量AI调用，需先确认范围；本PR不实现，不声称今天重复已经修好。

若授权修复并重刊，必须处理X按rank记账与榜单重排的不一致风险，避免旧排名对应新新闻导致漏发或重发；不能清空X或Square历史。新闻事实本身未在本任务独立核实，本记录仅讨论系统内重复。

## 验证

新增生产配置集成测试：多次时段调用只发前三条，旧1–4已发记录完整保留。完整测试与治理结果见PR。

# Jev 请求调度修复

Issue: https://github.com/ohxiyu/bmtnews-standalone/issues/106

Owner Codex；branch agent/jev-rate-pacing，独立 worktree，用户要求的统一 Jev
生产接入纠正。PR105 在1b2a72d合并，运行35574566736有123条评分HTTP429，
并在去重429后停止；没有使用DeepSeek替代评分，网站早报未被覆盖。

## 调整

同一事件循环中的同凭据/模型共用队列，串行请求、最小间隔3秒。
429遵从可解析秒数或HTTP日期的Retry-After，无效值使用30秒冷却；
后续任务共享冷却，超过60秒的剩余等待直接保持未评分/停止发布，避免无限阻塞。
每个请求最多两次尝试，账户错误不重试。模型、规则、缓存版本、额度均不变。

依据：https://vercel.com/docs/ai-gateway/rate-limits
付费不能保证上游永不限流；本次不改变账户计划或购买额度。

## 验证

41项Jev测试通过，包括并发实例共享等待、429重试时间、超长冷却、无效header。
完整867项回归通过。代码complete；测试complete；合并pending；部署pending；生产验证pending。

## 正式验收

PR107合并305fe3122741641165dfb4f7bb9ec367b15e091f；CI35575078442及
CodeQL35575078513全部成功。运行35575310373，job106255696092，
报告artifact10627927320：123条新评分全部Jev成功，17条同规则缓存，
evaluation_pending=0；Jev去重4次、来源核验15次、预筛选8次成功。
预筛选有1批失败，按设计进入正式Jev评分，无替代模型评分。
DeepSeek调用只出现concept_extraction、content_enrichment和translation。
14条超过7分，去重后13条，最终待扩写12条；Crypto主轨7/9，未凑数。

评分与去重不再被429阻塞；本次在unsupported_translation而非请求错误处
停止发布。故代码/测试/合并/生产执行/统一评分验收完成，但日报新页面未发布。
latest.json重跑前后完全一致，date2026-09-21，generated_at
2026-09-20T23:28:51.024061Z。不能把统一评分验收写成整期发布成功。
未调整来源核验门槛、未新增购买或额度。后续生成内容来源支持问题独立处理。

Source commit: 305fe3122741641165dfb4f7bb9ec367b15e091f (PR107)
Worker version: unchanged; independent dispatcher not modified.
Deployment: production Actions35575310373 executed the merged code; no new Pages artifact was deployed because generation verification stopped publication.
Verification: artifact10627927320 confirms123 successful Jev analysis calls,17 cached scores,0 pending,4 Jev dedup calls and no DeepSeek scoring; public edition unchanged.
Rollback: revert focused PRs through a new reviewed PR; never edit gh-pages manually or silently restore mixed scoring.

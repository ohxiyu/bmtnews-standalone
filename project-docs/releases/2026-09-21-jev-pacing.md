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

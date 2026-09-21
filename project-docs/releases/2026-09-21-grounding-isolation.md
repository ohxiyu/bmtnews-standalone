# 来源核验与单条隔离修复

Issue: https://github.com/ohxiyu/bmtnews-standalone/issues/110

Owner Codex，agent/grounding-item-isolation，独立worktree。用户明确要求修复
unsupported_translation；承接已授权Jev正式接入与今日重跑，不改变评分模型或门槛。

## 行为

简短中英生成和Jev核验共用同一份原始标题及4000字正文，排除社区评论，
不再把旧AI摘要充当翻译来源。扩写使用同一正文准备函数。
核验保留decision、支持概率和门槛，区分unsupported、insufficient、low_confidence；
接口或格式失败仍为独立错误，不能断言内容虚假。
单条拒绝尝试一次来源内简短生成；接口故障不反复生成内容。
失败条目清除旧生成字段、记录状态；其余任务完成后从发布列表剔除失败项，
日报、归档、事件更新及分发只使用剩余项。全部失败时停止，保留原日报。
允许按现有质量规则发布短版，记录核验后数量，不降分数凑数。

仅更新生成缓存版本，评分缓存继续有效；已核验的短版中英文本可缓存。
没有增加服务、配额、认证、调度或UI改动。

## 验证

878项完整回归通过；70项相关测试通过，含生成缓存独立失效测试。
测试覆盖来源输入一致、三类拒绝、接口故障、兄弟任务完成、旧字段清理、
缓存隔离、发布列表移除及全失败禁止空版。

## 五阶段

代码complete；测试complete；合并pending；部署pending；生产验收pending。

# Jev 统一评分规则

Issue: https://github.com/ohxiyu/bmtnews-standalone/issues/104

Owner Codex，branch agent/jev-unified-rules，独立 worktree。本次为用户已授权
Jev 正式接入与日报重跑的逻辑纠正，用户明确要求移除不可用时退回 DeepSeek。

## 行为

- 启用 Jev 时，评分和分类直接使用 Jev；DeepSeek 不再先评一次分，也不能零分否决。
- 相同 impact/novelty 公式和窗口时效规则；失败最多两次请求，永久账户错误一次。
- 未评分保持 null、记录安全错误码、不缓存、不进入排序；全部评分失败停止发布。
- 预筛选失败送入正式 Jev 评分，不补其他模型分数；去重失败停止，不切换模型。
- v2 规则版本隔离历史混合评分和比较缓存。DeepSeek 仍生成扩写和翻译。
- 保留来源核验门槛，区分 HTTP、格式、unsupported_translation 等失败原因。
- 不改 UI、Quick Post、来源、调度、分发历史或额度。

## 验证与限制

最终完整 pytest 858 项通过，包含 Jev 32 项针对测试。
PR: https://github.com/ohxiyu/bmtnews-standalone/pull/105
接口错误测试使用 MockTransport，不将其当作线上准确率证明。
原日报重跑 35572996454 两次失败，线上仍为 2026-09-21 早报。
本次修复统一决策标准，不保证所有来源都能通过生成核验。

## 五阶段

代码 complete；测试 complete；PR 合并 pending；部署 pending；生产验证 pending。

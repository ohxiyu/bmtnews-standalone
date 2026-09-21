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

代码complete；测试complete；合并complete；部署complete；生产验收complete。


## 正式发布验收

Source commit: 1e171e06363368fa5b378718a05c6da234e84112（PR #111）
Worker version: 独立调度Worker未变更，本次没有Worker部署。
Deployment: gh-pages 88119b9e6d902e6a751ace6886c1c8e9239c6d6f；Cloudflare Pages 2d114c9a-802e-47cb-95a0-2878c0daaba6 success。
Verification: 2026-09-21T09:48Z，https://bmt.news/api/latest.json 与该发布产物完全一致；generated_at=2026-09-21T09:45:45.531282Z。
Rollback: 通过回退PR撤销#111后走既有发布工作流；不手动编辑gh-pages。前版产物f288eb943d8f9f525f580ea5cdb5c7ea88593794可作恢复参照。

正式运行：https://github.com/ohxiyu/bmtnews-standalone/actions/runs/35584701102 ，daily-summary成功。
报告artifact 10631049414，固定窗口2026-09-20 07:00至2026-09-21 07:00 Asia/Shanghai。
182候选；156次评分缓存命中，26次新Jev评分，evaluation_pending=0；筛选前13条达7分。
11条进入生成核验，4条剔除（translation_low_confidence 3、translation_insufficient 1）；7条通过并发布。
22次Jev来源核验，未退回DeepSeek评分。DeepSeek保留文本生成、概念提取及事件关系等原有职责。
7条全部使用核验通过的简短中英文译文（translation_only），不发布失败扩写；run report因此为warning而非全绿，error=null。
部分采集源403/GDELT429仍按既有部分失败逻辑处理，不属于本次Jev调用失败。
今日归档恰好7条，4条拒绝项ID均不存在；公开API全部具有中英文标题与摘要。
没有降低90%核验门槛、评分阈值或以低分内容补数。

文档证据跟踪Issue #112；878项全量测试、最终70项相关回归、治理检查，以及PR111 CI/CodeQL通过。

# Square 定时漏触发修复

Issue #78，owner Codex，branch agent/square-scheduler-recovery。PR77保留历史上线证据，不覆盖它的未合并工作；以后不能直接合并其旧任务指针。

## 原因与恢复

2026-09-12 11:33上海时间：最新日报14条，持久化计划14条；前三条due_at为09:22、10:53、11:18。但当天没有任何GitHub schedule运行，最近workflow_run停留在08:34。可确认是触发链没有运行，无法观察GitHub内部漏调度原因，不是Binance接口拒绝。

[恢复运行34670696550](https://github.com/ohxiyu/bmtnews-standalone/actions/runs/34670696550)成功发送1条，post_id=365743446372371，今日剩余13条；昨日7条sent记录保留。没有重置队列、强制批发或跨日补发。

## 修复

复用现有Cloudflare dispatcher和GITHUB_DISPATCH_TOKEN，使用3条Cron配置，其中共享5分钟timer覆盖Square09:00–23:30；最后23:35–23:55空返回。日报仍按原频率检查，避免每5分钟重新检查整站。两个任务独立settle，一个失败不会阻断另一个。

调用Square workflow前检查main在途任务，避免替换pending；queue_only=true避免workflow_dispatch强制重新读取日报。最终是否启用、是否到期、是否已发均由现有workflow/队列判断，保留每次1条、至少5分钟间隔和远端pending检查点。Cloudflare只触发Actions，不持有Binance Key。

无新服务、凭据、AI调用或套餐升级；会增加现有Worker与GitHub API调用，Actions可能同时收到两路触发但发送幂等。GitHub执行本身故障仍会延迟，并非实时保证。

## 验证与上线边界

Worker typecheck、types check和44项测试通过；完整Python测试773 passed、1既有warning；治理和Worker dry-run通过。现有开发依赖npm audit提示6项漏洞（2 moderate、4 high），未越界强制升级。

代码完成不等于上线。本任务默认仅提交PR，需授权后先合并workflow新增输入，再部署现有dispatcher（必须保留dashboard配置和已有Secrets），然后检查新Cron配置、queue_only运行中跳过日报读取、单条成功并写回队列。回退使用PR恢复dispatcher旧配置，保留square-queue；必要时关闭SQUARE_ENABLED。不得手改gh-pages或清空发送历史。

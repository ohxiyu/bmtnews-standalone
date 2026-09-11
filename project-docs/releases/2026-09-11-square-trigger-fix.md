# Square 触发修复

Issue #74 / Codex / agent/square-trigger-fix。

19:22 Asia/Shanghai 核查：SQUARE_ENABLED=true、Secret 名称正确，工作流 active，但运行列表为空、square-queue 不存在。证据只证明调度未触发，不能断言 GitHub 内部具体故障。

按用户“检查修复”恢复已经启用的生产分发：手动 dispatch main，一次运行 [34593750085](https://github.com/ohxiyu/bmtnews-standalone/actions/runs/34593750085)，接口确认前三条成功，队列持久化 sent 和帖子 ID：365504915650613、365504931033049、365504947907064。今天共 14 条，剩余 11 条。没有删除/重置队列或盲目重试。帖子平台可见性/审核状态仍以用户页面为准。

## 修复

- 保留原定时与手动触发，新增 main 的 Daily Edition / X Distribution 成功结束后 workflow_run 兜底。
- 校验触发仓库，始终 checkout main，不下载或执行触发任务产物；不依赖额外凭据。
- 所有入口共用原有并发锁、URL 去重以及远端 pending 检查点；增加同一上海小时共享发送额度，避免两个触发在同一小时连续发两批。
- 凌晨自动触发退出；08 点允许日报完成后首发。不改变日报、X 和网站行为，不增加模型调用或服务。
- GitHub 事件仍是 best effort，此兜底不是独立外部时钟，不保证绝对准点。若仍漏触发，下一步需单独审核现有 Cloudflare 调度器集成。

## 验证与交付

uv sync --frozen --extra dev 成功；pytest 768 passed、1 个既有弃用 warning（17.46秒）；Square专项20 passed；治理和diff check通过。代码修复仅提交 PR，未获本轮合并授权。实发恢复使用的是已合并 PR73，不代表本补丁已上线。合并后验证真实 workflow_run 触发、同小时额度及后续剩余队列。公开帖子URL的网页抓取未成功，因此仅确认接口成功与ID，未声称人工可见性验收通过。

回退：revert 此补丁或关闭 SQUARE_ENABLED；必须保留 square-queue。

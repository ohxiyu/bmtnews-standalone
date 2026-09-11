# Square 持久化随机发送计划

用户在 PR75 未合并时追加“日报只建一次队列、发送分钟不固定”，属于同一分发修复迭代；沿用 Issue #74 / agent/square-trigger-fix / PR #75，不创建并行修改分支。

## 现行方案（替代前版小时额度方案）

- 日报首次初始化或 Daily Edition、Feed Collection、Deploy Docs 成功后读取最新刊期，同步正文、源URL与排名；仅内容指纹改变时持久化。X完成只作到期检查兜底，手动任务可强制同步。
- 定时任务09:00–23:30上海时间每5分钟检查持久化小队列；最多175次/日。已有计划时不fetch gh-pages，不读取日报，不装依赖；只有到期或需同步才安装依赖进入分发器。GitHub自身调度仍可能延迟/漏跑，这不是独立外部时钟。
- 正常建队列时，在剩余09:00–23:25窗口内分段随机选择分钟，预留最后5分钟检查余量。保存exact text与due_at，重跑/同日报同步不重新抽签。
- 同一期修订只更新未发正文，保留原due_at；撤下条目移出计划。已有sent/pending/unknown/rejected/blocked记录全部保留，不自动重试。新条目补随机时间，并避开已计划时间5分钟范围。
- 每次最多发送1条，与上次尝试至少隔5分钟。不为了赶进度集中刷屏；严重延迟会剩余未发，时间不足的新条目标记unscheduled并报警，不保证无条件当天发完、不自动跨日发送。
- 旧v1状态保持editions原结构，新增plans；迁移不清队列、不重发历史。发送前仍要求remote pending检查点成功，写失败不发帖。
- 无新增模型调用、凭据、服务器或数据库。每5分钟检查会增加Actions任务启动次数；空任务已短路，不能把“无AI消耗”说成“没有计算开销”。

## 状态和验证

25项专项测试通过；全量pytest 773 passed、1个既有弃用warning；uv sync、YAML解析、治理和diff check通过。成功发送后移除计划中的重复正文，仅保留小型去重/帖子ID证据，避免队列随着已发正文积累而膨胀。未合并本PR、未部署、未触发真实发帖，未修改生产square-queue。

历史实发验收证据仍在 [前次记录](2026-09-11-square-trigger-fix.md)。该记录的小时额度/调度方案被本记录替代，不是当前目标。

## 上线与回退

### 2026-09-12 00:48 上海时间上线记录

Source commit: ae5786ff7bb0e256d5da92fd81a4b285208e7691

Worker version: 不适用，GitHub Actions分发器，未部署Worker。

Deployment: main工作流已生效，run34624039907成功。

Verification: 773 tests passed；生产空运行成功，首次随机计划和实际发帖仍待新刊验收。

Rollback: 先关闭SQUARE_ENABLED，再通过PR回退代码；保留square-queue。

- 用户明确授权“合并上线”；[PR75](https://github.com/ohxiyu/bmtnews-standalone/pull/75)已合并，源码提交 `ae5786ff7bb0e256d5da92fd81a4b285208e7691`。
- 合并前重新同步main并运行完整验证：773 passed、1既有warning，治理和diff检查通过；test/analyze/governance/CodeQL均成功。
- `SQUARE_ENABLED=true`，专用Secret名称存在，未读取密钥值。
- [生产运行34624039907](https://github.com/ohxiyu/bmtnews-standalone/actions/runs/34624039907)成功，date=2026-09-12，attempted=0、sent=0、attention=0。
- 产物 `051c45b` 中最新日报仍是2026-09-11（14条）；队列保留该日7条sent记录，未清空、重试或跨日补发。尚无plans，因此不能将本次成功空运行视为随机计划/实际发送验收。
- 待验收：9月12日日报发布后的持久化随机due_at、后续schedule仅检查队列、全期发送完成和平台展示。没有为验收创建假新闻或强制历史补发。
- 本次仅更新GitHub分发工作流，不代表Pages页面发生新部署。上线记录通过独立文档PR交付。

需用户授权合并后，在首次真实任务核对plans中的固定due_at、old sent保留、随后schedule任务不再读取日报、全期remaining降至0。无法保证的部分是GitHub调度及时性和币安平台最终审核可见性。

不要为了回退删除square-queue；计划已激活后旧版本不认识due_at，回退代码前先关SQUARE_ENABLED，避免恢复旧的批发行为。API未知结果仍需人工核对。

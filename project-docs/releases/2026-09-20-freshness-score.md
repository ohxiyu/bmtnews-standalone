# 评分阶段排除旧事复盘

Issue: [#97](https://github.com/ohxiyu/bmtnews-standalone/issues/97)
Owner: Codex / freshness-score；用户授权修改、合并上线。
PR: [#98](https://github.com/ohxiyu/bmtnews-standalone/pull/98)

## 最小改动与成本边界

现有单次评分请求中的次要考量段替换为日期窗口和时效规则，评分档位与输出
结构不变。旧事复盘且没有本期具体新进展时要求 score=0，复用现有阈值过滤。
新进展按新增事实评分，不按旧事件的重要性评分。日报含补位候选传入实际固定
窗口；其他采集评分使用包含来源发布时间的上海 07:00 固定窗口，不使用运行时钟。
没有更改采集窗口、回溯配置、页面、调度、模型、预算、重试或 AI 调用次数。
系统提示词字符数小于原版；字符数不等同 token/费用，不承诺精确费用不变。

为遵守用户“不重算缓存、不增加调用”的明确要求，本次是缓存契约的限定例外：
公共提示词指纹保持不变，运行时规则只用于本来就需要评分的 cache miss。
历史命中分数继续使用，可能保留旧误判；不声称此次已修正全部缓存或今日榜单。
后续若要求重审历史评分，必须重新确认 AI 成本授权，不应静默清缓存。

## 验证与限制

测试全为离线 stub，不调用真实模型。验证 Clarity 文章的发布时间、窗口与
零分指令被传入；模拟零分通过现有阈值被排除、新进展 8 分保留；每条未缓存
内容仍仅一次评分，缓存命中禁止创建 AI client；补跑不以当前日期替代事件时间。
这只能证明请求和过滤流程，不能证明真实模型一定识别旧事；来源正文截断或
缺日期仍可能误判。现有 823 项基线测试之外新增 3 项回归测试。
uv sync --frozen --extra dev 成功，826 项 pytest 全量通过。

## 上线方式

Python 代码由现有 Actions 从 main checkout，合并后下一次正常生产任务使用。
不手动触发日报、采集、X 或历史重算；因此今天已有榜单不变，首次实际生产
执行与模型识别效果需留待正常调度验收。无需重新部署 Pages 或 dispatcher。
回滚采用 revert 应用 PR，经检查合并，不回退或覆盖生产状态文件。

原 Quick Post 上线记录在 PR96；该分支不属于本任务，不修改或合并它。

## 2026-09-20 授权上线证据

证据文档 PR: [#99](https://github.com/ohxiyu/bmtnews-standalone/pull/99)，待审阅，不影响已合并应用代码。

Source commit: c0f37bef06f40b0a8d69a356bedc147d9374c669，PR98 于 03:39:04Z 合并。

Worker version: not changed；Pages 6bb5c964-f15b-4ddd-a0c2-8125a8fe485d，dispatcher 未修改。

Deployment: 生产 main 源码已更新，Actions 每次 checkout 后使用；本任务无常驻 Python
服务可部署，不需要 Pages 发布。首次正常生产执行尚未观察，不将合并等同运行成功。
[CI 35486990809](https://github.com/ohxiyu/bmtnews-standalone/actions/runs/35486990809)
测试与治理通过，CodeQL 和 Cloudflare Preview 同样通过。没有手动 dispatch 付费任务。

Verification: 2026-09-20T03:39:04Z 合并后 fetch 确认 origin/main 含窗口与零分规则；
核对 daily-summary.yml 的 checkout 与既有运行路径。826 项全量测试通过，合并前
再次执行 12 项窗口与新回归测试通过。模型实际效果、首次新版本生产运行仍待观察。

Rollback: 已知源码基线 55f21307ae41b134de2aa732523fde6f85474a22；经授权 revert PR98
并经 PR 检查合并。不得回滚生产内容状态或为回滚清空 AI 缓存。

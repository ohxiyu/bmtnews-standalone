# 币安广场每日分发

Issue #72；Codex；agent/binance-square。只提交 PR，不合并或上线。

已按用户要求删除取消的 Issue #71、agent/quick-post-placement 和其未提交代码；无云端资源需要清理。

## 行为

- 每天北京时间 09:17–23:17，每小时一次短任务，通常一条新闻；按剩余时间计算补发数量。
- 使用 gh-pages 的 api/latest.json 全部入选内容，不采用 X 的条数上限；中文标题、正文分段、原文来源、站点署名。
- 保留已有分析文字与限定条件，不额外调用 AI，不自动添加话题、交易暗示或图片，不截断事实。超本地安全长度或平台拒绝需要人工处理。
- 默认仅当天，未出日报不发昨天；手动 workflow_dispatch 可指定历史日期补发。
- URL 哈希 + 刊期去重，排名或标题变更不会重复发布。同日新 URL 视为新条目。
- 独立 square-queue 分支保存小型状态；在 API 请求之前先提交并推送 pending，再记录结果；推送失败不发帖、不强推。
- pending/unknown/rejected/blocked 全部需要核对，不自动重试。504 不冒充确定成功，防止重复帖。
- 工作流 Summary 显示已发、剩余、待核实和拒绝数量；有异常时任务失败提醒。GitHub 定时任务可能延迟/漏跑，不能承诺绝对准点或无条件全部送达。
- 不影响网站、X、Telegram、采集或 gh-pages 生成逻辑。

## 上线配置（尚未执行）

1. 在币安广场创作者中心创建 **专用发布** Key，不使用交易 Key。
2. GitHub 仓库 Actions Secret：`BINANCE_SQUARE_OPENAPI_KEY`。不要贴到聊天、Issue、代码或命令参数。
3. 经审核合并后，Actions Variable `SQUARE_ENABLED=true` 才启用；缺开关或密钥不会发帖。
4. 首次用真实待发新闻验收账户和权限；检查 Summary、square-queue 中 post_id 与广场页面，不能把测试通过当作实发成功。
5. 暂停：将开关设 false。不要删除 square-queue，否则去重记录会丢失。

异常恢复：先关开关，对照广场已发布记录逐条核实 pending/unknown。已发标记 sent；确认未发才从该日状态移除对应 URL 哈希记录，再手动补跑。拒绝/过长项同样先修复内容或权限，不可盲目清空队列。当前仅支持创建，修改/删除广场内容需在平台处理。

沿用现有公开仓库 Actions 和 httpx，无新增依赖、服务器、数据库或模型调用。平台和账号限制以当时政策为准，不承诺永远免费。

## 协议证据

按[币安官方发布脚本](https://github.com/binance/binance-skills-hub/blob/main/skills/binance/square-post/scripts/lib.mjs)与[正文发布脚本](https://github.com/binance/binance-skills-hub/blob/main/skills/binance/square-post/scripts/post-text.mjs)实现固定 endpoint、认证头和正文格式。官方参考代码的 504 处理并不提供帖子 ID，本实现保守标为待核实。

## 验证与交接

PR #73。uv sync --frozen --extra dev 成功；全量 pytest 764 passed、1 个既有弃用警告（10.22 秒）；Square 专项 16 passed，含本地 bare Git 远端 pending/sent 恢复；治理检查及 diff check 通过。未执行真实发布、未配置密钥或开关、未合并、未部署。
回退只暂停工作流并保留队列，不会自动删除已经发布的帖子。

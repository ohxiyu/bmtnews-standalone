# Quick Post 实时读取与刊期位置

Issue: [#94](https://github.com/ohxiyu/bmtnews-standalone/issues/94)
PR: [#95](https://github.com/ohxiyu/bmtnews-standalone/pull/95)
Owner: Codex / quick-post-immediate
Branch: agent/quick-post-immediate

## 改动与边界

Quick Post 原来只能在首页顶部展示，Git 保存后必须等待 Actions 部署。
本次允许选择刊期与新闻之间的每个位置；Pages Worker 在请求时读取 main 的
编辑注册表和固定目录的图片，绕过资产及边缘缓存。正文、位置与状态保存后，
页面重新读取即可更新，不依赖重建。日报、AI、调度与通知不变。

position 表示前面有几条日报新闻：null/0 在最前，超过当前条数放末尾；同一位置
按 pin、created_at、id 倒序。中英使用相同序号，不冒充 AI 排行，不改变排行计数。
加载历史后查询对应刊期。尚无日报的近期 Quick Post 单独显示，带明确日期。
页面初次打开、回到窗口及点击重试时读取；不在后台持续轮询。

公开字段采用白名单；草稿、未来日期、内部字段不公开。公开读取失败返回 503，
页面清除已显示的 Quick Post 并提供重试，不能将静态旧值当成实时内容。
Access 登录与 CSRF 校验、SHA 乐观并发和相同 payload 幂等保持。
图片使用内容哈希固定路径并校验字节，不接受任意 GitHub 路径或远端代理地址。

## 验证

- Worker 33 项通过，包括实时发布/编辑/停用、历史日期、未来与草稿排除、
  上游失败、位置边界、图片即时读取与哈希不匹配。
- 浏览器 390×844/1280×900 后台模拟通过草稿恢复、位置保留、冲突不丢正文。
- 浏览器 390/1280 中英/亮暗模拟通过所有插入间隙、历史加载、停用、失败/重试、
  XSS 文本安全与无横向溢出。截图位于本地 /tmp/bmtnews-quick-post-immediate-evidence。
- uv sync --frozen --extra dev、823 项 pytest、治理检查与 git diff --check 通过。
- 原有分享、PWA 与调度前端 28 项 Node 测试通过。
- 真实首页只读加载后在本地浏览器注入测试 Quick Post：390/1280 均通过，
  排行数量不变、插入点正确、无横向溢出。实际截图 live-before/after-* 留在上述本地目录，
  测试正文没有发送到后台或写入生产。
- 修复一个既有测试依赖生产 editorial.json 固定条数导致的失败：日期隔离测试
  改用固定 fixture，包含停用项与次日排除；生产注册表未修改。

## 上线与限制

代码完成与上线是不同状态，本轮未合并、未部署、未写生产内容。
现有 Production ADMIN_GITHUB_TOKEN 仍是固定仓库读取所需依赖；Preview 不应复制
生产凭据。每次实时查询会使用 GitHub API 额度；没有新存储/套餐或额度提升。
上游限流时明确失败。新 Worker 和页面必须一起发布，不能只更新一端。
真实生产邮箱会话、图片发布与停用闭环待获准部署后用用户实际内容验收。
回退通过 revert PR 和既有 Actions 发布流程，保留已有 editorial 数据与图片。

原 handoff 的 morning-ai-economy 状态属于历史快照；其发布记录仍保留，本次按
用户指定转入 Issue94，不覆盖其他未合并发布证据 PR 的分支。

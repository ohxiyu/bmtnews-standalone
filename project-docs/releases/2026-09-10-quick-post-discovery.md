# Quick Post 开发前检查与待决策边界

任务：[Issue #66](https://github.com/ohxiyu/bmtnews-standalone/issues/66)。基线：`3a035c6a191a7431660cac88daf22da3c3b42bec`，2026-09-10。唯一负责人 Codex / quick-post，分支 `agent/quick-post`，独立 worktree `bmtnews-quick-post`。当前仅完成检查与方案记录，功能代码未实现，未修改任何生产资源；交付权限为 PR，不含合并和部署。

## 1. 当前流程与数据

`/admin/` 是 Sveltia CMS 静态页面，通过用户的 GitHub fine-grained Token 写 `data/editorial.json`。保存后 `editorial-rebuild.yml` 比较当天有效编辑，改变时触发 `daily-summary.yml` 的 `force_publish`，经整期重建和 Pages 发布后才展示。它不是已经具备 D1 内容表和写入 API 的实时 CMS。

`src/editorial.py` 中 `EditorialEntry` 支持 editorial / sponsored / suppress；当前普通插入要求 URL 与标题，日期控制有效期，精选默认置顶。`ContentItem` 也要求 title 和 URL，Quick Post 无标题且来源可空，不能随意造一个标题来绕过模型。`src/web_feed.py`、`src/archive.py`、`src/api_output.py` 与浏览器信息流增强共同决定展示和归档契约。

图片由 CMS 提交到 `docs/assets/uploads`，不是 R2 上传。分类应复用 crypto-markets、crypto-exchange、crypto-protocol、crypto-security、policy-regulation、ai-technology、macro-policy，允许 Quick Post 不选分类。

## 2. 架构检查结论

| 检查项 | 现状 |
| --- | --- |
| 页面框架 | 静态 Pages / Jekyll，加原生 JavaScript 和统一 CSS；不是 React CMS。 |
| Pages Worker | `docs/_worker.js`，承担静态资源、缓存、Markdown 协商和只读 JSON API；没有管理写接口。 |
| 调度 Worker | `ops/daily-dispatcher/src/index.ts`；独立 TypeScript 包、wrangler.jsonc，负责调度/恢复/可选 OAuth。 |
| 持久化绑定 | 仓库配置只有调度用 RecoveryGate Durable Object；不能挪作内容库。未配置内容 D1、R2 或 KV。此结论来自代码，不代表已检查控制台所有资源。 |
| 认证 | GitHub Token；OAuth 默认关闭。没有证据表明已经配置 Cloudflare Access，不增加匿名写 API，不擅自更换认证。 |
| API 与上传 | CMS 自己使用 GitHub API，没有现成 `/api/admin/posts` 或 R2 上传服务可直接复用。 |
| 图片与发布速度 | Git 图片也依赖发布产物；只替换输入表单不能保证即时生效。 |
| 缓存 | 边缘与 PWA 都有缓存；不能通过只在管理员本机插入 DOM 冒充全站发布成功。 |

## 3. 接入建议与必须确定的边界

推荐产品结构：`/admin/` 默认进入极简 Quick Post，仅正文必填；URL 检测不删除原文，一张图片，分类按钮，Breaking / Pin，草稿保护与幂等提交。旧普通文章与现有编辑数据保留；广告、压稿作为次级管理功能，不再让旧多字段表单充当默认发布入口。

两种工程路径不能混为一谈：

1. **保留 Git 存储。** 扩展同一个 editorial 数据文件与现有模型、上传目录和认证，重做后台 UI；同时可优化为纯编辑重刊以避免重新分析。操作可做到很短，但 GitHub Actions 排队和 Pages 构建决定了生效速度，不能承诺立即发布。直接读取 GitHub 仍需处理上游缓存、限流和故障，不把它当作已验证的可靠实时内容服务。
2. **确认即时发布为硬要求。** 在现有 Cloudflare 内增加持久化实时编辑层，例如 D1 的统一 editorial entries（不是独立 quick_posts 表），保留 GitHub 身份验证并提供受保护写入接口；迁移现有人工编辑数据，统一读写，保留自动文章静态链路。需要明确授权资源绑定与迁移方案，提供 migration、回退及故障降级，不创建生产资源后再补文件。图片即时可用需一并解决，不能隐瞒仍等 Git 部署的限制。

待用户确认：是接受现有链路分钟级生效，还是允许引入 Cloudflare 内的实时存储。确认前不假装两条路径都已满足“发布后立即进入 Feed”，也不直接迁移生产数据。

## 4. 待实施文件范围与验收

预计涉及 `docs/admin/`、公共样式/脚本、编辑模型/归档/API/渲染、相关工作流及测试。选实时方案时再把持久化绑定、migration 和认证适配纳入 Issue 范围，禁止复用调度恢复锁的存储或秘密作为发布权限。

验收需覆盖纯正文、URL、图片、分类、Breaking、日期内置顶、中文/英文/emoji/长文本，以及空内容、非法 URL、图片失败、断网、认证过期、并发和重复提交。还需验证普通文章、旧编辑、广告/压稿、API/HTML 一致性、日期边界、缓存、手机输入/键盘/safe-area 与草稿恢复。没有真实 iPhone / PWA 设备测试就明确标为未验证。

## 5. 本次验证与交接

仓库身份、远端 main、开放 Issue/PR 与工作区已核对；创建 Issue #66 前未发现其他开放的产品开发任务，仅有依赖 PR。主站公开版本接口返回 `sha256-fc44e345414e`，构建时间 `2026-09-09T09:10:02+00:00`，这只是现有站点的版本快照，不是 Quick Post 已上线。

当前无应用代码或数据库修改，所以没有功能测试或部署结果可报告。保留原工作区未跟踪文件和旧 `agent/ui-handoff` 分支；该旧文档内容已被远端 PR #65 的治理体系取代，不应再盲目合并旧交接。

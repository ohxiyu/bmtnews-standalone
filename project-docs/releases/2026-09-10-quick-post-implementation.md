# Quick Post 与邮箱后台交付记录

Issue: [#66](https://github.com/ohxiyu/bmtnews-standalone/issues/66)
PR: [#67](https://github.com/ohxiyu/bmtnews-standalone/pull/67)
Owner: 当前 Codex / quick-post
Branch: agent/quick-post
Worktree: work/bmtnews-quick-post
Baseline: 3a035c6a191a7431660cac88daf22da3c3b42bec

## 决策与范围

用户已确认：Quick Post 替代 /s 的主入口，邮箱验证码替代 GitHub 登录，
继续 Git 存储与分钟级部署，不引入数据库和新付费服务。允许邮箱由用户单独指定；
为避免把账号写入公开仓库，实际值只在平台配置。

实现：正文为必填、可选原文/分类/配图/Breaking/Pin、Git 草稿、当前标签页
未提交草稿恢复、幂等提交和 SHA 冲突保护。旧编辑/广告/压稿可新建编辑和启停，
未知原有元数据保留。来源目录移至 /s/sources/，表单代为发起原有来源检查工作流；
来源生产变更仍需 PR 审核，不擅自自动合并。

新 quick_post 类型与旧数据在同一个 data/editorial.json 内；发布时只输出明确的
公开字段。Quick Post 位于独立首页区块及 /api/quick-posts.json，不伪装成 AI 日报排行。
仅今天与昨天内容出现在该流中，按日期、Pin、创建时间排序。
既有日报保持两期、配额与发布窗口不变。Quick Post 不自动翻译或推送 Telegram。

## 安全与发布边界

- /s、/s/*、/admin 与 /admin/*、/api/admin 及子路径在资产/缓存读取前鉴权。
- 验证 Cloudflare Access JWT 的签名、RS256、issuer、audience、时效和唯一邮箱。
  不相信未经签名的邮箱头。拒绝从 pages.dev / next 域名直接进入管理端。
- 写入要求同源 Origin、JSON 与 X-BMT-Admin 标记；所有管理响应 no-store。
- GitHub token 留在 Pages Secret，只允许固定仓库、固定 editorial 文件、固定
  图片目录和既有 source-change 工作流；不接受客户端自定仓库/分支/文件路径。
- SHA 乐观并发防覆盖；相同 Quick Post ID 与相同 payload 重试不重复创建。
- 图片限制 1 MB 和 PNG/JPEG/WebP 签名，内容哈希命名；已存在图片核验相同字节。
  上传保存后经 Git 部署，可能先于文章公开，不把上传当私有存储。
- quick_post 不进入旧 AI 重刊判定。Deploy Docs 监听 editorial.json 并单独生成流；
  各公开发布工作流都重新生成，避免之后普通部署丢失流。
- “已保存”不是“已上线”；管理台以公开 API id + updated_at 核验 Quick Post。
- 仓库本来公开，Git 草稿、内部备注和图片不是秘密存储。
- 现有 gh-pages 仍只由 Actions 更新，没有人工编辑生成状态。

## 必须先完成的平台设置

当前核验：Cloudflare CLI 已登录正确账户，Pages 项目 bmtnews 的生产分支为
gh-pages，生产与 Preview 均无后台 env vars。Access applications 和 identity providers
列表为空；organization 查询返回 403。没有修改生产资源。

1. 在 Cloudflare Zero Trust 控制台完成组织/团队初始化（仅免费方案）。
   添加 One-time PIN 身份提供者。
2. 建立同一个 Self-hosted Access 应用，保护 bmt.news/s、bmt.news/s/*、
   bmt.news/admin、bmt.news/admin/*、bmt.news/api/admin、bmt.news/api/admin/*。
   将这些路径纳入同一个应用/同一个 AUD；不要为每一路径随意配置不同 AUD。
   Allow 策略只 Include 用户指定的精确邮箱，不能只允许 One-time PIN 登录方式，
   不能 Include Everyone 或整个 gmail.com 域。可选 24 小时登录会话。
3. 在 Pages bmtnews 的 Production Variables and Secrets 配置：
   - ADMIN_ACCESS_ISSUER：精确 https://团队名.cloudflareaccess.com，不带末尾斜杠。
   - ADMIN_ACCESS_AUD：上一步应用的 Audience。
   - ADMIN_ALLOWED_EMAIL：用户指定邮箱。
   - ADMIN_GITHUB_TOKEN：仅限 ohxiyu/bmtnews-standalone 的 fine-grained token，
     Contents Read and write，以及 Actions Read and write（用于来源申请）。
     不授权 Workflows 修改；设置期限并安排轮换。
   不把这些生产绑定复制到 PR Preview。
4. 后台 token 的 Contents 权限在 GitHub 层不能细分到单文件，代码中的固定路径
   是额外限制，不应声称凭据本身只有单文件权限。不能复制 gh CLI 的广权限 OAuth，
   也不能复用 GITHUB_DISPATCH_TOKEN。把凭据直接粘贴到平台 Secret，不发聊天。
5. 以上完成后核对应用/策略/绑定名称，要求 CI test 和 analyze 都成功，才可推进
   PR 合并和 Actions 部署。缺设置时新后台故意返回 503；不能先替换线上入口再配置。

官方设置参考：
[OTP](https://developers.cloudflare.com/cloudflare-one/integrations/identity-providers/one-time-pin/)、
[JWT 验证](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/validating-json/)。

## 验证与未完成

- uv sync --frozen --extra dev 成功；完整 pytest 748 passed，1 个既有依赖弃用警告。
- 管理 Worker Node 测试 15/15：伪造/过期/错误邮箱与 AUD、编码路径、CSRF、
  SHA 冲突、重试幂等、旧字段保留、图片与来源申请等。
- 公开 Worker 12/12，分享与 PWA 25/25。
- 浏览器模拟 390×844、1280×900：正文分段、草稿恢复、冲突不丢输入、状态文案、
  无横向溢出、无页面异常。脚本 tests/check_admin_browser.mjs 不连接生产。
- 截图仅本地验收产物，不是线上截图：
  /tmp/bmtnews-quick-post-evidence/quick-post-390.png 与 quick-post-1280.png。
- 真实邮箱 OTP、真实发布、来源工作流与真实 iPhone 尚未验收。
- 本地系统 Ruby 缺 Jekyll 依赖，最终 Jekyll 构建以 Cloudflare PR Preview 验证。
- 本地 workerd 成功编译；未配置管理 Secrets 时 /s/ 和 /api/admin/state 为 503，
  公开 /openapi.json 为 200。已安装旧 workerd 不支持生产的 2026-08-21 日期，
  此本地烟测使用其支持的 2026-07-29，未修改生产兼容日期。
- Draft PR 未合并，未部署，未声明生产成功。不要用 mock 写入结果冒充线上结果。

## 上线验收与回退

上线后先匿名检查：主站可访问、/s 被 Access 登录拦截、匿名写入失败、
直接 pages.dev 管理路径失败。再由用户用允许邮箱收码登录，创建一条草稿确认
公共 API 不包含它；经用户确认发布一条实际内容，等待 API 与主页一致后再标已上线。
不要未经批准发送虚构验收新闻。验证图片、停用和冲突保护，检查通知未意外触发。

回退由获授权的整合者创建 revert PR，保留 Git 数据，不删除 quick_post 历史。
先回退网页/Worker 发布链路，确认旧管理方式所需授权，再调整 Access 策略；
绝不为了恢复功能公开写 API 或临时放行所有邮箱。

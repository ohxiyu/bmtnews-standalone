# 人工编辑层（Editorial Layer）

`data/editorial.json` 是日报的人工编辑入口：改这个文件、推送到 `main`，
`editorial-rebuild` workflow 会自动以 `force_publish` 重刊当天日报，
几分钟后网页更新。不需要任何服务器或后台系统；git 历史就是审计日志。

## 使用方式一：网页后台（推荐）

访问 **https://bmt.news/admin/**（Sveltia CMS，一个静态页面，无服务器）。
所有字段都是表单：类型下拉选择、日期用日历选择器、URL 有格式校验，
写不出坏 JSON。点「保存」即自动 commit 到 `main` 并触发重刊。

首次登录需要一个 GitHub Personal Access Token：

1. GitHub → Settings → Developer settings → **Fine-grained tokens** → Generate new token
2. Repository access 选 **Only select repositories** → `ohxiyu/bmtnews-standalone`
3. Permissions → Repository permissions → **Contents: Read and write**（其余保持 No access）
4. 生成后复制，在 /admin/ 登录界面点 **「Sign In with Token」按钮**（不是
   "Sign In with GitHub"）粘贴即可（浏览器本地保存，不经过任何第三方服务器）

> ⚠️ 登录界面上的 **"Sign In with GitHub"** 按钮走 OAuth 流程，在完成下面的
> 「一键 GitHub 授权登录」配置之前点它会得到 Not Found —— 请用
> **"Sign In with Token"**。

### 可选：一键 GitHub 授权登录（免 token）

daily-dispatcher Worker 已内置 OAuth 中转路由（`/oauth/auth`、
`/oauth/callback`），默认关闭（未配置 secrets 时返回 503）。启用步骤：

1. GitHub → Settings → Developer settings → **OAuth Apps** → New OAuth App，
   Authorization callback URL 填 `https://<worker域名>/oauth/callback`
2. 在 `ops/daily-dispatcher` 下执行
   `wrangler secret put GITHUB_OAUTH_CLIENT_ID` 和
   `wrangler secret put GITHUB_OAUTH_CLIENT_SECRET`，重新部署 Worker
3. 取消 `docs/admin/config.yml` 里 `base_url` / `auth_endpoint` 的注释并填入
   Worker 域名

注意取舍：OAuth App 的授权范围是 `public_repo`（所有公开仓库的写权限），
比只授权单个仓库的 fine-grained token **更宽**；胜在方便。个人使用推荐
继续用 fine-grained token。

### 安全边界（务必了解）

- `/admin/` 页面本身是公开的静态外壳，任何人都能打开，但**没有你的凭证
  就写不了任何东西**；仓库本来就是公开的，不存在数据泄露面
- token/OAuth 凭证只保存在你自己浏览器的 localStorage，不经过任何第三方
  服务器；换电脑要重新登录，怀疑泄露时去 GitHub 撤销即可
- fine-grained token 的实际权限 = 向本仓库推送内容。它**改不了 GitHub
  Actions workflow 文件**（需要单独的 workflow 权限），但能改 `src/` 代码
  和页面内容，所以 token 要当密码保管，建议设 90 天有效期定期轮换
- CMS 脚本从 unpkg 加载并**钉死版本号**，升级需手动改版本（防止上游被
  投毒时自动带入）；`/admin/*` 配置了 CSP，只允许连接 GitHub API 等
  白名单域名，限制恶意脚本外传凭证的通道（CSP 头由 Cloudflare 生效）
- 所有写入都是 git commit：任何误操作都可以从提交历史一键回滚

## 使用方式二：直接改文件

在 GitHub 网页端（或手机 App）直接编辑 `data/editorial.json`，把条目加进
`items` 数组并 commit 到 `main` 即可。`enabled: false` 的条目会被忽略，
可以把示例留在文件里当模板。

## 条目类型

### `editorial` — 编辑精选（自己想加的新闻）

```json
{
  "type": "editorial",
  "url": "https://example.com/story",
  "title_zh": "中文标题",
  "title_en": "English title",
  "summary_zh": "一两句中文摘要。",
  "summary_en": "Optional English summary.",
  "date": "2026-08-09"
}
```

- 插入当天日报并**置顶**，页面上带「编辑精选」标签，不参与 AI 评分（评分位显示 —）
- 会随日报一起进入 Telegram / 邮件 / webhook 推送
- `date` 指定生效的刊期（东八区刊期日）；省略则每期都会插入，一般都应填
- 至少要有 `url` 和一个标题；缺某语言时自动回退另一语言

### `sponsored` — 广告位

```json
{
  "type": "sponsored",
  "url": "https://example.com/promo",
  "title_zh": "广告标题",
  "summary_zh": "一句话描述。",
  "position": 4,
  "starts": "2026-08-10",
  "expires": "2026-08-17"
}
```

- **仅网页展示**，带明显「广告 / Sponsored」标签，不进排行榜、不受分类过滤影响、不进 Telegram/邮件推送
- 每期最多渲染 1 条；`position` 是插入在第几条新闻的位置（默认 4，即第三条之后）
- `starts` / `expires` 区间内自动上刊，过期后下一次重刊自动消失
- 链接带 `rel="sponsored"`，符合搜索引擎规范

### `suppress` — 人工压稿

```json
{
  "type": "suppress",
  "url": "https://example.com/article-to-hide",
  "date": "2026-08-09"
}
```

- 按 URL（忽略跟踪参数等）把某条新闻从当期候选中剔除；已发布的日报改完文件后会自动重刊，从页面上消失

## 生效与失败行为

- 推送到 `main` 后 `editorial-rebuild` workflow 触发 `daily-summary`
  （`force_publish=true`），完整重跑当天固定窗口并重新发布
- 文件解析是**软失败**：JSON 写坏或某条目字段无效时，该条目被跳过并在
  run report 里记录告警，绝不会阻塞日报发布
- run report 中的相关指标：`editorial_items`、`sponsored_slots`、`suppressed_manual`

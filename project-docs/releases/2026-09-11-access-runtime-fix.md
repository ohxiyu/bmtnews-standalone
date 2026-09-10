# Access 登录运行时修复

Issue #69；负责人 Codex；分支 agent/access-runtime-fix。

真实 workerd 复现：redirect:error 不受支持，公钥 fetch 抛 TypeError，
被统一捕获为 invalid_session。此前 Node fetch mock 没有暴露运行时差异。

修复仅将共享上游请求改为 manual，主动拒绝全部 3xx 并取消响应流。
JWT 签名、邮箱、AUD、issuer、有效期、CSRF 与备用域名拦截不变。
不记录令牌、不新增外部诊断服务、不新增生产依赖。

增加重定向回归测试与可用 MINIFLARE_MODULE 运行的真实 workerd 检查脚本。
上线前要求 pytest、管理接口测试、治理检查和 CI test/analyze 通过。
生产重新加载已登录页面验收，不写入虚构新闻。

回退：通过 revert PR 和现有 Deploy Docs 回退，不修改 Access 放行规则。

验证：uv sync --frozen --extra dev 成功；pytest 748 passed、1 warning (18.08s)；
Node 管理接口 16 项通过；真实 workerd 接受有效 JWT 且拒绝重定向公钥。
治理检查通过。修复 PR #70，生产验收尚未完成。

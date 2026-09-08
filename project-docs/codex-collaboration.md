# Agent 协作运行手册

长期规则只维护在 [AGENTS.md](../AGENTS.md)；本文件解释文档分工和操作顺序，不提供额外部署授权。

## 每类信息只维护一个地方

| 文件 | 唯一职责 |
| --- | --- |
| [AGENTS.md](../AGENTS.md) | 技术栈、成本/授权边界、协作禁区和交付规则 |
| agent.md / CLAUDE.md / GEMINI.md | 短入口，只指向共享规范与当前交接 |
| [handoff.md](handoff.md) | 唯一当前目标、Issue/owner、五阶段状态和下一步 |
| [backlog.md](backlog.md) | 优先级、任务范围与验收条件；不代表授权 |
| [ui-rules.md](ui-rules.md) | 导航、排版、分享和移动适配不变量 |
| [data-contract.md](data-contract.md) | 窗口、数据/缺失值、统计和去重语义 |
| [releases](releases/0.2.0.md) | 历史版本与交付证据，不作当前任务指针 |

BMTNews 的 docs/ 是公开网站源码，会触发发布。上表路径均在 project-docs/，不是另一个项目的 docs/。现有调度、来源、编辑、PWA 等领域文档保留，各自的规则从本索引链接，不复制到各 Agent 入口。

## 开工与认领

先核验仓库身份、登录、工作区、main、开放 Issue/PR 与线上版本，再在 Issue 中声明唯一编辑负责人、文件范围、独立 agent/* 分支/worktree、验收条件、依赖与非目标。若没有任务 Issue，先创建；已有认领先协调。用户的新任务优先于旧交接，但不能覆盖其他人的工作。

```bash
git status -sb
git remote -v
gh auth status
gh repo view ohxiyu/bmtnews-standalone
git fetch origin
gh issue list --state open
gh pr list --state open
```

在已核实的仓库创建独立 worktree，例如 `git worktree add ../bmtnews-task -b agent/task origin/main`，先确认名称未被占用。只改分配文件；模块重叠串行。生产发布由一个获得当前任务授权的整合负责人执行，其他 Agent 仅交付 PR。

## 五个状态和结束动作

代码完成 ≠ 测试通过 ≠ PR 合并 ≠ 部署成功 ≠ 线上验收。交接 JSON 中每个状态只能为 pending、complete 或 not_required；未验证内容必须写明，不能把上次任务的成功当成本次结果。

先 fetch/merge origin/main，运行 uv sync --frozen --extra dev、uv run pytest 和治理检查，再推送分支、建立目标 main 的 PR。应用 PR 必须同时更新交接及一份发布/验证记录；机器人依赖 PR 也由整合负责人补齐影响和验证证据后再合并，不静默绕过检查。纯说明文字变更不用伪造生产部署。

未完成时推送有效代码并保留 Draft PR，记录尚未完成、尚未验证、阻塞和准确下一步。最终 SHA 从 PR 获取；交接中的 last_verified_commit 记录上次实际核验 SHA，不能制造包含自身 SHA 的循环要求。远端 CI 状态用实时 PR 检查核验。

合并后只有在本任务明确授权时才部署。站点产物由 Actions 写 gh-pages；Worker 的合并不等于部署，详见 [调度手册](daily-dispatcher.md)。完成生产验收后，以文档 PR 更新证据，禁止直接提交 main。清理任务分支前确认其提交已经进入 origin/main，且工作区无未提交内容。

## 自动检查的范围

`uv run python scripts/check_governance.py` 检查主应用 VERSION/pyproject/uv.lock/版本文档，以及独立 Worker 的两份 package 清单；并检查统一入口、单个执行指针、字段和五阶段状态关系、治理文档及新增/修改 Markdown 的本地文件链接。

CI 传入精确 base/head SHA，检查应用、生产工作流或版本变更是否包含交接和发布证据。新增版本号须新增对应版本说明；无版本变化也应留下任务交付记录。检查不联网验证外部链接，不校验 Markdown fragment 锚点，不证明文字真实性、授权或实际线上状态；这些由 reviewer 验证。既有无关文档逐步纳入，避免一次性修订大量历史材料。

部署记录在声明 deployed=complete 时至少包含以下非空字段（Worker 未变必须写 not changed，并标出最近核验版本或 unknown）：

```text
Source commit: exact SHA
Worker version: verified ID, or not changed / unknown with reason
Deployment: production deployment ID and workflow URL
Verification: timestamp, public URLs, expected and observed values; remaining gaps
Rollback: known-good version and authorized rollback procedure
```

## 给下一位 Agent 的提示

> 接手 ohxiyu/bmtnews-standalone。先读 AGENTS.md、agent.md、project-docs/handoff.md，再核对远端 main、工作区、开放 Issue/PR、任务认领和生产版本。按 Current execution pointer 继续；如我指定新任务，先更新指针。遵守当前任务授权和成本边界，不把历史授权当作新授权。完成后更新交接和验证记录、提交 PR；未经本任务明确授权不合并或部署。未完成工作留下准确分支、提交和下一步。

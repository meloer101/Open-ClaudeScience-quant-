# Phase 13B 详细实施计划：产品形态缺口收口（GAP 第四章剩余项）

> 对应 [GAP_ANALYSIS.md](GAP_ANALYSIS.md) 第四章「对标 Claude Science 的产品形态缺口」的**剩余未完成项**，是 [PHASE13.md](PHASE13.md) 1.2–1.7 的落地细化版。
>
> 前置（均已合入或在 PR 中）：
> - **1.0 coordinator 拆分 + SubAgent**（PR #13）：`agent/loop.py` 通用 loop、`agent/run_context.py`、`agent/tools/`、`agent/helpers/`，Critic 已迁为第一个 SubAgent，manifest 有 `delegations` 段。
> - **1.1 执行沙箱核心**（PR #14）：`skills/sandbox.py` 受限子进程 + rlimit，`run_signal_code` 单资产路径已接入；macOS 上 `RLIMIT_AS` 不可用已显式降级。
>
> 命名说明：PHASE14 已被 [PHASE13.md](PHASE13.md) 预留给 5.2 Alpha 生命周期 / 5.3 信号导出,故本文件为 13B。

---

## 〇、剩余缺口盘点（对照 GAP 第四章逐条）

| GAP 条目 | 状态 | 本计划交付 |
|---|---|---|
| 4.1 多轮 session | ✅ 已落地 | §1.4 |
| 4.2 计划确认 / HITL staging | ✅ 执行前审查台核心完成 | §1.3 |
| 4.3 文献接入 | ❌ 未动 | §1.5 |
| 4.4 可扩展性（→MCP client, GAP 7.2） | ✅ 只读 MCP client 完成 | §1.1 |
| 4.4 附属：SKILL.md 对齐（GAP 7.3） | ❌ 未动 | §1.2 |
| 4.5 沙箱 | 🟡 核心完成，三个收尾项 | §1.0 |
| 4.6 远程计算 | ✅ 接口预留（local 实装 / remote stub） | §1.6 |

设计原则沿用 PHASE13：**审计链不可断裂**（每个新能力都进 manifest）、**重构先行纯 Python 可测**、**信任分层**（内置 provider vs 外部 MCP）、**显式化优先**、**不改 verdict 语义**。

---

## 一、交付物

### 1.0 沙箱收尾（承接 1.1 的三个已声明缺口，🔴 先做——它是 1.1/1.2 执行类能力的门槛）

PR #14 在 [PHASE13.md](PHASE13.md) §1.1 里诚实标注了三个未完成项，本节逐个收口：

**(a) 交叉截面 / `screen_factors` 路径接入沙箱**（最重要——这才是模型代码真正高频执行的路径）

现状：[cross_sectional_backtest.py](quantbench/engine/cross_sectional_backtest.py) 的引擎循环按 symbol 逐个调用 `compute()`（`groupby("symbol")`），调用方（[coordinator.py:641](quantbench/agent/coordinator.py) 的 `execute` 内截面工具、[tools/screening.py](quantbench/agent/tools/screening.py)、[helpers/sensitivity.py](quantbench/agent/helpers/sensitivity.py)）都经 `load_signal_function` 拿到裸 `compute` 传入引擎——完全绕过沙箱。

方案（已在 PHASE13 §1.1 中预判）：**整 panel 一次沙箱化**，不按 symbol 开子进程。
- [x] `codeexec.py` 新增 `run_signal_code_panel(code, panel, *, sandbox=None) -> pd.DataFrame`：子进程内完成「加载 compute → 按 symbol 分组逐个调用 → 拼出 `(timestamp, symbol, factor)` 三列 DataFrame」整个循环，一次进出。子进程 entrypoint 是模块级函数（`spawn` 可 pickle），内部复用引擎现有的 groupby 逻辑抽出的纯函数。
- [x] 引擎签名改造：`run_cross_sectional_backtest` 的 `compute_factor` 参数增加一个替代入口——接受**预计算好的 factor panel**（`factor_values: pd.DataFrame | None`），两者互斥。引擎内部若拿到 `factor_values` 就跳过 groupby-调用段。这样沙箱边界清晰落在「模型代码执行」与「确定性引擎计算」之间，引擎本身不感知沙箱。
- [x] 调用方切换：coordinator 截面工具 / screening / sensitivity 全部改为「先 `run_signal_code_panel` 拿 factor panel，再传引擎」。sensitivity 的多次重跑（execution 双口径、borrow 对比、中性化对比）**复用同一份 factor panel**，不重复执行模型代码——顺带把当前每次 sensitivity 都重跑一遍 compute 的浪费也消掉（一次 run 内同一份代码最多执行一次）。
- [x] 沙箱默认限额对 panel 规模放宽：新增 `SANDBOX_PANEL_CPU_SECONDS` / `SANDBOX_PANEL_WALL_TIMEOUT_S`（如 60s/120s，S&P 500 × 10 年日线的合理上界），与单资产限额分开——一个 config 常量各表一个真实场景，不共用一个"拍脑袋均值"。

**(b) 资源用量回填 manifest**（PHASE13 §1.1 的加分项，为 GAP 5.4 铺路）
- [x] `run_in_sandbox` 返回值改为携带元数据：内部记录 wall time、子进程退出码、命中的限制；通过一个轻量结构（`SandboxUsage(wall_seconds, cpu_limit_hit, ...)`）挂到线程本地或显式返回。为不破坏 `run_signal_code` 的裸 `pd.Series` 返回约定，采用**回调/收集器模式**：`run_in_sandbox(..., usage_sink: list | None)`，调用方（tools 层）传入收集器并写进 `ctx`，最终入 manifest 新段 `sandbox_usage: [{call, wall_seconds, limits}]`。
- [x] 峰值内存：子进程结束前 `resource.getrusage(RUSAGE_SELF).ru_maxrss` 随结果一起回传（macOS 单位是 bytes、Linux 是 KB——换算写清楚，别再埋一个平台差异）。

**(c) 文件系统白名单**：**明确降级为不做真目录挂载**，理由写进代码注释与 GAP：无 Docker/chroot 前提下,`_SAFE_BUILTINS` 禁 `open`/`__import__` 已在语言层阻断文件访问,子进程 cwd 切到临时目录作为纵深防御的最后一层（一行改动,顺手做）。Docker 仍是后续增量,不在本阶段。

**验收**：一个含死循环的候选因子在 `screen_factors` 里只拖死自己这个 candidate（结构化错误、其余 candidate 正常完成、run 不挂）；同一因子经 panel 路径与旧直调路径数值逐位一致；manifest 出现 `sandbox_usage`；全量测试零回归。

### 1.1 MCP client：只读外部数据工具（GAP 7.2 / 4.4 正解，🟡 高）

**范围决策**（沿 PHASE13 §1.2，本阶段只做只读）：执行类 MCP tool 需 1.0(a) 收口后按「必须经沙箱」原则另行放开，本阶段一律拒绝注册。

- [x] 依赖：官方 `mcp` Python SDK（唯一新增依赖，PHASE13 已批准）。
- [x] 配置：`PROJECT_ROOT/mcp_servers.json`（走 [config.py](quantbench/config.py) 的 PROJECT_ROOT 惯例）：`[{name, transport: {command|url}, enabled_tools: [...], allow_write: false}]`。`enabled_tools` 是**显式白名单**，缺省为空 = 一个都不注册（不是"全部"）。
- [x] 新增 `skills/mcp_adapter.py`：启动时连接各 server、`list_tools`、把每个白名单内 tool 包成 [Skill](quantbench/skills/registry.py:7)（`name=f"mcp_{server}_{tool}"`，`inputSchema` 直接透传为 params schema），注册进 [SkillRegistry](quantbench/skills/registry.py:14)。`registry.execute` 命中时转发 `call_tool`。Coordinator 无感知——工具形状与内置完全一致，[loop.py](quantbench/agent/loop.py) 不改一行。
- [x] **审计红线一**：每次调用记 `ctx.mcp_calls.append({server, tool, args, result_sha256})`，manifest 新段 `mcp_calls`（模式照抄 `delegations`，[store.py](quantbench/artifact/store.py) 加一个参数）。
- [x] **审计红线二**：`ctx.mcp_calls` 非空的 run，`run_review` 注入 `external_data_unverified` finding（severity=`info`，**不封顶 verdict**——它是来源标签不是质量缺陷；实现照抄 [report.py](quantbench/review/report.py) 现有 optional-detail finding 的模式）。
- [x] 拒绝逻辑：`allow_write: true` 或 tool 名/描述含副作用信号的,注册时直接拒绝并 warning（宁可误拒——本阶段无放行路径，执行类 tool 留到沙箱化 RPC 设计）。

**验收**：用 `mcp` SDK 自带的 stdio mock server（测试内起一个返回固定 OHLCV JSON 的极简 server）：白名单内 tool 可被 agent loop 正常调用、manifest 有 `mcp_calls` 且含 result hash、review 出现 `external_data_unverified`；白名单外 tool 调用报"未注册"；`allow_write` server 的 tool 全部拒绝注册。

### 1.2 SKILL.md 目录式对齐（GAP 7.3，🟠 低成本，与 1.1 并行）

- [x] 迁移：`skills_docs/{causal-factor-authoring,crypto-cross-sectional-workflow,reviewer-weak-triage}.md` → `skills_docs/<name>/SKILL.md`。[SkillRegistryDocs](quantbench/skilldocs/registry.py:9) 的 `load_all` 改为扫目录（兼容旧平铺 `.md` 一个过渡版本，下阶段删）。frontmatter 键不变。
- [x] 渐进披露：注入时只给 SKILL.md 正文 + 附属文件清单；新增内置工具 `read_skill_file(skill, path)`（注册进 registry,路径严格限制在该 skill 目录内——`Path.resolve()` 后必须以 skill 目录为前缀,防目录穿越）。
- [ ] skill 附带脚本：**依赖 1.0(a)**。目录里的 `*.py` 脚本经 `run_in_sandbox` 执行；1.0(a) 未合入前此项禁用（加载器发现脚本时 warning 并忽略）。

**验收**：三个 skill 迁目录后触发词匹配与注入行为不变（现有 skilldocs 测试通过）；带附属参考表的测试 skill 能被 `read_skill_file` 按需读取；`read_skill_file("x", "../../.env")` 被拒绝。

### 1.3 执行前审查台 / human-in-the-loop staging（GAP 4.2，✅ 核心完成）

本节已由 [PHASE13B_HITL_STAGING.md](PHASE13B_HITL_STAGING.md) 重新定型：HITL 的核心不是在 run 开头确认一份抽象计划，而是在昂贵回测前审查已经生成的研究 artifact（factor definition / formula / `compute()` / static validation report）。

- [x] `quantbench/agent/staging.py`：新增 `FactorSpec`、`ValidationReport`、`CostEstimate`、`StagingPolicy`、`GateDecision`、`StagingGate`，并实现 `should_stage(risk × cost)` 纯函数。
- [x] validation report 复用 `detect_lookahead(code)`，并从便宜 compute 产出的 signal/factor panel 计算 `shift`、输入列、NaN/覆盖率、输出对齐和首尾样例；不触发昂贵回测。
- [x] 单资产路径：`run_signal_code(...)` → staging gate → `run_vectorized_backtest(...)`；若用户改 code，只重跑一次便宜 compute。
- [x] 截面路径：`run_signal_code_panel(...)` → staging gate → `run_cross_sectional_backtest(...)`；config 覆盖在昂贵回测前重新归一化。
- [x] API：run 状态新增 `awaiting_confirmation`（由 `staging_pending.json` 表达）；新增 `POST /api/runs/{id}/staging/confirm`，body 携带 `{overrides: {code?, config?}}` 推进阻塞中的 run。
- [x] Web：`StagingReviewPanel` 展示三层 factor spec + validation report，并支持编辑 code / `cost_bps` 后确认。
- [x] 审计：manifest 新增 `staging` 段，包含 `factor_spec`、`validation_report`、`gate_decision`、`overrides`、`staged_diff`。

**验收**：含 lookahead 嫌疑的因子在昂贵回测前停在审查台；简单干净因子默认放行但仍写入 manifest；API `awaiting_confirmation` 可被 `/staging/confirm` 推进；`tests/test_phase13b_staging.py` 覆盖策略、report、diff 与 API confirm。

### 1.4 多轮对话式 session（GAP 4.1，🟡 本阶段最大产品跃迁,依赖 1.3）

- [x] Session 模型（新 `quantbench/api/session.py` + artifact 持久化）：session = `{session_id, turns: [{turn_index, user_message, run_id|None, summary}]}`,存 `runs/_sessions/{session_id}.json`（复用 artifact 目录惯例,不引数据库）。
- [x] 上下文延续：新一轮的 messages 组装时,在 system 之后注入「本 session 已有 run 的结构化摘要」（每 run：hypothesis、verdict、关键 metrics、run_id）——**不是**塞历史 messages（[execute() docstring](quantbench/agent/coordinator.py:641) 已记录过全量历史会污染 skill 匹配与 context 的顾虑）。
- [x] 追问语义：「把手续费改成 10bps 再看看」→ Coordinator 在有 session 上下文时注册 `fork_previous_run(run_id, modification)` 工具（复用 [build_fork_config](quantbench/library/fork.py) 与 fork lineage）,而不是靠 prompt 猜——工具化的路由可测、可审计。
- [x] API：`POST /api/sessions`、`POST /api/sessions/{id}/turns`（返回 run_id,SSE 复用 [stream_run_events](quantbench/api/server.py:146)）、`GET /api/sessions/{id}`。
- [x] Web（[App.tsx](web/src/App.tsx)）：v1 做「对话流 + run 卡片」的最小版——消息列表 + 每轮内嵌现有 run 详情组件;1.3 的计划卡片嵌入此流。样式增量,不重写现有页面。
- [x] **溯源**：manifest 记 `session_id` + `turn_index`;session JSON 是完整 artifact。

### 1.4.1 用户长期记忆（Session 之后的记忆闭环，✅ 已落地）

- [x] 存储：`memory/user/*.md` 一条事实一个文件，frontmatter 记录 `type` / `description` / `provenance` / `created_at` / `confidence` / `fields`，`INDEX.md` 作为常驻小集。
- [x] 注入：Coordinator 将 `INDEX.md` 注入 system prompt；默认偏好只预填 staging gate 默认值，不静默改研究假设。
- [x] 审计：manifest 新增 `applied_memory_defaults`；记忆写/改事件记录到 `memory_events`。
- [x] 晋升：`memory_consolidation` 复用 `SubAgent` 抽象，单 session 候选只记录不晋升，跨 session 重复达到阈值才写入/更新长期记忆，并经 SSE `memory` 事件会话内可见。

**验收**：Web 起 session,第一轮跑动量因子,第二轮「加上 sector 中性化再跑」→ 不重述前情,系统经 `fork_previous_run` 定位上一 run 重跑,两张 run 卡片同流;session JSON 是完整 artifact;library 按 session_id 能拉出这组 run。

### 1.5 文献接入（GAP 4.3，🟠 差异化价值,SubAgent 第四个实例）

- [ ] 文献 SubAgent：输入论文全文文本（v1 只接受**本地 PDF/纯文本路径**,不做 arXiv 爬取——网络获取属数据源问题,留给 MCP）→ 提取因子定义 → 产出 `{factor_name, compute_code, paper_claims: {sharpe, ic, universe, period}, citation}`。PDF 解析用已装依赖可及的最轻方案（`pypdf` 级;若需新增,在 PR 里单独声明）。
- [ ] 产出走标准流程：`compute_code` 直接喂 `run_from_factor`（[coordinator.py:570](quantbench/agent/coordinator.py)）,享受全套沙箱/回测/review/critic。
- [ ] 复现对比表：research note 增「论文声称 vs 复现」段;差异大时注入 `replication_gap` finding（severity=`info`——对不上是研究发现,不是缺陷）。
- [ ] 溯源：manifest 与实验记录加 `source: {type: "paper", ref, path}`;library 支持按来源检索。

**验收**：本地 fixture 论文（自造一篇含明确因子定义的短文即可,不依赖真实 PDF 版权文件）→ SubAgent 产出可跑的 compute → 完整 run 走完 → note 含引用与对比表 → manifest `delegations` 有该委派、`source` 段齐全。

### 1.6 远程计算接口预留（GAP 4.6，🟠 最后收尾,不实装）

- [x] `ExecutionBackend` 协议（`local` / `remote`），[execution_backend.py](quantbench/agent/execution_backend.py)；`screen_factors` 的 fan-out（[coordinator.py](quantbench/agent/coordinator.py) `build_screen_factors_skill`）经 `get_execution_backend().map(...)` 派发。`local` = 现状 `ThreadPoolExecutor`（完成序返回，下游本就排序，顺序非承载语义）；`remote` 抛 `NotImplementedError`（明确未实装）。
- [x] config 留 `EXECUTION_BACKEND`（默认 `"local"`，可经 `QUANTBENCH_EXECUTION_BACKEND` env 切换）。

**验收**：默认行为逐字节不变（既有 screen 测试零回归）；配置切 remote **失败前不执行任何任务**、抛清晰 `NotImplementedError` 而非静默回退。

---

## 二、审计接入总览

| 能力 | manifest 新段 | Reviewer finding | 对 verdict |
|---|---|---|---|
| 沙箱用量 (1.0b) | `sandbox_usage` | — | 无 |
| MCP 调用 (1.1) | `mcp_calls` | `external_data_unverified` (info) | 无 |
| 执行前审查台 (1.3) | `staging` | — | 无 |
| Session (1.4) | `session_id` + `turn_index` | — | 无 |
| 用户长期记忆 (1.4.1) | `applied_memory_defaults` + `memory_events` + `delegations` | — | 无 |
| 文献来源 (1.5) | `source` | `replication_gap` (info,可选) | 无 |

不新增统计检查、不动 [determine_verdict](quantbench/review/report.py) 阈值——全部是留痕与来源标签。

---

## 三、依赖与落地顺序

```
1.0 沙箱收尾 ──┬──> 1.1 MCP(执行类,本阶段不放开)
               └──> 1.2 skill 附带脚本
1.1 MCP(只读) ──────────────── 独立
1.2 SKILL.md(前两点) ───────── 独立
1.3 执行前审查台 ──> 1.4 session
1.5 文献 ──────────────────── 依赖既有 SubAgent,独立
1.6 远程接口 ──────────────── 最后
```

建议顺序：**1.0 → 1.1 与 1.2 与 1.3 并行 → 1.4 → 1.5 → 1.6**。每项独立成 PR、独立可测、合并即有价值;1.4 是唯一的大 PR,拆 API/后端与 Web 两个提交。

---

## 四、明确不做

- 不做执行类 MCP tool 的放开（沙箱覆盖面收口后另评）;不做 QuantBench-as-MCP-server。
- 不做 arXiv/SSRN 在线抓取（v1 本地文件;在线获取走 MCP 数据源路线）。
- 不引入数据库（session 用 JSON artifact）;不引入 Agent 框架、不引入 Docker（均已在 PHASE13 论证）。
- 不做「人工确认永远默认打断」的破坏性默认（默认由 staging 策略函数按风险×成本决定）。
- 不动 5.2/5.3（Alpha 生命周期/信号导出,PHASE14）。

---

## 五、验证

- 每项各自的单测（`test_phase13b_*.py`）+ 全量 `uv run pytest -q` 零回归。
- 1.0(a) 必须有「screen 中单 candidate 死循环不拖垮批次」的集成测试——这是本阶段最重要的一条安全性回归。
- Golden runs 在 1.0(a) 的 panel 路径切换前后逐字节比对（同 PHASE13 1.0 的标准）。
- 手动端到端一次：Web session 两轮（含 fork 追问 + 计划卡片确认),检查 manifest 五个新段齐全。

---

*2026-07-04 已回填本文件与 [GAP_ANALYSIS.md](GAP_ANALYSIS.md) 第四章 session 勾选项。*

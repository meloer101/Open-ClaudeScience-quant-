# Phase 13 详细实施计划：对标 Claude Science 的产品形态 + 架构地基

> 对应 [GAP_ANALYSIS.md](GAP_ANALYSIS.md) 第四章「对标 Claude Science 的产品形态缺口」与第七章「架构决策」，落在第六节「第四优先级：产品形态与生产化」。
>
> 前置：Phase 10 统计护栏、Phase 11 数据地基、Phase 12 回测现实性均已就绪。本阶段**不依赖新数据源**，是纯工程与产品形态层——把「一句话→一次 run 的批处理研究工具」演进为「可对话、可确认、可扩展、可安全执行的研究平台」。
>
> **范围（已决策 2026-07-03）**：本阶段覆盖 4.1–4.6 六个产品形态缺口 **+** 支撑它们的架构地基 7.1（coordinator 拆分 + SubAgent）/ 7.2（MCP client）/ 7.3（SKILL.md 对齐）。**不含** 5.2 Alpha 生命周期 / paper tracking 与 5.3 信号导出（留待 Phase 14）。沙箱（4.5）方案已定为**受限子进程 + rlimit**，不引入 Docker。

---

## 〇、为什么是这一层、现状有多「批处理」

Phase 10–12 让「Sharpe 是不是幸运儿 / 方向是否可信 / 是不是建模假设吹出来的」这三个问题能被回答——**结论的可信度**已经建起来了。但系统的**形态**仍是一个批处理器，与 Claude Science 那种「研究对话」的产品体验有本质差距。当前有四处结构性限制：

1. **一句话 → 一次 run，无上下文延续。** [coordinator.py:1440](quantbench/agent/coordinator.py) 的 `execute()` 每次都新建 `_RunContext`、新建 messages、跑完即弃。Fork（[library/fork.py](quantbench/library/fork.py)）部分弥补，但「把手续费改成 10bps 再看看」「刚才那个因子加上 sector 中性化」这类**同上下文追问**做不到——每次都要用户把前情重新描述一遍。

2. **无计划确认，模型说了就做。** [coordinator.py:1490](quantbench/agent/coordinator.py) 起的 `for _ in range(MAX_STEPS)` 循环直接执行工具调用。VISION 5.1 设计的「先出研究计划、暂停确认数据范围/成本假设、再执行」从未落地。用户无法在昂贵的 `screen_factors` 跑起来之前干预，也无法审计「模型说要做什么 vs 实际做了什么」。

3. **工具集是内置固定集合，用户无法安全扩展。** [_build_registry](quantbench/agent/coordinator.py:323) 硬编码注册全部工具。用户想接自己的数据源（内部数据库、数据商 API）无路可走。Claude Science 是 60+ connectors 的生态。

4. **执行「安全」形同虚设。** [codeexec.py](quantbench/skills/codeexec.py) 号称沙箱，实为**同进程 `exec()`**（[codeexec.py:31](quantbench/skills/codeexec.py)）+ builtins 黑名单——模型写个 `while True` 或 `[0]*10**10` 就能拖垮整机，连 subprocess 隔离都没有。VISION 技术选型写的 "subprocess (MVP) → Docker" 连第一步都没走。这是生产化前**必须还的债**，也是开放「用户可扩展工具 / skill 附带脚本」的前置门槛。

而这四处背后共用一个**架构风险**：[coordinator.py](quantbench/agent/coordinator.py) 已 **2057 行**，agent loop、run 生命周期、业务工具构建三件事糊在一个文件里。任何产品形态改动（多轮、确认、MCP 注入）都要动这个巨型文件，回归风险随行数线性上升。所以本阶段**第一步是重构，不是加功能**（7.1）。

好消息：这些缺口的地基**大部分已经在手边**——
- 系统**已经在裸写多 agent**：[run_critic](quantbench/review/critic.py:44) 就是「独立 LLM + 独立 prompt + 结构化返回」的 sub-agent（[_run_critic_for_context](quantbench/agent/coordinator.py:784)），`screen_factors` 就是 fan-out 并发。缺的不是框架，是把已有模式**提炼成抽象**。
- MCP 的形状与现有 skill **天然对齐**：[SkillRegistry.schemas()](quantbench/skills/registry.py:21) 输出的就是 function-call schema，MCP tool 的 `name / description / inputSchema` 与之一一对应。[registry.execute()](quantbench/skills/registry.py:34) 就是现成的调度入口。
- 审计基建已就位：`injected_skills` 已经在 manifest 里记录（[coordinator.py:1564](quantbench/agent/coordinator.py)、[store.py:95](quantbench/artifact/store.py)），MCP 调用、计划 diff 只需复用同一模式。

### 设计原则（承接 Phase 10/12）

- **审计链不可断裂。** 这是不引入 Agent 框架的根本原因（GAP 7.1）：框架会在调用链里插入隐式重试/状态/prompt 拼接，manifest 里出现解释不了的部分，破坏「每个影响结果的东西都进 manifest」的核心承诺。本阶段每一个新增能力（SubAgent 委派、MCP 调用、计划确认、多轮上下文）**都必须在 manifest 留痕**。
- **重构先行、纯 Python 可测。** 编排逻辑（agent loop、SubAgent 委派、计划两阶段）属 VISION 第十一节「必须绝对正确的基础设施」，是普通可测 Python，不是模型创意。先重构出可测边界，再往里填功能。
- **信任分层。** 内置一等 provider（有质量校验）与外部 MCP tool（untrusted）**信任等级不同**：用了外部 MCP 数据的 run 由 Reviewer 打 `external_data_unverified` 警告，verdict 逻辑区别对待。安全边界（沙箱）落地前，不开放任何有副作用/执行类的外部能力。
- **显式化优先。** 计划确认、执行假设、外部数据来源——凡影响结果的，一律搬到用户看得见、Reviewer 审得到的地方（承接 Phase 12 的同一原则）。
- **不改既有 verdict 语义。** 本阶段是形态层，不新增统计检查、不动 `determine_verdict` 阈值；只新增 `external_data_unverified` 这类**来源可信度**标签。

---

## 一、交付物

按依赖顺序编号（落地顺序见第四节）。重构（1.0）是所有产品功能的地基，先行。

### 1.0 coordinator.py 拆分 + SubAgent 抽象（GAP 7.1，🔴 重构先行，纯重构不加功能）

**动机**：2057 行的单文件是真正的架构风险。后续每个产品功能都要动 agent loop，先把它拆出可测边界。

**拆分目标**（纯重构，行为零变化，靠既有测试 + golden runs 锁定）：
- [ ] `agent/loop.py` — 通用 agent loop：messages 组装、`llm.chat(tools=…)`、tool_call 分发、MAX_STEPS 护栏、`on_event` 流式钩子（现 [coordinator.py:1490-1535](quantbench/agent/coordinator.py) 的循环体）。不含任何业务工具知识。
- [ ] `agent/run_lifecycle.py` — run 生命周期：artifact/manifest 写入、事件、warnings 收集、`_RunContext`（现 [coordinator.py:299](quantbench/agent/coordinator.py)）。
- [ ] `agent/tools/` — 业务工具构建：把 [_build_registry](quantbench/agent/coordinator.py:323) 的每个 `_fetch_ohlcv`/`_run_signal_backtest`/`_run_cross_sectional_backtest`/`_screen_factors`/`_optimize_portfolio` 拆成独立模块，注册逻辑集中。
- [ ] `Coordinator`（[coordinator.py:1351](quantbench/agent/coordinator.py)）瘦身为「装配 + 编排入口」：`run` / `run_from_factor` / `run_fork` / `optimize_portfolio` 只做装配，循环体委托 `agent/loop.py`。

**SubAgent 抽象**（约 150 行，`agent/subagent.py`）：
- [ ] 定义：
  ```python
  @dataclass(frozen=True)
  class SubAgent:
      name: str
      system_prompt: str
      registry: SkillRegistry          # 工具子集（可为空 = 纯推理）
      max_turns: int                   # 预算护栏
      output_schema: dict              # 强制结构化返回（JSON schema）
  ```
- [ ] 父 Coordinator 把「委派给 SubAgent」当成**一次普通 tool 调用**：跑一个受限的 agent loop（复用 1.0 的 `agent/loop.py`），到 `max_turns` 或产出符合 `output_schema` 的结果即返回。
- [ ] **审计**：每次委派记入 manifest（`delegations: [{name, input, turns_used, output_hash}]`），复用 `injected_skills` 的记录模式（[store.py:95](quantbench/artifact/store.py)）。
- [ ] **迁移验证**：把现有 Critic（[run_critic](quantbench/review/critic.py:44)）迁为第一个 `SubAgent` 实例，证明抽象成立且不改变 Critic 行为（golden run 的 critic_report.json 前后一致）。

**验收**：全部既有单测 + Phase 10 建立的 golden runs 评测集在重构后**逐字节等价**（verdict、critic_report、manifest 关键字段不变）；`coordinator.py` 主文件降到 ~500 行以内；Critic 作为 SubAgent 跑通，manifest 出现 `delegations` 段。

---

### 1.1 执行沙箱：受限子进程 + rlimit（GAP 4.5，🔴 生产化前必还的债，解锁 1.2/1.3 的执行类能力）

**动机**：当前 [codeexec.py:31](quantbench/skills/codeexec.py) 是同进程 `exec()`，模型代码能耗尽 CPU/内存、写任意文件。沙箱是开放「外部执行类 MCP tool」和「skill 附带脚本」的前置门槛，故排在扩展性（1.2/1.3）之前。

**方案（已决策）**：`subprocess` 隔离 + POSIX `resource.setrlimit`，**不引入 Docker**——participation cap 式的「显式粗方案覆盖 80%」原则同样适用于安全边界。

**代码改动**：
- [x] 新增 `skills/sandbox.py`：把 `compute()` 执行搬进子进程（`multiprocessing` `spawn` context，非 `fork`——子进程是全新解释器，不继承父进程的线程/锁/连接池）。
  - 子进程 entrypoint（`_run_in_child` → `_apply_rlimits`）用 `resource.setrlimit` 设 `RLIMIT_CPU`（CPU 秒）、`RLIMIT_AS`（地址空间/内存）、`RLIMIT_FSIZE`（写文件大小）；父进程侧 `process.join(wall_timeout_s)` 做 wall-clock 兜底，超时后 `terminate()`→`kill()`。**已知平台差异**：`RLIMIT_AS` 在 Linux 上生效，在 macOS/Darwin 上内核拒绝 `setrlimit` 到任何有限值（即使从 unlimited 往下调），`_apply_rlimits` 逐项独立设置、某一项在当前平台不可用不影响其余项生效，不静默假装内存上限已生效。
  - **网络隔离**：沿用既有 `_SAFE_BUILTINS`（[codeexec.py](quantbench/skills/codeexec.py)）禁 `__import__`——子进程内代码同样无法 `import socket` 等，天然无网络能力，未额外新增机制。
  - **文件系统白名单**：未做真正的只读/只写目录挂载（无 Docker/chroot 前提下成本过高）；退化为「子进程内代码本就无法 `open()`（builtins 黑名单）」这一等价保证。这是本阶段**明确未完成**的一项，非本次验收范围。
  - 数据传递：走 `multiprocessing.Queue`（底层是 pipe），父子间直接传 `pd.DataFrame`/`pd.Series` 对象（pickle），不落临时文件。[run_signal_code](quantbench/skills/codeexec.py:17) 签名不变（两个位置参数不变，新增可选关键字参数 `sandbox: SandboxConfig | None`），内部改走 `run_in_sandbox`。
- [x] 资源上限写入 config（`SandboxConfig(cpu_seconds, mem_mb, wall_timeout_s, max_write_mb)`，默认值见 `quantbench/config.py` 的 `SANDBOX_*` 常量），默认值保守。
- [x] 超时/超限 → 结构化错误（`SandboxError`，一个 `RuntimeError` 子类；Coordinator 既有的 `except Exception` 工具失败处理已能捕获并转成 `{"error": ...}`，无需改 Coordinator），run 不崩溃。
- [ ] （加分，未做）资源用量（峰值内存、CPU 秒、wall time）回填 manifest——`run_signal_code` 的返回类型是裸 `pd.Series`，回填需要改变调用约定，留作后续增量，不阻塞本阶段核心验收。
- [ ] **未覆盖**：交叉截面/`screen_factors` 路径经 `load_signal_function` 返回的 `compute` 由引擎按 symbol 逐个调用（[cross_sectional_backtest.py](quantbench/engine/cross_sectional_backtest.py) 的 `groupby("symbol")` 循环），本次只把 `run_signal_code`（单资产路径）接入沙箱。按 symbol 粒度逐个开子进程的开销在大 universe 下不可接受，需要先决定「整 panel 一次性沙箱化」的设计再落地，留作后续增量。

**验收**：
- [x] 合成一个死循环因子（`while True: pass`）→ 命中 CPU rlimit（`cpu_seconds=1`）、抛出 `SandboxError`、run 不挂（[tests/test_phase13_sandbox.py](tests/test_phase13_sandbox.py)）。
- [x] 合成一个内存炸弹（`np.zeros((400_000_000,))`）→ 在 `RLIMIT_AS` 可用的平台（Linux）命中限制；在不可用的平台（macOS/Darwin）测试显式探测并跳过、注明原因，而非误报通过。
- [x] wall-clock 兜底独立验证：`cpu_seconds` 故意设得比 `wall_timeout_s` 宽松，仍在 `wall_timeout_s` 内被终止，证明父进程的 `join(timeout)` 本身在起作用，不是靠 rlimit 侥幸兜底。
- [x] 一个正常因子行为与旧路径**数值等价**：沙箱化的 `run_signal_code` 与未沙箱化的 `_execute_signal_code` 对同一输入产出逐位相同的 `Series`；全量既有测试套件（含 golden runs、screening、monitor pipeline）零回归。
- [ ] 子进程无法写数据目录、无法读 artifact 目录外的文件——未做真正的文件系统白名单（见上），此项验收未覆盖。

---

### 1.2 MCP client：接入外部数据工具（GAP 7.2 = 承接原 4.4，🟡 中高）

**动机**：解决「用户无法安全添加可执行工具」（原 4.4）的正解。QuantBench 作为 **MCP client**，让用户接入外部 MCP server（自有数据库、数据商 API）。**不做** 「QuantBench 作为 MCP server 供外部调用」的反方向。

**代码改动**：
- [ ] 配置文件声明外部 MCP server：`[{name, command|url, enabled_tools: [...]}]`，白名单默认只读（数据获取类）。
- [ ] 新增 `skills/mcp_adapter.py`（`MCPSkillAdapter`，预计一两百行）：基于官方 `mcp` Python SDK，把 MCP server 的 tool 动态注册进 [SkillRegistry](quantbench/skills/registry.py:14)——把 MCP 的 `inputSchema` 翻译成 `Skill` 的 schema，`registry.execute` 时转发给 MCP server。Coordinator 无感知（工具形状一致）。
- [ ] **审计红线一**：每次 MCP tool 调用（`server 名 / tool 名 / 参数 / 结果 hash`）记入 manifest，处理方式类比 `injected_skills`（[store.py:95](quantbench/artifact/store.py)）。新增 manifest 段 `mcp_calls`。
- [ ] **审计红线二**：MCP tool 返回的数据**未经内置数据质量校验**（[skills/data_quality.py](quantbench/skills/data_quality.py)），不享受内置 provider 的信任等级。用了外部 MCP 数据的 run，Reviewer 打 `external_data_unverified` 警告（新 `ReviewFinding`，severity=`info`，仅标注来源、不封顶 verdict——它是**可信度标签**不是**质量缺陷**），verdict 逻辑区别对待。
- [ ] **执行类 MCP tool 门槛**：有副作用/执行类的 MCP tool 需用户在 config 显式开启，且**必须经 1.1 沙箱**——沙箱未覆盖的执行类 tool 一律拒绝注册。本阶段默认只放开只读数据类。

**验收**：起一个 mock MCP server（返回固定 OHLCV），配置接入后 Coordinator 能像调内置工具一样调用它；该 run 的 manifest 出现 `mcp_calls` 记录（含结果 hash）且被 Reviewer 打 `external_data_unverified`；未白名单的 tool 无法被调用；执行类 tool 在沙箱缺席时拒绝注册。

---

### 1.3 Skills 格式对齐 SKILL.md 约定（GAP 7.3，🟠 低成本随手做）

**动机**：Workflow Skills（[skilldocs/registry.py](quantbench/skilldocs/registry.py) + `skills_docs/*.md`，按触发词注入，manifest 记 `injected_skills`）机制上**已等价于** Claude Code 的 Skills 模型。差距只有三点增量。

**代码改动**：
- [ ] **格式对齐**：`skills_docs/*.md` 迁移为目录式 `skills_docs/<name>/SKILL.md` + 附属文件，frontmatter 沿用 `name`/`description`/`triggers`。改 [skilldocs/registry.py:9](quantbench/skilldocs/registry.py) 的加载逻辑扫目录。实现与 Claude Code 生态**双向可移植**（用户在 Claude Code 里写的量化 skill 直接可用，反之亦然）。
- [ ] **渐进式披露**：SKILL.md 可引用附属文件（参考表、示例代码），模型**按需读取**而非全文一次性注入吃 context。新增一个 `read_skill_file(skill, path)` 工具，注入时只给 SKILL.md 正文 + 附属文件清单。
- [ ] **skill 附带可执行脚本**：⚠️ **依赖 1.1 沙箱**。skill 目录里的可执行脚本经 1.1 沙箱运行，否则等于给任意 markdown 开代码执行权。沙箱之前不开放此项——本阶段可先落地前两点（纯 doc/加载改动），脚本执行随 1.1 就绪后开。

**验收**：现有三个 skill（[causal-factor-authoring](skills_docs/causal-factor-authoring.md) 等）迁为目录式后触发与注入行为不变；一个带附属参考表的 skill，模型能通过 `read_skill_file` 按需拉取而非一次性注入；附带脚本的 skill 只能经沙箱执行。

---

### 1.4 计划确认环节 / human-in-the-loop（GAP 4.2，🟡 中）

**动机**：VISION 5.1 设计的两阶段——先出计划、暂停确认、再执行——从未落地。它是多轮 session（1.5）的天然踏脚石（都要在 loop 中间插入「暂停 + 用户输入」）。

**代码改动**：
- [ ] Coordinator 两阶段模式：新增 `plan()` 阶段，先让模型输出**结构化研究计划**（`{steps, data_needs, default_assumptions: {cost_bps, execution, neutralize, universe, date_range}, est_cost}`），**在昂贵工具（`screen_factors`/`cross_sectional_backtest`）执行前暂停**。
- [ ] CLI（[cli.py](quantbench/cli.py)）：交互式 `y/n` + 参数覆盖（`--cost-bps 10` 式覆盖计划里的默认假设）；非交互模式（`--yes`）沿用直接执行以保证 CI/脚本零回归。
- [ ] Web：计划以「计划卡片」呈现，用户可编辑假设后确认（见 1.5 的 UI 承接）。新增 API `POST /api/runs/{id}/plan/confirm`。
- [ ] **审计**：计划与实际执行的 **diff 记入 manifest**（`plan` 段 + `plan_execution_diff`）——审计「模型说要做什么 vs 实际做了什么」。这是审计链的自然延伸。
- [ ] 默认行为决策：默认**开启**确认（承接 Phase 12「默认更保守」），但提供 `auto_confirm` 开关；批量 `screen_factors` 尤其应确认（成本最高）。

**验收**：CLI 跑一个截面研究，先看到结构化计划、改 `cost_bps` 后确认，run 按改后假设执行；manifest 里 `plan` 与 `plan_execution_diff` 齐全，diff 反映用户的覆盖；`--yes` 模式行为与旧版一致。

---

### 1.5 多轮对话式 session（GAP 4.1，🟡 中高，本阶段最大产品跃迁）

**动机**：Claude Science 的核心体验是研究对话——追问、修改、中途转向在同一上下文里连续发生。当前 [execute()](quantbench/agent/coordinator.py:1440) 跑完即弃，无上下文延续。

**代码改动**：
- [ ] **Session 概念**（`api/session.py` + `artifact` 层）：一个 session = 多轮对话 + 多个 run，对话历史（含每个 run 的摘要 / verdict / 关键 metrics）作为上下文传给后续轮次。Session 本身是持久化 artifact。
- [ ] **上下文延续**：后续轮次的第一条 user message 前，注入「本 session 已有 run 的结构化摘要」（不是塞全部 messages——那会爆 context，也会污染 skill 匹配，见 [execute() docstring](quantbench/agent/coordinator.py:1465) 已有的相关顾虑）。「把手续费改成 10bps 再看看」应能定位到上一个 run 并以 fork 语义重跑（复用 [library/fork.py](quantbench/library/fork.py)）。
- [ ] **Web 演进**：[App.tsx](web/src/App.tsx) 从「提交 run 表单」（[createRun](web/src/api/client.ts:39)）演进为「对话流 + 内嵌 run 卡片」——每轮用户消息 + 模型回复 + run 结果卡片按时间线排列。1.4 的计划卡片自然嵌入此流。
- [ ] **溯源**：Session 对话历史成为 artifact 的一部分（Claude Science：溯源包含对话历史）。manifest 记 `session_id` + `turn_index`，实验库支持按 session 聚合。
- [ ] API：`POST /api/sessions`、`POST /api/sessions/{id}/turns`、`GET /api/sessions/{id}`；SSE 事件流复用现有 [stream_run_events](quantbench/api/server.py:146)。

**验收**：Web 端发起 session，第一轮跑截面动量因子，第二轮输入「加上 sector 中性化再跑」——系统不需重述前情即定位上一个 run 并以 fork 重跑，两个 run 卡片同流展示；session artifact 含完整对话历史；实验库能按 session_id 聚合这组 run。

---

### 1.6 文献接入：论文 → 假设来源（GAP 4.3，🟠 中低但差异化价值高，验证 SubAgent 抽象）

**动机**：「复现这篇论文的因子」是真实高频 use case（arXiv q-fin / SSRN）。它也是 1.0 的 `SubAgent` 抽象的**第二个实例**（继 Critic 之后），验证抽象可复用于新角色。

**代码改动**：
- [ ] **文献复现 SubAgent**（填充 1.0 的抽象，不引入新依赖）：输入 PDF / arXiv 链接 → 提取因子定义 → 生成 `compute()` → 交给标准回测审查流程。PDF 解析走已有能力或轻量库（不新增重依赖，优先纯文本/已装工具）。
- [ ] Research note 记录**假设来源**（论文引用），实验库支持按来源检索（`source: {type: "paper", ref, url}` 入 manifest 与实验记录 [library/record.py](quantbench/library/record.py)）。
- [ ] **复现 vs 论文报告结果的对比表**：复现出的 Sharpe/IC 与论文声称值并排——**往往对不上，这本身就是有价值的研究发现**，接入 note 与 Reviewer（可作 `info` 级 finding：「复现值与论文报告差异显著」）。

**验收**：给定一篇有明确因子定义的 q-fin 论文（本地 PDF fixture），文献 SubAgent 产出可跑的 `compute()`、走完标准审查、note 含引用与复现对比表；manifest 的 `delegations` 记录该 SubAgent 委派;实验库能按论文来源检索到这条记录。

---

### 1.7 远程计算（GAP 4.6，🟠 低，仅接口预留）

**动机**：批量因子筛选 + CPCV + bootstrap（Phase 10）会显著抬升计算量，本地单机终将成为瓶颈。但**当前不是瓶颈**，故本阶段**仅预留接口**、不实装。

**代码改动**：
- [ ] 定义执行后端抽象（`ExecutionBackend`：`local`（现状）/ `remote`（stub）），`screen_factors` 的 fan-out 通过该抽象派发。
- [ ] `remote` 后端留 SSH/Modal 的接口位与 config schema，本阶段**只实现 local**，remote 抛 `NotImplementedError` 并在 note 声明「远程计算规划中」。

**验收**：现有 `screen_factors` 走 `local` 后端行为不变；`remote` 后端接口存在但明确未实装，配置切到 remote 时给出清晰的「未实装」错误而非静默失败。

---

## 二、审计与信任分层接入总览（承接「审计链不可断裂」）

本阶段不新增统计检查、不动 [determine_verdict](quantbench/review/report.py) 阈值。新增的是**留痕**与**来源可信度标签**：

| 能力 | manifest 新增段 | Reviewer finding | 对 verdict 效果 |
|---|---|---|---|
| SubAgent 委派（1.0/1.6） | `delegations` | — | 无（纯留痕） |
| 沙箱资源用量（1.1） | `sandbox`（用值 + 峰值） | — | 无 |
| MCP 调用（1.2） | `mcp_calls`（server/tool/参数/结果 hash） | `external_data_unverified`(info) | 无（仅标注来源） |
| 计划两阶段（1.4） | `plan` + `plan_execution_diff` | — | 无 |
| Session（1.5） | `session_id` + `turn_index` | — | 无 |
| 文献来源（1.6） | `source`（paper ref） | 复现差异(info，可选) | 无 |

**信任分层原则**：`external_data_unverified` 是**来源可信度标签**而非**质量缺陷**——它不封顶 verdict，只让读者/Reviewer 知道「这条结论用了未经内置校验的外部数据」。执行类 MCP tool 与 skill 附带脚本一律**先过 1.1 沙箱**，沙箱缺席则拒绝启用。这维持了「内置一等 provider（可信）vs 外部 MCP（untrusted）」的分层。

---

## 三、依赖关系与落地顺序

### 依赖图

```
1.0 重构 + SubAgent ──┬──> 1.1 沙箱 ──┬──> 1.2 MCP(执行类) 
（一切的地基）         │               └──> 1.3 skill 附带脚本
                      │
                      ├──> 1.2 MCP(只读，不依赖沙箱)
                      ├──> 1.3 SKILL.md 格式对齐(doc-only)
                      ├──> 1.4 计划确认 ──> 1.5 多轮 session
                      ├──> 1.6 文献 SubAgent（验证抽象）
                      └──> 1.7 远程计算（接口预留）
```

### 建议落地顺序（承接 GAP 7.4）

1. **1.0 重构 + SubAgent（先行）** — 所有产品功能的地基；Critic 迁移验证抽象；golden runs 锁定零行为漂移。
2. **1.1 沙箱** — 生产化前置债；解锁 1.2/1.3 的执行类能力；独立可测。
3. **1.2 MCP client（只读先行）+ 两条审计红线** — 解锁外部数据源生态；执行类 tool 等 1.1 就绪后放开。
4. **1.3 SKILL.md 格式对齐** — 低成本随手做（前两点 doc-only）；附带脚本随 1.1 开。
5. **1.4 计划确认** — 两阶段模式；是 1.5 的踏脚石。
6. **1.5 多轮 session** — 本阶段最大产品跃迁；承接 1.4 的计划卡片。
7. **1.6 文献 SubAgent** — 填充 1.0 抽象的第二个实例，差异化价值。
8. **1.7 远程计算** — 仅接口预留，最后收尾。

1.2/1.3/1.4 在 1.0/1.1 就绪后**可并行**；1.5 依赖 1.4；1.6 依赖 1.0。

---

## 四、明确不做（本阶段边界）

- **不做 5.2 Alpha 生命周期 / paper tracking、不做 5.3 信号导出** —— 已决策移出本阶段，留待 Phase 14。它们依赖 session（1.5）与数据每日快照，本阶段先把形态地基打好。
- **不引入 Agent 框架**（LangGraph / CrewAI / AutoGen）—— GAP 7.1 已论证：框架破坏审计链、与「代码写基础设施」准则冲突，且不提供自己写不出的能力。裸写 SubAgent。
- **不做 Docker 沙箱** —— 已决策用受限子进程 + rlimit，覆盖 80% 风险且无运行时依赖。Docker 作为后续增量（若出现子进程隔离不足的真实需求）。
- **不做「QuantBench 作为 MCP server」** —— 只作 client 接入外部 server（GAP 7.2）。
- **不实装远程计算** —— 仅预留接口（1.7）；本地单机当前未成瓶颈。
- **不采用 Claude Agent SDK** —— 触发条款：若底层模型策略全面转向 Claude 再评估；当前 LiteLLM + DeepSeek 成本策略与其 Anthropic 锁定冲突（GAP 7.1 触发条款）。
- **不新增统计检查、不动 verdict 阈值** —— 本阶段是形态层，只加留痕与来源标签。
- **不引入重依赖** —— MCP 用官方 `mcp` SDK；沙箱用标准库 `subprocess`/`resource`；PDF 解析优先已装/纯文本方案。

---

## 五、与既有阶段的接口

- **golden runs（Phase 10 / GAP 5.1）是 1.0 重构的安全网**：2057 行拆分若无回归评测集兜底，风险极高。重构前先确认 golden runs 覆盖 verdict / critic_report / manifest 关键字段，重构后逐字节比对。
- **1.1 沙箱的资源用量回填**为 GAP 5.4「成本与用量可观测性」预埋数据（token/API/耗时可在同一 manifest 段扩展）。
- **1.5 session 的每轮 run 聚合**为 Phase 14 的 5.2 paper tracking 铺路（session 天然是一组相关因子的容器）。
- **1.6 文献来源**入实验库检索，与 Phase 11 数据版本锁定的溯源同构。

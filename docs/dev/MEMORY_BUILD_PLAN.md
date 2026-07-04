# 记忆系统搭建计划（Session + 长期记忆，一份文档、分阶段执行）

> 实现层文档,配套架构文档 [MEMORY_ARCHITECTURE.md](MEMORY_ARCHITECTURE.md)(为什么/是什么)。本文档回答"怎么做",覆盖 ① Session（[PHASE13B.md](PHASE13B.md) §1.5）与 ② 用户长期记忆（架构文档新增）**两层的完整落地**。
>
> **执行纪律(关键)**：这是**一份文档、三个阶段**,不是一次性交付的大任务。三阶段严格按依赖顺序,**每阶段独立可交付、独立可测、独立提交**。② 在 ① 落地前无法开始(没有连贯线程就没有可晋升的东西);② 的注入依赖已落地的 [1.4 审查台](PHASE13B_HITL_STAGING.md)。**别把三阶段当一个 blob 一起做。**
>
> **落地状态(2026-07-04)**：Stage A / B / C 已按顺序完成并分别提交：`ea16358`（Session）、`f43de33`（长期记忆存储 + 注入）、`f455126`（固化/晋升闸门 + memory_events）。文档回填提交另见后续 docs commit。
>
> 前置(均已在 `main`)：
> - **1.4 执行前审查台**：② 长期记忆注入的**唯一合法出口**(喂默认 → 审查台可见 → 进 manifest)。
> - **SubAgent 抽象**（[subagent.py](quantbench/agent/subagent.py)）：② 的固化 Agent 复用它(Critic 之后第二个实例)。
> - **fork + lineage**（[build_fork_config](quantbench/library/fork.py)、[execute_fork](quantbench/agent/coordinator.py)）：Session 的"追问重跑"复用。
> - **实验库**（[ExperimentIndex](quantbench/library/index.py)）：③ 持久记录,Session 按 session_id 聚合、② 检索寻址的对象。

---

## 〇、命名冲突先澄清（否则 Web 会做错）

现有 Web 的 `SessionTab`（[SessionTabBar.tsx](web/src/components/SessionTabBar.tsx)）**是假名**：它的 `id` 是"真实 run_id 或 draft",即**一个标签 = 一个 run**,不是对话 session。后端**完全无 session 概念**。

**本计划的 Session 是全新的**：一个 session = 一条研究线程 = **多个 run**。Stage A 会把现有"一标签一 run"演进为"**一标签一 session 线程,内含多个 run 卡片按时间线排列**"。计划中凡说"Session"均指后者。

---

## Stage A — Session（① / 1.5）：工作线程的上下文与寻址

> 依赖:无(纯新增)。这是整个记忆系统的地基——② 的晋升源头。

### A.1 数据模型与持久化

- 新模块 `quantbench/api/session.py`：
  ```python
  @dataclass
  class SessionTurn:
      turn_index: int
      user_message: str
      run_id: str | None            # None = 该轮未产出 run（如纯追问被 fork 到旧 run）
      summary: dict                 # {hypothesis, verdict, key_metrics: {...}, run_id}
  @dataclass
  class Session:
      session_id: str
      created_at: str
      turns: list[SessionTurn]
  ```
- 持久化 `runs/_sessions/{session_id}.json`（复用 artifact 目录惯例,**不引数据库**）。
- `SessionStore`：`create() / get(id) / append_turn(id, turn) / list()`。turn 的 `summary` 从**已完成 run** 的 manifest/review 提取——复用 [build_record](quantbench/library/record.py) 或 `read_manifest`,只取 hypothesis / verdict / 关键 metrics + run_id,**不存原始 transcript**（架构文档铁律:压缩而非原文,否则 context 爆 + 污染 skill 匹配）。

### A.2 上下文延续（③ → ① 流动）

- 新函数 `build_session_context(session) -> str`：把本 session 已有 run 的**结构化摘要**拼成一小段(每 run 一行:hypothesis + verdict + 关键 metric + run_id)。
- [Coordinator.execute](quantbench/agent/coordinator.py) 新增可选入参 `session_context: str | None`；非空时注入到首条 user message 之前(「本 session 已有 run 摘要如下…」),**不塞历史 messages**。
- 缺省 `None` → 行为与今日逐字节一致(零回归)。

### A.3 追问寻址工具（显式、可审计）

- 新内置 skill `fork_previous_run(run_id, modification)`，注册进 [_build_registry](quantbench/agent/coordinator.py)：让模型把「把手续费改成 10bps 再看看」解析成**具体 run_id**（从 A.2 注入的摘要里选）,再走 [execute_fork](quantbench/agent/coordinator.py) + [build_fork_config](quantbench/library/fork.py) 重跑。
- **为什么工具化而非靠 prompt 猜**：寻址可测、可审计;fork 语义复用既有 lineage,不破坏 ③ 不可变性。

### A.4 API

- `POST /api/sessions`：建 session。
- `POST /api/sessions/{id}/turns`（body: user_message）：在 session 内起一个 run（组装 `session_context` 传入 execute）,返回 run_id;SSE 复用 [stream_run_events](quantbench/api/server.py)。
- `GET /api/sessions/{id}`：取完整线程。
- manifest 新增 `session_id` + `turn_index`（照抄 delegations 的 store.py 加参数模式）。

### A.5 Web（本阶段最重的一块）

- 现有"一标签一 run"演进为"**一标签一 session 线程**"：[ChatPane](web/src/components/ChatPane.tsx) 渲染该 session 的 turns——**用户消息 + 内嵌 run 卡片**按时间线排列,底部是"继续追问"输入框。
- 1.4 的审查台卡片、run 结果卡片都嵌入此流。
- `SessionTab.id` 从 run_id 改为 session_id;`getRun` 轮询保留(单个 run 详情),新增 session 线程数据源。

### A.6 测试与验收

- **单测**：`SessionStore` CRUD;`build_session_context` 只产结构化摘要不含 transcript;`fork_previous_run` 解析 run_id 并走 fork。
- **端到端**：起 session,第一轮跑动量因子,第二轮「加 sector 中性化再跑」→ 不重述前情,经 `fork_previous_run` 定位上一 run 重跑,两张 run 卡片同流;session json 含完整线程;实验库能按 session_id 聚合。
- **零回归**：不传 `session_context` 时既有 run 行为不变。

---

## Stage B — 长期记忆存储 + 注入（② 存储 + INDEX + 审查台默认）

> 依赖:Stage A（线程存在）**且** 1.4 审查台（已落地,注入的唯一出口）。

### B.1 存储

- 新模块 `quantbench/memory/store.py`：`memory/user/*.md`,**一条事实一个文件**,frontmatter `type` / `description` / `provenance`(源自哪个 session/run)/ `created_at` / `confidence`;`memory/user/INDEX.md` 一行一条(会话开始注入的"常驻小集")。
- `UserMemoryStore`：`read_all() / write(fact) / update(id, ...) / delete(id) / render_index()`。**project-global**(单人期,`user_id` 仅预留字段)。
- **可变**：能 update（事实变了）、能 delete（被推翻）。

### B.2 注入（② → ① / 1.4 流动）——只喂默认,绝不静默改假设

这是 ② 在研究工具里唯一正确的用法（架构文档铁律）：

```
② 长期记忆 → 预填 1.4 审查台默认 → 用户在门里【可见/可改】 → 最终值进 manifest
```

- **常驻集注入**：会话开始把 `INDEX.md` 注入 system prompt（复用 [build_augmented_system_prompt](quantbench/skilldocs/inject.py) 的注入模式,或并行一个)。
- **审查台默认预填**：type=默认偏好的事实（如 cost_bps=10）**预填** [StagingGate](quantbench/agent/staging.py) 的 config 默认,而非直接生效。审查台已有"可见 + 可改 + 进 manifest",天然承接。
- **审计**：manifest 新增 `applied_memory_defaults: [{fact_id, field, value}]`——记录"本 run 用了哪些来自 ② 的默认",区分"记忆喂的"与"当场定的"。

### B.3 测试与验收

- **单测**：存储 CRUD;`INDEX.md` 与文件一致;冲突事实触发 update 而非叠加。
- **注入审计安全**：有「默认 10bps」事实时,run 的审查台默认预填 10;**未经审查台确认不静默生效**;manifest 出现 `applied_memory_defaults`;用户在门里改回 5 → 本 run 用 5。
- **零回归**：无 `memory/user/` 时全系统行为与今日一致（② 缺省空,注入 no-op）。

---

## Stage C — 固化 / 晋升闸门 + 腐烂治理（① → ② 流动，最难）

> 依赖:Stage A（晋升源头)+ Stage B（晋升目标）。**已决策:自动 consolidation + 会话内可见。**

### C.1 记忆固化 SubAgent（复用抽象,不新造框架）

- 复用 [SubAgent](quantbench/agent/subagent.py)（Critic 之后第二个实例）做"记忆固化 Agent"：
  - 输入:一个 session 的 run 摘要 + 用户在审查台的历次改动（[staged_diff](quantbench/agent/staging.py) 里已有）。
  - 输出:候选持久事实 `{type, statement, provenance, confidence}`。
- 委派照旧进 manifest `delegations`（SubAgent 既有审计模式）。

### C.2 晋升闸门（防腐烂第一道）

- **触发**:session 结束跑一次;或周期性 consolidation 扫最近若干 session 找**跨会话重复模式**。
- **单次不晋升,重复才晋升**（≥N 个 session 出现同一偏好）——这是防腐烂第一道闸。

### C.3 会话内可见（自动写 ≠ 静默写）

- 每次写入/更新 ② 产出一条**会话内提示**（"🧠 已写入记忆:默认成本改为 10bps"）,用户当场知道记住了什么,可一键撤销/编辑。
- 通过 SSE 事件（复用 [stream_run_events](quantbench/api/server.py) 的事件流,新增 `memory` 事件类型）推给 Web。

### C.4 腐烂治理

- 写入前**去重**;与已有事实**冲突时 update 或标记过时**,不叠加;`confidence` 随重复升、随被推翻降;明显过时的 delete。
- **反向流(流动 4 的反向)**：用户在审查台改掉某个由 ② 预填的默认 → 作为该事实的 confidence **下调信号**回流。

### C.5 ② 自身可审计

- 每次 ② 写/改/删记一条 `memory_events`（what / when / provenance:源自哪个 session_id + consolidation）——**记忆本身也进审计链**。
- `provenance` 让任一条用户记忆可回溯到"从哪些 run / 哪个 session 归纳而来"。

### C.6 测试与验收

- **单测**：单次出现的偏好**不**晋升;跨 ≥N 个 session 重复**晋升**;晋升产出会话内可见提示 + `memory_events` 留痕 + `provenance` 可回溯 + manifest `delegations` 含该委派。
- **腐烂治理**：冲突事实 update 而非叠加;被推翻的事实 confidence 降/删;过时事实不再注入。
- **闭环端到端**：用户跨 session 反复设 10bps → 固化提升「偏好 10bps」(可见提示)→ 之后 run 的审查台默认预填 10（A→C→B 闭环）。

---

## 一、跨阶段：审计与存储约定

| 能力 | manifest / 文件新增 | 审计事件 |
|---|---|---|
| Session（A） | `session_id` + `turn_index`;`runs/_sessions/{id}.json` | — |
| ② 注入（B） | `applied_memory_defaults` | — |
| ② 固化（C） | `delegations`（固化 SubAgent 委派）| `memory_events`（写/改/删）|

- **全文件式**:`runs/`、`runs/_sessions/`、`memory/user/`,**不引数据库**。
- **不动 verdict**:记忆系统是形态层,不新增统计检查、不碰 [determine_verdict](quantbench/review/report.py) 阈值。
- **③ 保持不可变**:记忆系统只读 / 只寻址 `library/`,绝不改历史 run。

---

## 二、落地顺序（单人直接在 main 上推进）

**严格 A → B → C,每阶段独立提交。**

1. **Stage A**：A.1 存储 → A.2 上下文注入 → A.3 fork 寻址工具 → A.4 API → A.5 Web → A.6 验收。（Web 是最重的一块,可再拆后端/前端两提交。）
2. **Stage B**：B.1 存储 → B.2 注入(常驻集 + 审查台默认 + `applied_memory_defaults`)→ B.3 验收。
3. **Stage C**：C.1 固化 SubAgent → C.2 晋升闸门 → C.3 会话内可见 → C.4 腐烂治理 → C.5 审计 → C.6 闭环验收。

**闸门纪律**：B 在 A 未落地前不动;C 在 A+B 未落地前不开（否则记忆可能在没有审查台可见出口的情况下静默改假设,违反铁律）。

---

## 三、明确不做（边界）

- **不引数据库 / 向量库 / embedding 检索**:三层全文件式;检索靠 [ExperimentIndex](quantbench/library/index.py) 与 frontmatter 结构化字段。需要时再评估。
- **不做多用户 / 权限**:单人期 ② = project-global,`user_id` 仅预留。
- **不做静默注入**:② 永远经审查台可见、进 manifest。没有"记忆偷偷改假设"的路径。
- **不做要求用户显式「记住」**:已决策走自动 consolidation + 会话内可见。
- **不改 ③ 不可变性**;不新增统计检查、不动 verdict 阈值。
- **不塞原始 transcript 进 context**:Session 只注入结构化摘要。

---

## 四、与既有工作的接口

- **1.4 审查台** = ② 注入唯一合法出口(B.2)。
- **SubAgent 抽象** 被固化 Agent 复用(C.1),委派进 `delegations`。
- **fork + lineage** 被 Session 追问寻址复用(A.3)。
- **实验库** 按 `session_id` 聚合(A.4),被 ② 检索寻址(B/C)。
- **SSE 事件流** 复用于 Session 实时 + ② 的"已写入记忆"可见提示(C.3)。

---

*落地后按阶段回填本文件、[MEMORY_ARCHITECTURE.md](MEMORY_ARCHITECTURE.md) 各层状态、[PHASE13B.md](PHASE13B.md) §1.5 与 [GAP_ANALYSIS.md](GAP_ANALYSIS.md) 4.1。*

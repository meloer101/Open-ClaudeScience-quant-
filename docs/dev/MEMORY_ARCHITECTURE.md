# QuantBench 记忆系统架构

> 跨阶段设计文档(与 [VISION.md] / [GAP_ANALYSIS.md](GAP_ANALYSIS.md) 同级,非单一 phase 交付)。
>
> 定义 QuantBench 的记忆系统:**三层 + 四条流动**。回答「Session、用户长期记忆、研究记录三者各是什么、怎么写、怎么进 context、怎么互相流动」,并锁死一条量化工具特有的铁律:**记忆只喂默认、经审查台可见、进 manifest 留痕,绝不静默改研究假设。**
>
> 关联:① Session = [PHASE13B.md](PHASE13B.md) §1.5;② 长期记忆 = 本文档新增;③ 持久记录 = 既有 `quantbench/library/`;注入闸门与 [PHASE13B_HITL_STAGING.md](PHASE13B_HITL_STAGING.md) 的审查台咬合。

**落地状态(2026-07-04)**:三层已按文件式方案落地。① Session 写入 `runs/_sessions/` 并在 Web 中按线程展示 run 卡片;② 长期记忆写入 `memory/user/` 并通过 `INDEX.md` 注入常驻小集;② 默认值只进入 staging gate,manifest 记录 `applied_memory_defaults`;①→② consolidation 复用 `SubAgent`,跨 session 阈值晋升并记录 `memory_events`。

---

## 〇、核心模型:不是三个抽屉,是三层 + 四流动

「三层记忆」若被实现成三个平行存储抽屉,必然做烂——因为三层的**写入策略、可变性、注入方式**根本不同,而真正的价值在**层与层之间的流动**。

```
        ┌─────────────────────────────────────────────┐
        │  ② 用户长期记忆 (project-global, 可变, 策展)   │
        └───────▲───────────────────────┬─────────────┘
       ④ 晋升   │ 自动 consolidation      │ ③ 注入默认
       (会话内可见)                       ▼
        ┌───────┴───────┐         ┌──────────────────┐
        │  ① Session     │────────▶│  1.4 审查台默认    │
        │ (线程工作上下文) │  ②预填  │ (可见/可改/进manifest)│
        └───────┬───────┘         └──────────────────┘
       ① run落库 │  ▲ ② 检索寻址(fork/库检索)
                ▼  │
        ┌──────────┴──────────────────────────────────┐
        │  ③ 持久记录 (run/manifest/lineage, 不可变)      │
        │      quantbench/library/ —— 已存在            │
        └─────────────────────────────────────────────┘
```

四条流动(设计的真身):
1. **① → ③**:run 结束落库。**已有**。
2. **③ → ①**:检索/fork,把过去 run 的摘要浮现进当前线程。**= 1.5**。
3. **② → ①/1.4**:会话开始注入常驻事实 + 预填审查台默认。**新**。
4. **① → ②(晋升闸门)**:自动 consolidation,把线程里学到的持久事实固化成用户级记忆,**且在会话内可见**。**新,最难**。

---

## 一、三层各自的性质(别用同一套机制对待)

| | ① Session | ② 长期记忆 | ③ 持久记录 |
|---|---|---|---|
| **是什么** | 一条研究线程的工作上下文 | 关于用户的持久事实/偏好 | 做过的 run 的不可变账本 |
| **谁写/怎么写** | 自动追加,无策展 | **自动 consolidation + 会话内可见** | 自动(run finalize 落库) |
| **可变性** | 线程内 append,结束冻结 | **可变:能改、能删**(事实会过时/被推翻) | **不可变**:run 即 run,只能 fork 取代 |
| **进 context 方式** | 结构化摘要,选择性浮现 | 会话开始注入常驻小集 + 预填 1.4 默认 | **不自动进**,靠显式寻址检索 |
| **寻址键** | session_id + turn_index | user_id(单人期 = project-global) | run_id + lineage |
| **QuantBench 现状** | **已落地**:`runs/_sessions/` + Web 线程 | **已落地**:`memory/user/` + `INDEX.md` + consolidation | **已有** `library/` |

一句话区分 ② 与 ③:**③ 是原始 run;② 是从一堆 ③ 里跨会话归纳出的、经策展的"关于用户的模式"。② 是 ③ 的有损压缩 + 人味泛化,不是再存一份 run。**

---

## 二、③ 持久记录(已有,只需确认约束)

- **落地位置**:`quantbench/library/`——[ExperimentIndex](quantbench/library/index.py:12)、[ExperimentRecord](quantbench/library/record.py:24)、[lineage.py](quantbench/library/lineage.py)、[fork.py](quantbench/library/fork.py)、[compare.py](quantbench/library/compare.py)、[trials.py](quantbench/library/trials.py) + 每个 run 的 `manifest.json`。
- **本记忆系统对它的唯一要求**:**保持不可变**。记忆系统只**读**、只**寻址**它,绝不改历史 run。这是审计链的根。
- ② 需要的检索入口它已提供:`ExperimentIndex.filter/sort`、`build_record(run_id)`、lineage。**不新增存储,只被 ② 消费。**

---

## 三、① Session(= PHASE13B §1.5,本文档只补记忆视角的约束)

Session 是"工作线程的上下文**选择与寻址**",不是"存储"——③ 已经存下了一切,Session 的活是**从已存的东西里,选对的、压好的、指准的,喂给下一回合**。

记忆视角下的三条硬约束(细节见 [PHASE13B.md](PHASE13B.md) §1.5):
- **压缩而非原文**:每个 run 只贡献结构化摘要(hypothesis / verdict / 关键 metrics / run_id),**不塞原始 transcript**(否则 context 爆 + 污染 skill 匹配)。
- **显式寻址**:「上一个 run」「那个动量因子」经 `fork_previous_run(run_id, modification)` 工具解析成具体 run_id——把隐式指代变可审计的检索。
- **落地位置**:`runs/_sessions/{session_id}.json`(复用 artifact 目录惯例,不引数据库);manifest 记 `session_id` + `turn_index`。
- **它是 ② 的晋升源头**:没有连贯线程,「晋升什么」无从谈起——故 ① 必须先于 ② 做透。

---

## 四、② 用户长期记忆(本文档核心新增)

### 4.1 存哪、什么形态

- **文件式,一条事实一个文件 + 索引**(与 Claude `memory/` + `MEMORY.md` 模型同构):`memory/user/*.md`,每个文件 frontmatter 带 `type` / `description` / `provenance`(源自哪个 session/run)/ `created_at` / `confidence`;`memory/user/INDEX.md` 一行一条,是会话开始注入的那份"常驻小集"。
- **project-global**(单人期):`user_id` 概念预留,当前全项目一个用户。
- **可变**:能 update(事实变了)、能 delete(被推翻)。**腐烂治理是 ② 的核心工作,不是存储。**

### 4.2 存什么(② 的合法内容)

只存**持久且通用**的关于用户的事实,典型:
- **默认假设偏好**:反复设的 `cost_bps` / `execution` / `neutralize` / universe / date_range。
- **方法论偏好**:「永远 point-in-time」「永远建模 borrow」「crypto 永远计 funding」。
- **关注面**:资产类别、板块、反复出现的 hypothesis 主题。
- **反复的纠正**:用户在审查台里反复改模型的同一类东西(如总把 5 日改 20 日)。

**不存**:一次性的、线程内的、能从 ③ 直接查到的东西(那是 ① 或 ③ 的职责)。

### 4.3 晋升闸门(决策:自动 consolidation + 会话内可见)

**已定决策**:不要求用户显式说「记住」,而是**自动 consolidation**——但**在会话内可见**(像主流 AI 工具那样,产出一条"🧠 已写入记忆:默认成本改为 10bps"的提示),而非静默写入。

- **机制:复用 [SubAgent](quantbench/agent/subagent.py) 抽象做"记忆固化 Agent"**(继 Critic 之后的又一实例——抽象复用,不新造框架)。输入:一个 session 的 run 摘要 + 用户在审查台的历次改动;输出:候选持久事实 `{type, statement, provenance, confidence}`。
- **触发**:session 结束时跑一次;或周期性 consolidation 扫最近若干 session 找**跨会话重复模式**(单次出现不晋升,重复才晋升——防腐烂的第一道闸)。
- **可见**:每次写入/更新 ② 都产出一条会话内提示(用户当场知道记住了什么),并可一键撤销/编辑。**自动写 ≠ 静默写。**
- **腐烂治理**:写入前去重;与已有事实冲突时**更新或标记过时**而非叠加;`confidence` 随重复次数升、随被推翻降;明显过时的 delete。

### 4.4 ② 的注入:只喂默认,绝不静默改假设(量化工具铁律)

这是 ② 在**研究工具**里唯一正确的用法,也是通用记忆设计不会提醒你的地雷:

> 若「用户偏好 10bps」被记住后**静默应用**到回测——两个用户跑同一因子会因隐藏记忆拿到不同结果,**违反审计原则**。

**铁律:② 只影响"默认值 + 建议",经审查台可见,进 manifest 留痕。** 流动固定为:

```
② 长期记忆 → 预填 1.4 审查台默认 → 用户在门里【可见/可改】 → 最终值进 manifest
```

- ② 提供的是 staging 门里那些字段的**默认**(cost_bps 预填 10 而非 5),不是既成事实。
- manifest 新增记录:**本 run 应用了哪些来自 ② 的默认**(`applied_memory_defaults: [{fact_id, field, value}]`)——审计「这个默认是记忆喂的,不是模型/用户当场定的」。
- 用户在审查台改掉某默认 → 既反映到本 run,也可回流成 ② 的 `confidence` 下调信号(④ 的反向流)。

### 4.5 ② 自身可审计

- 每次 ② 写入/更新/删除记一条 `memory_events`(what / when / provenance:源自哪个 session_id+consolidation)。
- `provenance` 让任何一条用户记忆都能回溯到「它是从哪些 run/哪个 session 归纳出来的」——记忆本身也进审计链。

---

## 五、四条流动的实现落点

| 流动 | 落点 | 状态 |
|---|---|---|
| ① → ③ run 落库 | `library/record.build_record` + manifest | 已有 |
| ③ → ① 检索/fork | `fork_previous_run` 工具 + `ExperimentIndex` | 已落地 |
| ② → ①/1.4 注入默认 | 会话起注入 `INDEX.md` 常驻集;预填审查台默认 | 已落地 |
| ① → ② 晋升 | 记忆固化 SubAgent(session 末 + 周期扫);会话内可见 | 已落地 |

---

## 六、测试

- **② 存储纯函数**:写/读/更新/删除一条用户记忆;`INDEX.md` 与文件一致;冲突事实触发更新而非叠加。
- **晋升闸门**:单次出现的偏好**不**晋升;跨 ≥N 个 session 重复的偏好**晋升**;晋升产出会话内可见提示 + `memory_events` 留痕 + `provenance` 可回溯。
- **注入审计安全**:② 有「默认 10bps」时,run 的审查台默认预填为 10;**未经审查台确认不静默生效**;manifest 出现 `applied_memory_defaults`;用户改回 5 → 本 run 用 5 且 ② 的 confidence 收到下调信号。
- **腐烂治理**:被推翻的事实 confidence 下降/删除;过时事实不再注入。
- **零回归**:无 `memory/user/` 时全系统行为与合并前一致(② 缺省为空,注入为 no-op)。

---

## 七、落地顺序

1. **① Session(1.5)先做透**——它是 ② 的晋升源头,没有连贯线程无从谈晋升。
2. **② 存储层 + INDEX 注入(常驻小集)**——纯文件式,可独立测。
3. **② → 1.4 审查台默认预填 + `applied_memory_defaults` 审计**——依赖 1.4 审查台就绪。
4. **记忆固化 SubAgent(晋升闸门)+ 会话内可见提示 + `memory_events`**——依赖 1.5。
5. **腐烂治理(去重/冲突/confidence/删除)**——随 ② 用量增长收口。

每步小步提交到 `main`。② 在 ① 稳之前不动;④ 晋升在 ③→默认→审查台那条注入路径(第 3 步)就绪前不开(否则记忆可能静默改假设)。

---

## 八、明确不做(边界)

- **不引数据库**:三层全走文件式 artifact(`runs/`、`runs/_sessions/`、`memory/user/`)。
- **不做静默注入**:② 永远经审查台可见、进 manifest;没有「记忆偷偷改了假设」的路径。
- **不做多用户 / 权限**:单人期 ② = project-global,`user_id` 仅预留字段。
- **不改 ③ 的不可变性**:记忆系统只读/寻址 `library/`,绝不改历史 run。
- **不做要求用户显式「记住」的模式**:已决策走自动 consolidation + 会话内可见。
- **不新造记忆框架 / 向量库**:② 是文件 + 索引 + 固化 SubAgent;检索靠既有 `ExperimentIndex` 与结构化 frontmatter,不引入 embedding 检索(需要时再评估)。

---

## 九、与既有工作的接口

- **1.4 审查台**是 ② 注入的**唯一合法出口**——② 喂默认、审查台可见、manifest 留痕,三者咬死。
- **1.5 Session** 是 ② 晋升的**唯一源头**——先有连贯线程,才有可固化的模式。
- **SubAgent 抽象** 被记忆固化 Agent 复用(Critic 之后的又一实例),委派照旧进 manifest `delegations`。
- **manifest 审计段** 新增 `applied_memory_defaults`(本 run 用了哪些记忆默认)与 `memory_events`(记忆的写/改/删),照抄 `delegations`/`sandbox_usage`/`mcp_calls` 的加法。

---

*2026-07-04 已回填 [PHASE13B.md](PHASE13B.md) 与 [GAP_ANALYSIS.md](GAP_ANALYSIS.md),并在本文件标注各层完成状态。*

# QuantBench 现状盘点与下一步建议

> 快照日期:2026-07-04 | 对照 [GAP_ANALYSIS.md](GAP_ANALYSIS.md) 全六章 + 已落地代码逐项核对。
>
> 一句话现状:**GAP 第二章(统计严谨性)、第三章(回测现实性)、第四章(产品形态)已基本闭合;第一章(数据地基)主体完成、剩零散外部依赖项;第五章(roadmap 缺失的整块议题)是当前最大的未开垦地。** 系统已从"一句话→一次 run 的批处理器"演进为"可对话、可确认、可扩展、可审计、有记忆"的研究平台。

---

## 一、完成度总览

| 章节 | 主题 | 状态 | 备注 |
|---|---|---|---|
| 一 | 数据地基 | 🟡 主体完成 | PIT S&P500 / 时变 universe / funding / 版本锁定 / crypto 每日快照已做;剩 crypto PIT 重建、equity 退市源、PerpetualData schema |
| 二 | 统计严谨性 | ✅ 完成 | DSR / PBO / walk-forward / CPCV / bootstrap / IC 显著性(Phase 10/10.5) |
| 三 | 回测现实性 | ✅ 完成 | 执行价 / 流动性成本+容量 / borrow / 中性化(Phase 12)+ beta 中性化修复 |
| 四 | 产品形态 | 🟡 基本完成 | 沙箱 / MCP / SKILL.md / 审查台 / Session+记忆 / 远程接口(PHASE13B);剩 4.3 文献接入、4.4 provider 信任层、4.5 Docker(推后) |
| 五 | roadmap 缺失议题 | 🟡 5.1+5.2 已完成 | 5.1 golden runs 纪律 ✅;5.2 Alpha 生命周期/paper tracking ✅;5.3 信号导出(未做)、5.4 可观测性(部分) |
| 六/七 | 开发顺序 / 架构决策 | ✅ 已执行 | 不引 Agent 框架、MCP 作 client、SubAgent 自有抽象——均已落地 |

---

## 二、已完成(含计划外补的)

- **统计护栏全套**(Phase 10/10.5):试验次数记账、DSR、PBO/CSCV、walk-forward、CPCV、bootstrap CI、IC Newey-West。
- **回测现实性四件套**(Phase 12):执行价显式化、流动性感知成本+容量曲线、borrow cost+做空可行性、三维中性化(beta/size/sector)。**计划外修复**:beta 中性化原为静默空操作,已接上滚动 beta;`close_t+1` 口径修正。
- **数据地基主体**(Phase 11):PIT S&P500 成分、时变 universe 回测、funding rate 拉取+建模、数据版本锁定+rerun。
- **产品形态整条线**(PHASE13B):
  - 1.0 受限子进程沙箱(含截面/monitor 路径收口)
  - 1.1 MCP client(只读外部数据工具 + 两条审计红线)
  - 1.2 SKILL.md 目录化 + read_skill_file
  - 1.4 执行前审查台(HITL,factor_spec 三层 + 便宜 validation_report + 风险自适应门)
  - 1.5 Session + 记忆系统(三层四流动:Session / 长期记忆 / 持久记录,含自动 consolidation + "只喂默认不静默改假设"铁律)
  - 1.6 远程计算接口预留(ExecutionBackend,local 实装 / remote stub)
- **架构基建**:coordinator 拆分、SubAgent 抽象(Critic + 记忆固化两个实例)、manifest 审计段(delegations/sandbox_usage/mcp_calls/staging/applied_memory_defaults/memory_events)。
- **5.1 Golden runs 纪律**:[tests/golden_run_registry.py](tests/golden_run_registry.py)(6 个 case,覆盖 lookahead/overfit/robust-classic/regime 四类)+ [tests/test_golden_run_discipline.py](tests/test_golden_run_discipline.py)(逐 case 断言 + 汇总表)+ [.github/workflows/tests.yml](.github/workflows/tests.yml)(仓库首个 CI,push to main 触发,无需密钥)。已实测验证阈值改动能被精确抓到。
- **5.2 Alpha 生命周期 + Paper Tracking**(合并第一章「每日快照」一起做):因子状态机 `research→paper_tracking→live_candidate→decayed→retired`([quantbench/factors/lifecycle.py](quantbench/factors/lifecycle.py) 纯函数 + [FactorStore.transition_lifecycle](quantbench/factors/store.py) 审计持久化,`retired` 仅可显式触发);Paper tracking 累计层([quantbench/factors/paper_tracking.py](quantbench/factors/paper_tracking.py),复用既有 `refresh_and_backtest`/`compute_decay_report`,不新造数据管道或衰减算法);crypto 每日 universe 快照([warehouse.py](quantbench/data/warehouse.py) 新表,`quantbench universe snapshot-crypto`)。调度用本地轮询循环(`quantbench factor track --watch`,同构 `monitor watch`),未接 GH Actions cron(状态持久化在无状态 runner 上不合适)。**过程中发现并修复一个真实 bug**:`run_paper_tracking_pass` 曾只转发 `store` 不转发 `tracking_store`,导致自定义 FactorStore 目录时 paper-tracking 历史会写去默认路径(手动验证时实际把测试数据写进了真实项目目录)——已修复为从 `store.factors_dir` 派生,并补上一直缺失的 `factors/` 到 `.gitignore`。

---

## 三、剩余缺口(诚实标注 partial vs 未做,附代码依据)

### 第一章 · 数据地基(🟡 剩外部依赖项)
- [ ] **Crypto point-in-time 重建**([GAP 1.1](GAP_ANALYSIS.md)):当前用今日成交量排名回填历史,截面结论仍带非-PIT 警告。每日快照(`quantbench universe snapshot-crypto`)**已开始积累**,但用累积数据重建 PIT universe 是后续增量(需要攒够时间跨度)。
- [ ] **Equity 退市标的数据源**(1.2):yfinance 对已退市股票的数据不可靠,需评估付费源。Crypto 侧的每日快照方案已落地(见「二、已完成」5.2)。
- [ ] **数据分片保留策略**(1.4):跑过 run 的数据分片可能被缓存淘汰,影响 bit-level 重放。
- [ ] **`PerpetualData` schema + open_interest**(1.5):funding 已建模,OI 字段未落地。

### 第四章 · 产品形态(🟡 剩少数)
- [ ] **4.3 文献接入(未做)**:PDF/arXiv → 提取因子定义 → 生成 compute → 走审查流程 + 复现对比表。这是 SubAgent 抽象的天然第三个实例(继 Critic、记忆固化之后),差异化价值高。
- [ ] **4.4 内置 provider 信任分层**(partial):MCP 外部工具已打 `external_data_unverified`;内置一等 provider 的信任等级区分未完全成形。
- [ ] **4.5 Docker 沙箱**(设计推后):受限子进程已覆盖 80%;macOS 上 RLIMIT_AS 无效是已知平台差异。真实需要更强隔离时再上。
- [ ] 审查台/CLI 交互增强(staging 的完整 plan-first 上游对象、CLI 内联编辑)——非阻塞增强项。

### 第五章 · roadmap 缺失的整块议题(🟡 5.1+5.2 已完成,余下未做)
- [x] **5.1 Golden runs 纪律**——已完成,见上「二、已完成」。
- [x] **5.2 Alpha 生命周期 / paper tracking**——已完成,见上「二、已完成」。CUSUM 未做(复用既有比值判定,足够 v1);equity 退市数据源仍待评估(见第一章)。
- [ ] **5.3 信号导出**(未做):通过审查的因子 → 当期目标权重 JSON/Parquet(含时间戳、数据版本、因子 hash、完整溯源)。研究→生产的交接面。
- [ ] **5.4 成本/用量可观测性**(🟡 partial):`sandbox_usage`(CPU/内存/wall)**已有**;LLM token 用量+成本、数据 API 调用数、screen 前成本预估**未做**。记忆 consolidation 目前每轮 turn 跑一次 LLM SubAgent,是一处可优化的 per-turn 成本。

---

## 四、建议下一步(带排序理由)

沿项目既有"先正确性、后体验"原则,建议顺序:

### 🥇 已完成:5.1 Golden runs 纪律
### 🥈 已完成:5.2 Alpha 生命周期 / paper tracking + crypto 每日快照

### 🥉 第一优先:第一章数据收尾(crypto PIT 重建 + equity 退市源 + PerpetualData)
crypto 每日快照基建已经在跑(5.2 交付),接下来是等快照积累到足够跨度后用它重建 PIT universe,以及评估 equity 侧的付费退市数据源。
- 规模:中(有外部数据依赖,费工;PIT 重建部分需要先攒时间)。风险:中。

### 后续收尾(低优先、可穿插)
- **5.3 信号导出**:研究→生产交接面。用户当前不做实盘,优先级低,但一旦要接自己的交易系统就需要。规模小。
- **5.4 可观测性补全**:LLM token/成本 + screen 成本预估。`sandbox_usage` 已铺好 manifest 位,增量小。**顺带**:记忆 consolidation 每轮 turn 跑一次 LLM SubAgent 的 per-turn 成本,可在此一并优化(降频/session 末再跑)。
- **4.3 文献接入**:差异化价值高但非正确性,SubAgent 第三实例(继 Critic、记忆固化、之后可能的第四实例之后),可在任意窗口插入。

---

## 五、一句话建议

**5.1 锁住了已建成的判断质量,5.2 把系统推过了"研究平台 vs 回测玩具"的分水岭(因子状态机 + paper tracking + crypto 每日快照三件套一次做完,复用度很高)。下一步建议做第一章数据收尾——crypto PIT 重建(快照基建已在跑,等积累)和 equity 退市数据源评估。**

---

*本文件为活文档,随阶段推进更新;权威缺口清单仍以 [GAP_ANALYSIS.md](GAP_ANALYSIS.md) 勾选项为准。*

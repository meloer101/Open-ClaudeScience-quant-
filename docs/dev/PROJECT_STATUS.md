# QuantBench 现状盘点与下一步建议

> 快照日期:2026-07-04 | 对照 [GAP_ANALYSIS.md](GAP_ANALYSIS.md) 全六章 + 已落地代码逐项核对。
>
> 一句话现状:**GAP 六章全部主体完成。** 剩下的全是明确标注、真正受外部条件卡住的零碎项(equity 付费退市源、crypto PIT 数据积累时间、执行耗时细分、文献接入、Docker)。系统已从"一句话→一次 run 的批处理器"演进为"可对话、可确认、可扩展、可审计、有记忆、有生命周期管理、可导出信号"的研究平台。

---

## 一、完成度总览

| 章节 | 主题 | 状态 | 备注 |
|---|---|---|---|
| 一 | 数据地基 | 🟡 主体完成 | PIT S&P500 / 时变 universe / funding / 版本锁定 / crypto 每日快照 / crypto PIT 重建 / provider 退市能力自动标记 均已做;剩 equity 付费退市源(外部依赖)、PerpetualData schema |
| 二 | 统计严谨性 | ✅ 完成 | DSR / PBO / walk-forward / CPCV / bootstrap / IC 显著性(Phase 10/10.5) |
| 三 | 回测现实性 | ✅ 完成 | 执行价 / 流动性成本+容量 / borrow / 中性化(Phase 12)+ beta 中性化修复 |
| 四 | 产品形态 | 🟡 基本完成 | 沙箱 / MCP / SKILL.md / 审查台 / Session+记忆 / 远程接口(PHASE13B);剩 4.3 文献接入、4.5 Docker(推后) |
| 五 | roadmap 缺失议题 | ✅ 全部完成 | 5.1 golden runs 纪律、5.2 Alpha 生命周期/paper tracking、5.3 信号导出、5.4 成本可观测性——均已落地 |
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
- **收尾四件套**(观测性 + provider 能力标记 + crypto PIT + 信号导出,一起做完):
  - **5.4 成本可观测性**:`ctx.llm_usage` accumulator(照抄 `sandbox_usage`/`mcp_calls` 模式)记录每次 LLM 调用的 token/成本(复用 litellm 自带 `completion_cost`,不手搓定价表);`run_subagent` 新增 `usage_sink`,Critic 和记忆固化 SubAgent 的开销首次可见;`screen_factors` 返回 `cost_estimate` 字段(复用 1.4 的 `CostEstimate`,只做可见不叠加新阻塞门)。
  - **1.2 Provider 退市能力标记**:`ProviderResult.covers_delisted` 由 provider 自己声明,`fetch_universe_ohlcv` 保守聚合(任一 symbol 未覆盖/拉取失败即视为不覆盖)后自动写回 `UniverseDefinition.covers_delisted`——修了一个真实的时序 bug:该值原本在 `universe_coverage_report` 内被读取时仍是聚合前的旧值,现已改为聚合后再传入。
  - **1.1 Crypto PIT 重建**:[build_point_in_time_crypto_perpetual](quantbench/data/universe.py) 从累积快照重建 membership intervals,算法上"快照覆盖有间断就断开区间,不假装连续"(不同于 S&P500 的完整变更事件日志,这里是稀疏日采样);代码完整、可测,真实可用性随快照积累时间自然改善。
  - **5.3 信号导出**:`CrossSectionalBacktestResult` 新增 `weights` 字段(内部早已算出,只是没返回);`monitor/pipeline.py` 的 `refresh_and_backtest` 拆出私有 `_refresh_and_recompute` 共享刷新逻辑,新增 `refresh_and_recompute_weights` 取最新一期权重;`quantbench/factors/signal_export.py` + `quantbench factor export <name>` 组装完整导出(权重+因子版本 hash+溯源+已知局限),v1 仅覆盖截面因子。

---

## 三、剩余缺口(诚实标注 partial vs 未做,附代码依据;真正受外部条件卡住的项)

### 第一章 · 数据地基(🟡 剩两项外部依赖)
- [ ] **Equity 退市标的数据源**(1.2):yfinance 对已退市股票的数据不可靠,需付费源(Polygon 等,需用户自己的 API key/订阅)。Provider 能力标记机制已就绪(见「二、已完成」),接入时只需把 `covers_delisted=True` 设到位即自动生效,不需要再改传播逻辑。
- [ ] **`PerpetualData` schema + open_interest**(1.5):funding 已建模,OI 字段未落地。
- [ ] **数据分片保留策略**(1.4):跑过 run 的数据分片可能被缓存淘汰,影响 bit-level 重放。
- **Crypto point-in-time 重建**:代码已完整落地(见「二、已完成」),**不再是缺口**——剩下的只是"快照攒够时间跨度"这件事,会随时间自然发生,不需要额外工程。

### 第四章 · 产品形态(🟡 剩两项,均为刻意推后)
- [x] **4.3 文献接入已落地**:支持 arXiv ingest、本地 PDF 上传/CLI ingest、paper viewer、selection-grounded QA、paper-to-run reproduce。安全修订后，Web/API 不再接受裸本地路径，本地 PDF 通过上传接口导入。
- [ ] **4.5 Docker 沙箱**(设计推后):受限子进程已覆盖 80%;macOS 上 RLIMIT_AS 无效是已知平台差异。真实需要更强隔离时再上。
- [ ] 审查台/CLI 交互增强(staging 的完整 plan-first 上游对象、CLI 内联编辑)——非阻塞增强项。

### 第五章 · roadmap 缺失的整块议题 —— ✅ 全部完成
5.1 golden runs 纪律、5.2 Alpha 生命周期/paper tracking、5.3 信号导出、5.4 成本可观测性均已落地(见上「二、已完成」)。CUSUM(5.2 的一个加分项)未做,复用既有比值判定已足够 v1。

---

## 四、建议下一步

GAP 六章目前**没有正确性缺口**了——剩下的两项(equity 付费数据源、Docker 沙箱)都需要用户主动决定(掏钱买数据源 / 真的需要更强隔离时再上),不是"下一步该写什么代码"的问题。文献接入(4.3)是唯一一个纯工程、differentiation 导向、随时可插入的增量项,可以作为下一个可选目标,但不再有"必须做"的紧迫性。

---

## 五、一句话建议

**GAP_ANALYSIS 六章主体已全部完成。剩下的都是需要用户决策(是否购买付费数据源、是否需要 Docker 级隔离)或纯粹等时间(crypto 快照积累)的项,唯一还值得主动推进的纯工程增量是 4.3 文献接入。**

---

*本文件为活文档,随阶段推进更新;权威缺口清单仍以 [GAP_ANALYSIS.md](GAP_ANALYSIS.md) 勾选项为准。*

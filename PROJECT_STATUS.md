# QuantBench 现状盘点与下一步建议

> 快照日期:2026-07-04 | 对照 [GAP_ANALYSIS.md](GAP_ANALYSIS.md) 全六章 + 已落地代码逐项核对。
>
> 一句话现状:**GAP 第二章(统计严谨性)、第三章(回测现实性)、第四章(产品形态)已基本闭合;第一章(数据地基)主体完成、剩零散外部依赖项;第五章(roadmap 缺失的整块议题)是当前最大的未开垦地。** 系统已从"一句话→一次 run 的批处理器"演进为"可对话、可确认、可扩展、可审计、有记忆"的研究平台。

---

## 一、完成度总览

| 章节 | 主题 | 状态 | 备注 |
|---|---|---|---|
| 一 | 数据地基 | 🟡 主体完成 | PIT S&P500 / 时变 universe / funding / 版本锁定已做;剩 crypto PIT、退市源、PerpetualData schema |
| 二 | 统计严谨性 | ✅ 完成 | DSR / PBO / walk-forward / CPCV / bootstrap / IC 显著性(Phase 10/10.5) |
| 三 | 回测现实性 | ✅ 完成 | 执行价 / 流动性成本+容量 / borrow / 中性化(Phase 12)+ beta 中性化修复 |
| 四 | 产品形态 | 🟡 基本完成 | 沙箱 / MCP / SKILL.md / 审查台 / Session+记忆 / 远程接口(PHASE13B);剩 4.3 文献接入、4.4 provider 信任层、4.5 Docker(推后) |
| 五 | roadmap 缺失议题 | 🔴 主体未做 | 5.1 golden runs(fixture 已有、纪律未建全)、5.2 Alpha 生命周期(监控已有、状态机/paper 未做)、5.3 信号导出(未做)、5.4 可观测性(部分) |
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

---

## 三、剩余缺口(诚实标注 partial vs 未做,附代码依据)

### 第一章 · 数据地基(🟡 剩外部依赖项)
- [ ] **Crypto point-in-time**([GAP 1.1](GAP_ANALYSIS.md)):当前用今日成交量排名回填历史,截面结论仍带非-PIT 警告。
- [ ] **退市标的数据源**(1.2):crypto 退市永续 / equity 退市股票的历史 OHLCV 无获取路径。最低成本方案是"每日快照当前 universe,自然积累无偏差数据"——**与 5.2 paper tracking 共用同一套快照机制**。
- [ ] **数据分片保留策略**(1.4):跑过 run 的数据分片可能被缓存淘汰,影响 bit-level 重放。
- [ ] **`PerpetualData` schema + open_interest**(1.5):funding 已建模,OI 字段未落地。

### 第四章 · 产品形态(🟡 剩少数)
- [ ] **4.3 文献接入(未做)**:PDF/arXiv → 提取因子定义 → 生成 compute → 走审查流程 + 复现对比表。这是 SubAgent 抽象的天然第三个实例(继 Critic、记忆固化之后),差异化价值高。
- [ ] **4.4 内置 provider 信任分层**(partial):MCP 外部工具已打 `external_data_unverified`;内置一等 provider 的信任等级区分未完全成形。
- [ ] **4.5 Docker 沙箱**(设计推后):受限子进程已覆盖 80%;macOS 上 RLIMIT_AS 无效是已知平台差异。真实需要更强隔离时再上。
- [ ] 审查台/CLI 交互增强(staging 的完整 plan-first 上游对象、CLI 内联编辑)——非阻塞增强项。

### 第五章 · roadmap 缺失的整块议题(🔴 最大未开垦地)
- [ ] **5.1 Golden runs 纪律**(🟡 partial):fixture 集 [test_phase10_golden_runs.py](tests/test_phase10_golden_runs.py) **已存在**;但"每次改 prompt/换模型/调阈值后跑评测集、输出 verdict 混淆矩阵、纳入 CI"的**纪律未建全**。系统这半年积累了巨量 Reviewer findings 与 verdict 逻辑,却没有回归锁——prompt 一改可能整体漂移无人察觉。**成本低、保护面最大。**
- [ ] **5.2 Alpha 生命周期 / paper tracking**(🟡 partial):live 监控 + 衰减预警([monitor/decay.py](quantbench/monitor/decay.py))**已有**;但**因子状态机**(`research → paper_tracking → live_candidate → decayed → retired`)、**paper tracking**(对 ≥PROMISING 因子每日算假想收益)、**统计衰减判定**(CUSUM/滚动检验)**未做**。这是"研究平台 vs 回测玩具"的分水岭,**且已被 Session/记忆系统解锁**(session 天然是一组相关因子的容器)。
- [ ] **5.3 信号导出**(未做):通过审查的因子 → 当期目标权重 JSON/Parquet(含时间戳、数据版本、因子 hash、完整溯源)。研究→生产的交接面。
- [ ] **5.4 成本/用量可观测性**(🟡 partial):`sandbox_usage`(CPU/内存/wall)**已有**;LLM token 用量+成本、数据 API 调用数、screen 前成本预估**未做**。

---

## 四、建议下一步(带排序理由)

沿项目既有"先正确性、后体验"原则,建议顺序:

### 🥇 第一优先:5.1 Golden runs 纪律(最高性价比)
**为什么先做**:系统刚在半年内堆了 sandbox/MCP/审查台/记忆/一整套新 Reviewer findings 与 verdict 逻辑——**改动面最大、却没有判断质量的回归锁**。fixture 已在手,缺的是把它变成"每次 prompt/模型/阈值改动后强制跑 + 混淆矩阵 + CI"的纪律。成本最低、保护刚建成的一切,**应立刻做**。
- 规模:小。依赖:无(fixture 已有,合成数据)。风险:低。

### 🥈 第二优先:5.2 Alpha 生命周期 / paper tracking(最大产品跃迁)
**为什么第二**:这是"研究平台"真正成立的最后一块,而且 **Session/记忆刚落地已解锁它**(session = 一组相关因子的容器)。监控/衰减已有,补上"因子状态机 + 每日 paper tracking + 统计衰减判定"即闭环。
- 规模:中大。依赖:每日数据快照机制(与第一章 1.2 退市数据的"每日快照"共用,一举两得)。风险:中(需长期运行的定时任务)。

### 🥉 第三优先:第一章数据收尾(crypto PIT + 退市快照 + PerpetualData)
**为什么第三**:crypto 截面结论至今带非-PIT 警告——这是正确性缺口。且"每日快照"机制**同时喂 5.2 的 paper tracking**,与第二优先天然合并。
- 规模:中(有外部数据依赖,费工)。风险:中。

### 后续收尾(低优先、可穿插)
- **5.3 信号导出**:研究→生产交接面。用户当前不做实盘,优先级低,但一旦要接自己的交易系统就需要。规模小。
- **5.4 可观测性补全**:LLM token/成本 + screen 成本预估。`sandbox_usage` 已铺好 manifest 位,增量小。**顺带**:记忆 consolidation 目前每轮 turn 跑一次 LLM SubAgent,是 per-turn 成本,可在此一并优化(降频/session 末再跑)。
- **4.3 文献接入**:差异化价值高但非正确性,SubAgent 第三实例,可在任意窗口插入。

---

## 五、一句话建议

**立刻做 5.1(锁住已建成的判断质量),然后把 5.2 paper tracking 与第一章"每日快照"合并成一个"Alpha 生命周期 + 数据积累"的阶段做——这两件共用同一套每日快照基建,一起做省一半工,且正好把系统推过"研究平台"的分水岭。**

---

*本文件为活文档,随阶段推进更新;权威缺口清单仍以 [GAP_ANALYSIS.md](GAP_ANALYSIS.md) 勾选项为准。*

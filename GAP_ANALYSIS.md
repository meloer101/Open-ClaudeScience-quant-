# QuantBench 缺口分析与后续开发路径

> 缺口分析文档 v1.0 | 2026-07-03
>
> 基于对 VISION.md、PHASE0–9 + PHASE_UI 全部规划文档、`quantbench/` 全部模块（data / engine / review / portfolio / agent / skills / library / api）、tests 和 web 端的完整审查。
>
> 对标产品：Claude Science（Anthropic 面向科学家的 AI 研究工作台）。本文档回答两个问题：
> 1. 对一个**真实生产级量化研究平台**来说，现有实现缺什么？
> 2. 现有 roadmap（Phase 0–9）里**整块没有规划到**的议题是什么？

---

## 〇、总体判断

**Agent 架构层（Claude Science 骨架）已经相当完整**，且是很多同类项目做不对的部分：

- Coordinator + 确定性 Reviewer + 独立 LLM Critic 的 actor-critic 结构
- Artifact 溯源（代码 + 参数 + 指标 + manifest 落盘）
- 实验库 / 谱系 / fork / compare
- Factor Library + Workflow Skills 两套沉淀机制
- "模型写创意、代码写基础设施"的边界准则（VISION 第十一节）

**真正的残缺不在 agent 架构层，而在量化研究本身的三个硬核层：**

1. **数据的 point-in-time 正确性**（第一章）
2. **统计推断的严谨性**（第二章）
3. **回测的现实性**（第三章）

这三层是"研究结论可信"的地基，也是目前 roadmap 里基本没有铺路的地方。第四章是对标 Claude Science 的产品形态缺口，第五章是 roadmap 本身缺失的整块议题，第六章给出建议的开发顺序。

---

## 一、数据层缺口（最大的缺口，roadmap 里最缺规划的）

现状是"**诚实标注偏差**"而不是"**消除偏差**"。诚实标注（`universe.py` 里的 `survivorship_bias_note`、crypto universe 的 non-point-in-time 警告）是对的第一步，但对生产级研究来说不够：**在有幸存者偏差的 universe 上，动量/反转类因子的截面结果连方向都可能是错的**，Reviewer 再严格也审不出来——因为偏差在数据进入回测之前就已经发生。

### 1.1 Point-in-time universe（优先级：🔴 最高）

**现状**：
- S&P 500 支持当前成分股快照（显式标注 survivorship bias）和基于 Wikipedia 变更表重建的 point-in-time membership intervals。
- Crypto 用**当前** 24h 成交量 Top-N USDT 永续合约，显式标注非 point-in-time。

**缺什么**：
- [x] S&P 500 历史成分股变更表（Wikipedia 有完整的加入/剔除历史，可解析；或购买正式数据）。给定任意 as_of_date，返回当时的真实成分。
- [ ] Crypto 历史成交量快照重建：按历史某日的 24h/30d 成交量排名构建当时的 Top-N，而不是用今天的排名回填历史。
- [x] `UniverseDefinition.point_in_time = True` 路径的真正实现（当前 `universe.py` 中 `point_in_time=True` 分支是拒绝/未实现的）。
- [x] 回测引擎支持**时变 universe**：成分股在回测期内进出，因子截面只在当日成分内计算。这对 `cross_sectional_backtest.py` 是一个结构性改动（当前假设 panel 内 symbol 集合固定）。

**验收标准**：同一个 20 日动量因子，在 point-in-time S&P 500 和当前快照 S&P 500 上分别回测，系统能并排展示两者差异，research note 明确说明使用了哪种 universe。

### 1.2 退市标的的数据获取（优先级：🔴 高）

**现状**：VISION Phase 1 验收标准写了"含退市合约"，但 CCXT provider（`ccxt_perpetual.py`）实际只能拉当前在市合约；退市合约的历史 OHLCV 没有获取路径。美股侧同理，yfinance 对已退市股票的数据不可靠。

**缺什么**：
- [ ] Crypto：评估退市永续合约历史数据来源（交易所归档 / Tardis / 自建快照积累）。最低成本方案：从现在开始每日快照当前 universe 与行情，随时间自然积累无偏差数据。
- [ ] Equity：评估含退市股票的数据源（见 1.3）。
- [x] 在 universe 元数据中记录"本 universe 覆盖退市标的：是/否"，Reviewer 对"否"的 PIT 截面 run 输出结构性警告并影响 verdict 上限（例如封顶 PROMISING，不给 STRONG）。

### 1.3 数据源健壮性与正式数据源抽象位（优先级：🟡 中高）

**现状**：美股默认来源仍是 yfinance；`ProviderResult` 已记录 adjustment/fallback metadata，并已留出 Polygon schema 映射 stub，但真实付费源尚未启用。

**缺什么**：
- [x] Provider 抽象已存在（`providers/base.py`），但需要为至少一个**可付费正式数据源**留好实现位（Polygon / Tiingo / Databento / Tardis 等），并明确各字段的 schema 映射。
- [x] 复权方式显式记录：前复权 / 后复权 / 分红是否再投，写入 dataset 元数据和 research note。当前 `adjusted: bool` 一个布尔值不足以描述。
- [x] 数据源降级策略：主源失败时的行为（报错终止 vs 降级并警告），不允许静默切换。

### 1.4 数据版本锁定的完整闭环（优先级：🟡 中高）

**现状**：manifest 已记录 run 级 `data_hash` 和分片级 `data_slices`；`quantbench rerun <run_id>` 已能校验缓存分片 hash 并在漂移时硬失败。完整自动重放 run 配置并 bit-level 重算指标仍未完成。

**缺什么**：
- [x] 每次 run 在 manifest 中记录所用每个数据分片的内容 hash + 行数 + 时间范围。
- [x] `quantbench rerun <run_id>` 命令：优先使用缓存中 hash 匹配的数据分片；若缓存已失效或数据 hash 不匹配，显式报告"数据已漂移，结果不可直接对比"。
- [ ] 数据分片的保留策略（跑过 run 的数据分片不被缓存淘汰，或淘汰前归档）。

### 1.5 Funding rate 与持有成本建模（优先级：🔴 高，crypto 结论可信的前提）

**现状**：CCXT funding rate 拉取、DuckDB funding cache、截面引擎 funding 扣减和 Reviewer `funding_cost_sensitivity` 已接入；open interest 仍未落地。

**为什么致命**：永续多空组合里 funding 是一等成本项。做多高动量币种往往意味着持续支付正 funding，年化可以吃掉几十个百分点，足以把 Sharpe 1.5 的策略变成亏损。

**缺什么**：
- [x] `fetch_funding_rate` skill（CCXT 支持拉取历史 funding rate）。
- [x] 回测引擎在 crypto 永续场景下将 funding 计入持仓成本（按持仓方向逐期扣减）。
- [x] Reviewer 新增检查项：funding 计入前后的 Sharpe 对比（类似现有 cost_sensitivity 的结构）。
- [ ] 数据 schema 落地 VISION 中已定义的 `PerpetualData`（funding_rate / open_interest 字段）。

---

## 二、统计严谨性缺口（Reviewer 缺"多重检验"这条命门）

现有 Reviewer 检查项（未来函数、OOS 衰减、成本敏感、参数扰动、regime、tail、换手、beta、集中度）覆盖面不错，但都是**针对单个 run 的检查**。Phase 8 的 `screen_factors` 批量筛选制造了一类 Reviewer 检测不到的问题：

> **一次筛 20 个因子，即使全部是噪声，也大概率有 1–2 个 OOS Sharpe 好看。这是多重检验（multiple testing），不是 alpha。**

当前系统在没有统计护栏的情况下批量生产候选因子，这是**现在就在发生的最危险错配**——批量能力已上线，护栏没跟上。

### 2.1 多重检验修正 / Deflated Sharpe Ratio / PBO（优先级：🔴 最高）

**缺什么**：
- [x] **试验次数记账**：实验库记录"针对同一 universe × 时段，历史上总共试过多少个因子/参数组合"。这是所有修正方法的输入，且只有平台能自动做到（人工研究者自己都记不住）。
- [x] **Deflated Sharpe Ratio（DSR）**：给定试验次数 N 和候选 Sharpe 的方差，修正后的 Sharpe 显著性。作为 `screen_factors` 流水线的**强制输出列**。
- [x] **PBO（Probability of Backtest Overfitting）**：基于 CSCV（组合对称交叉验证）估计"样本内最优的配置在样本外表现低于中位数"的概率。
- [x] Reviewer verdict 规则接入：DSR 不显著或 PBO 过高时，封顶 verdict（不给 STRONG）。
- [x] 遵循 VISION 第十一节准则：DSR/PBO 的计算逻辑属于"必须绝对正确的基础设施"——**写成有测试的代码**，Critic/Coordinator 只解读结果。

### 2.2 Walk-forward / CPCV（优先级：🟡 中高）

**现状**：只有单一 train/test 切分（`out_of_sample.py`）。单次切分的 OOS 结果本身方差很大——运气好坏对 verdict 影响过大。

**缺什么**：
- [x] Walk-forward 多窗口验证：滚动切分多个 train/test 窗口，报告 OOS 指标的分布而不是单点。
- [x] CPCV（Combinatorial Purged Cross-Validation）：带 purge/embargo 的组合式交叉验证，防止相邻窗口的信息泄漏（信号有 lookback 时训练/测试边界会重叠）。
- [x] Purge/embargo 逻辑与因子 lookback 长度联动（可从 `compute()` 的 rolling / shift / ewm / pct_change 参数推断或通过 `lookback_bars` 显式声明）。

### 2.3 置信区间与显著性表达（优先级：🟡 中）

**现状**：research note 报告 Sharpe 1.42 单点值，无区间——对研究者是误导。

**缺什么**：
- [x] Bootstrap（block bootstrap，尊重收益自相关）计算 Sharpe / 年化收益的置信区间。
- [x] IC 的 t 统计量 / Newey-West 修正标准误。
- [x] Research note 模板改为报告"Sharpe 1.42 [95% CI: 0.6, 2.1]"格式，并在截面 IC 行展示 Newey-West t/p/lags；ChartsPanel 相应展示区间。

---

## 三、回测现实性缺口（成本与执行模型过于理想）

### 3.1 成本模型：从固定 bps 到流动性感知（优先级：🟡 中高）

**现状**：单一固定 `cost_bps`（默认 5bps）。

**缺什么**：
- [ ] **成交量参与率上限**：假设组合规模（如 $1M / $10M），每标的每期成交量不超过其日成交额的 x%（如 1–5%）；超限部分视为无法建仓。小币种/小盘股十分位组合在此约束下往往根本建不满仓。
- [ ] **随流动性分层的价差成本**：按标的成交额分层设定 spread 假设（大盘 2bps / 小盘 20bps），而不是全 universe 一个数。
- [ ] Reviewer 新增检查项：容量估算——策略在多大规模下 Sharpe 衰减到不可接受，作为 research note 的标准输出（"该策略估计容量 $X"）。

### 3.2 做空可行性与 borrow cost（优先级：🟡 中，equity 截面必需）

**现状**：equity 十分位多空默认全部股票可做空、零 borrow cost。实际上空头腿最赚钱的部分往往是 hard-to-borrow 的小票。

**缺什么**：
- [ ] 空头腿的 borrow cost 假设（最低限度：按市值/流动性分层的固定费率假设，明确写进 config 和 note）。
- [ ] Reviewer 新增检查项：long-only 腿 vs short 腿的收益分解——如果收益主要来自 short 腿，输出"做空可行性存疑"警告。

### 3.3 执行价假设显式化（优先级：🟡 中，成本低收益大）

**现状**：信号在 t 期生成后用什么价格成交，埋在引擎代码里，未在 config / research note 中显式化。

**缺什么**：
- [ ] 在 config 中显式声明执行假设：`execution: {signal_time: close_t, fill_price: open_t+1 | close_t+1}`。
- [ ] Research note 标准段落说明执行假设。
- [ ] （加分项）close_t 成交 vs open_t+1 成交的双口径对比，两者差异大本身就是"策略依赖不可实现的即时成交"的信号。

### 3.4 中性化与极简风险模型（优先级：🔴 高）

**现状**：截面因子研究的标准操作——市值/行业/beta 中性化——引擎里没有。VISION Phase 4 自己承认 Risk Attribution 留了缺口（"没有因子模型数据源"）。

**为什么重要**：没有中性化，"momentum 因子有效"可能只是"做多了高 beta"或"做多了某个行业"。现有的 beta_exposure 检查只是事后诊断，中性化是事前处理。

**缺什么**：
- [ ] 极简风险模型 v1：市场 beta + size（对数市值）+ 行业哑变量（美股用 GICS sector，crypto 可用板块标签），对因子值做截面回归取残差。**不需要买 Barra**，这三个维度就能解决 80% 的问题。
- [ ] 回测配置项 `neutralize: [beta, size, sector]`，默认开启中性化并在 note 中报告中性化前后的对比。
- [ ] 用同一个风险模型解锁 Phase 4 遗留的 Risk Attribution 图表：组合收益分解为因子暴露收益 + 残差 alpha。
- [ ] 数据依赖：市值数据（yfinance 可取）、行业分类（S&P 500 的 GICS 可从成分表获取）。

---

## 四、对标 Claude Science 的产品形态缺口

### 4.1 多轮对话式 session（优先级：🟡 中高）

**现状**：Coordinator 是"一句话 → 一次 run"的批处理模式。Fork 部分弥补，但真正的 interactive session 没有。

**Claude Science 的核心体验**是研究对话：追问、修改、中途转向、"把手续费改成 10bps 再看看"在同一上下文里连续发生。

**缺什么**：
- [ ] Session 概念：一个 session 包含多轮对话 + 多个 run，对话历史作为上下文传给后续轮次。
- [ ] Web 端从"提交 run 表单"演进为"对话流 + 内嵌 run 卡片"。
- [ ] Session 本身成为 artifact 的一部分（Claude Science：溯源包含对话历史）。

### 4.2 计划确认环节（human-in-the-loop）（优先级：🟡 中）

**现状**：VISION 5.1 设计了 Coordinator 生成计划后暂停确认（"数据范围？手续费假设？"），当前实现直接执行。

**缺什么**：
- [ ] Coordinator 两阶段模式：先输出结构化研究计划（步骤、数据需求、默认假设、预计耗时），等用户确认/修改后再执行。
- [ ] CLI 用交互式 y/n + 参数覆盖；Web 用计划卡片 + 编辑确认。
- [ ] 计划与实际执行的 diff 记入 manifest（审计"模型说要做什么 vs 实际做了什么"）。

### 4.3 文献接入：论文 → 假设来源（优先级：🟠 中低，但差异化价值高）

Claude Science 有 literature 连接器。量化对应物："**复现这篇论文的因子**"是真实高频 use case（arXiv q-fin / SSRN）。

**缺什么**：
- [ ] 输入 PDF/arXiv 链接 → Coordinator 提取因子定义 → 生成 `compute()` → 走标准回测审查流程。
- [ ] Research note 记录假设来源（论文引用），实验库支持按来源检索。
- [ ] 复现结果与论文报告结果的对比表（往往对不上——这本身就是有价值的研究发现）。

### 4.4 技能生态可扩展性（优先级：🟠 中低）

**现状**：Skill registry 是内置固定集合。Workflow Skills（markdown 注入）解决了"流程沉淀"，但用户无法安全添加新的**可执行工具**（如接自己的数据源）。Claude Science 是 60+ connectors 的生态。

**缺什么**：
- [ ] ~~插件化 provider 接口（自研）~~ → **已决策改用 MCP client 方案，见 7.2**：用户通过外部 MCP server 接入自己的数据源/工具，无需自研插件协议。
- [ ] 内置一等 provider（有质量校验、可获信任等级的数据源）仍走 `providers/base.py` 抽象，与 MCP 外部工具（untrusted）区分信任层级。

### 4.5 执行沙箱（优先级：🟡 中高，生产化前必须还的债）

**现状**：模型生成的 `compute()` 代码经 `codeexec.py` 用 subprocess 直接执行。VISION 技术选型写明 "subprocess (MVP) → Docker sandbox"。

**缺什么**：
- [ ] Docker（或至少受限 venv + 资源限制 + 网络隔离）沙箱执行模型生成代码。
- [ ] 超时/内存上限（防止模型写出死循环或内存爆炸的因子代码拖垮整机）。
- [ ] 文件系统访问白名单（只读数据目录 + 只写 artifact 目录）。

### 4.6 远程计算（优先级：🟠 低，规划中已有）

VISION Phase 5 的 SSH/Modal 支持未实现。批量因子筛选 + CPCV + bootstrap 会显著抬升计算量，届时本地单机会成为瓶颈。可以等第二章落地后再做。

---

## 五、Roadmap 本身缺失的整块议题

以下议题在 Phase 0–9 + Phase 6（生产化）的任何文档中**都没有出现**，需要新增规划：

### 5.1 系统自身的评测集（golden runs）（优先级：🔴 高，成本低收益大）

Claude Science 背后有 eval 文化。QuantBench 的 Coordinator/Reviewer/Critic 的判断质量目前**没有任何回归保障**——prompt 改一版、模型换一代，verdict 可能整体漂移而无人察觉。

**缺什么**：
- [ ] 一组 golden runs 固定评测集：
  - 已知含未来函数的因子（Reviewer 必须抓到）
  - 已知过拟合的因子（参数扰动/OOS 必须暴露）
  - 已知稳健的经典因子（不应被误杀）
  - 已知 regime 依赖的因子
- [ ] 每次修改 prompt / 升级模型 / 改 Reviewer 阈值后跑评测集，输出 verdict 混淆矩阵。
- [ ] 纳入 CI（合成 fixture 数据即可，不依赖外部 API）。

### 5.2 Alpha 生命周期管理（优先级：🟡 中，Phase 6 需要展开）

Phase 6 只有 "Live signal monitoring / 策略衰减预警" 两行字。**研究 → 纸面跟踪 → 衰减判定 → 退役**这个闭环是"研究平台"和"回测玩具"的分水岭。

**缺什么**：
- [ ] Paper tracking：对 verdict ≥ PROMISING 的因子，每日增量拉数据、计算信号、记录"如果按信号交易"的假想收益（无真实下单，符合产品边界）。
- [ ] 衰减判定规则：live 期 IC/Sharpe 与回测期的统计对比（CUSUM 或滚动窗口检验），触发衰减警告。
- [ ] 因子状态机：`research → paper_tracking → live_candidate → decayed → retired`，Factor Library 记录状态流转历史。
- [ ] 这也是对 point-in-time 数据积累（1.2）的天然补充——每日快照即无偏差数据。

### 5.3 信号导出格式（研究 → 生产的交接面）（优先级：🟠 中低）

平台边界是"不做自动交易"，但真实用户的下一步是把通过审查的因子接入自己的交易系统。

**缺什么**：
- [ ] 标准化信号导出：给定因子 + universe，输出当期目标权重的 JSON/Parquet（含时间戳、数据版本、因子版本 hash）。
- [ ] 导出内容附带完整溯源引用（来自哪个 run、什么 verdict、已知局限），让"可审计"延伸到交接面。

### 5.4 成本与用量可观测性（优先级：🟠 低）

- [ ] 每次 run 记录 LLM token 用量与成本、数据 API 调用次数、执行耗时分解，写入 manifest。
- [ ] 批量筛选（screen_factors）前给出成本预估。

---

## 六、建议的开发顺序

按"先正确性、后体验"原则（与项目既有原则一致），建议顺序如下。每个阶段可对应一个新的 PHASE 文档。

### 第一优先级：统计护栏（建议 Phase 10）

**理由**：批量筛选能力已上线，多重检验护栏没跟上——系统现在就在批量生产统计上不可信的候选因子。这是当前最危险的错配，且不依赖新数据源，纯计算逻辑，可立即开工。

- 试验次数记账（实验库层面）
- Deflated Sharpe Ratio 强制输出（2.1）
- PBO / CSCV（2.1）
- Walk-forward 多窗口（2.2）
- Bootstrap 置信区间 + note 模板更新（2.3）
- Golden runs 评测集（5.1，与本阶段一起建立，用来锁定新检查项的行为）

### 第二优先级：数据地基（建议 Phase 11）

**理由**：决定截面结论的方向是否可信。最费工、有外部依赖，越晚开始越被动。

- Point-in-time S&P 500 成分（1.1）
- 时变 universe 回测支持（1.1）
- Funding rate 拉取 + 建模（1.5）
- 每日快照积累机制（1.2 + 为 5.2 铺路）
- 数据版本锁定闭环 + rerun 命令（1.4）
- 正式数据源抽象位（1.3）

### 第三优先级：让"这是 alpha"这句话成立（建议 Phase 12）

- 极简风险模型：beta + size + sector（3.4）
- 截面中性化选项 + 前后对比（3.4）
- Risk Attribution 图表（还掉 Phase 4 遗留缺口）
- 流动性感知成本模型 + 容量估算（3.1）
- Borrow cost / 做空可行性检查（3.2）
- 执行价假设显式化（3.3）

### 第四优先级：产品形态与生产化（建议 Phase 13+）

- coordinator.py 拆分 + SubAgent 抽象（7.1，重构先行）
- MCP client 接入外部数据工具（7.2，替代原 4.4 的自研插件接口方案）
- Skills 格式对齐 SKILL.md（7.3）
- Docker 沙箱（4.5，生产化前置条件）
- 多轮对话 session（4.1）
- 计划确认环节（4.2）
- Alpha 生命周期 / paper tracking（5.2）
- 文献接入（4.3）
- 信号导出（5.3）
- 远程计算（4.6）

---

## 七、架构决策：Agent 框架 / Sub-agent / MCP / Skills

> 2026-07-03 讨论后确定的方向。核心结论：**不引入 Agent 框架；引入 MCP（仅作为 client 使用外部 MCP server）；Workflow Skills 已等价于 Claude Code 的 Skills 模型，只需格式对齐。**

### 7.1 不引入 Agent 框架，Sub-agent 用自有抽象实现

**决策**：不采用 LangGraph / CrewAI / AutoGen 等编排框架，继续裸写 agent loop。

**理由**：
- Sub-agent 在实现层面就是"一次带独立 system prompt、独立工具子集、有预算上限的新 LLM 对话，结果以结构化形式返回父循环"。框架提供的是图编排、状态持久化、可视化调试——不提供任何自己写不出来的能力。
- 框架会带来两个致命代价：① **审计链断裂**——框架在调用链中插入隐式重试/状态/prompt 拼接，manifest 里出现解释不了的部分，破坏"每个影响结果的东西都进 manifest"的核心承诺；② 与 VISION 第十一节"模型写创意、代码写基础设施"准则冲突——编排逻辑必须是可测试的普通 Python。
- 系统**已经在裸写多 agent**：`review/critic.py` 就是一个独立 LLM 调用 + 独立 prompt + 结构化返回的 sub-agent；`screen_factors` 就是 fan-out 并发。缺的不是框架，是把已有模式提炼成抽象。

**任务**：
- [ ] **coordinator.py 拆分**（当前 1706 行，是真正的架构风险）：拆为 agent loop（通用对话循环）、run lifecycle（artifact/manifest/事件）、业务工具构建三块。纯重构，不加功能。
- [ ] **SubAgent 抽象**（约 150 行）：`name / system_prompt / registry（工具子集）/ max_turns（预算护栏）/ output_schema（强制结构化返回）`。父 Coordinator 把委派当成普通 tool 调用，每次委派记入 manifest（角色、输入、轮数、输出）。
- [ ] 将 Critic 迁移为第一个 SubAgent 实例，验证抽象成立。
- [ ] 后续新角色（数据勘察 agent、文献复现 agent、报告撰写 agent）均为填充该抽象，不引入新依赖。

**触发条款**：若底层模型策略全面转向 Claude，重新评估 Claude Agent SDK（原生自带 sub-agent / skills / MCP / 沙箱，即 Claude Code 全套骨架），但它锁定 Anthropic 模型，与当前 LiteLLM + DeepSeek 成本策略冲突，现阶段不采用。

### 7.2 MCP：作为 client 接入外部 MCP server

**决策**：QuantBench 作为 **MCP client**，让用户接入外部 MCP server（自有数据库、数据商 API、内部数据服务）。**不做** "QuantBench 作为 MCP server 供外部 agent 调用" 的方向。

**为什么合拍**：`SkillRegistry.schemas()` 输出的就是 function-call schema，MCP tool 的形状（name / description / inputSchema）与之一一对应。这直接解决 4.4 节"用户无法安全添加可执行工具"的缺口。

**任务**：
- [ ] 配置文件声明外部 MCP server（命令/URL、启用的 tool 白名单）。
- [ ] `MCPSkillAdapter`：基于官方 `mcp` Python SDK，把 MCP server 的 tool 动态注册进 `SkillRegistry`，Coordinator 无感知（预计一两百行）。
- [ ] **审计红线一**：每次 MCP tool 调用（server 名、tool 名、参数、结果 hash）记入 manifest，处理方式类比 `injected_skills`。
- [ ] **审计红线二**：MCP tool 返回的数据未经内置数据质量校验，不享受内置 provider 的信任等级。使用了外部 MCP 数据的 run 由 Reviewer 打上 `external_data_unverified` 警告，verdict 逻辑区别对待。
- [ ] MCP tool 的白名单默认只读（数据获取类）；执行类 / 有副作用的 MCP tool 需用户显式开启，且等 4.5 沙箱落地后再放开。

### 7.3 Skills：与 Claude Code 的 SKILL.md 约定对齐

**现状**：Workflow Skills（`skills_docs/*.md` + frontmatter `name`/`description`/`triggers`，按触发词注入，manifest 记录 `injected_skills`）在机制上**已经等价于** Claude Code 的 Skills 模型。差距只有三点增量：

- [ ] **格式对齐 SKILL.md 约定**：迁移为目录式 `skills_docs/<name>/SKILL.md` + 附属文件，实现与 Claude Code 生态的双向可移植（用户在 Claude Code 里写的量化 skill 直接可用，反之亦然）。
- [ ] **渐进式披露**：skill 可引用附属文件（参考表、示例代码），模型按需读取，而非全文一次性注入吃 context。
- [ ] **skill 内附带可执行脚本**：⚠️ 依赖 4.5 沙箱落地，否则等于给任意 markdown 开代码执行权。沙箱之前不开放。

### 7.4 落地顺序（归属第四优先级 Phase 13+ 内部排序）

1. coordinator.py 拆分 + SubAgent 抽象（重构先行，Critic 迁移验证）
2. MCP client + 两条审计红线（解锁外部数据源生态）
3. Skills 格式对齐 SKILL.md（低成本，随手做）
4. 沙箱落地后：skill 附带脚本、MCP 执行类 tool 放开

---

## 附：与 Claude Science 对照的差距总表

| Claude Science 能力 | QuantBench 现状 | 差距 | 对应章节 |
|---|---|---|---|
| 协调 Agent + 60+ 技能生态 | Coordinator + 固定内置技能 | 插件化扩展机制 | 4.4 |
| 完整溯源（代码+环境+对话） | 代码+参数+指标已有 | 对话历史、数据 hash 闭环 | 1.4 / 4.1 |
| Reviewer Agent 审查 | 确定性 Reviewer + Critic ✅ | 多重检验维度缺失 | 2.1–2.3 |
| 原生领域可视化 | 9 类图表 ✅ | Risk Attribution（依赖风险模型） | 3.4 |
| 自有基础设施运行 | 本地 subprocess | 沙箱、远程计算 | 4.5 / 4.6 |
| Session forking | Fork + 谱系 ✅ | 多轮对话式 session | 4.1 |
| Actor-Critic | Reviewer + Critic ✅ | 系统自身评测集 | 5.1 |
| Literature 连接器 | 无 | 论文→因子复现管线 | 4.3 |
| 计划确认（human-in-the-loop） | 直接执行 | 两阶段计划确认 | 4.2 |

---

*本文档为一次性缺口快照，各项落地后应将对应内容移入相应 PHASE 文档并在此标记完成。*

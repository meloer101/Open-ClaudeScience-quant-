# QuantBench: 量化金融研究工作台

> 产品愿景文档 v1.0 | 2026-07-01
>
> 对标产品：[Claude Science](https://www.anthropic.com/news/claude-science-ai-workbench) — Anthropic 面向科学家的 AI 研究工作台

---

## 一、一句话定义

**QuantBench 是一个面向量化研究者的 AI 工作台，让每一个策略想法都能变成一个可复现、可审计、可比较的研究实验。**

它不是聊天机器人，不是自动交易系统，不是 notebook —— 它是一个**量化研究闭环引擎**。

---

## 二、Claude Science 做对了什么（我们要学的）

Claude Science 的核心设计决策，及其在量化金融中的对应：

| Claude Science | QuantBench 对应 |
|---|---|
| 协调 Agent + 60+ 领域技能/连接器 | 协调 Agent + 量化研究技能（数据拉取、因子构建、回测、风险分析） |
| 每个输出自带完整溯源（代码 + 环境 + 对话历史） | 每个 research run 自带 artifact 包（代码 + 参数 + 数据版本 + 结果） |
| Reviewer Agent 检查引用和计算错误 | Reviewer Agent 检查未来函数、过拟合、手续费敏感性、样本外表现 |
| 原生渲染蛋白质结构、基因组浏览器、化学式 | 原生渲染 equity curve、因子 IC 热力图、分层回测、风险归因 |
| 在实验室自有基础设施上运行（本地/SSH/HPC） | 在研究者本地运行（本地 Python + 可选远程计算） |
| Session forking：分叉对比两种方案 | Experiment forking：分叉对比两组参数/两个因子变体 |
| Actor-Critic 模式：一个 agent 生成，另一个审查 | 同：策略研究 Agent 生成，风险审查 Agent 审查 |

---

## 三、产品架构（终态）

```
┌─────────────────────────────────────────────────────────────┐
│                        用户界面层                            │
│  Web UI (对话 + 可视化 + Artifact 浏览 + 实验库)              │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                      协调引擎层                              │
│                                                             │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │ Coordinator │  │   Reviewer   │  │  Session Manager  │  │
│  │   Agent     │──│    Agent     │  │  (fork/compare)   │  │
│  └──────┬──────┘  └──────────────┘  └───────────────────┘  │
│         │                                                   │
│  ┌──────▼──────────────────────────────────────────────┐    │
│  │              Skill Registry (技能注册表)              │    │
│  │  数据拉取 │ Universe构建 │ 因子计算 │ 回测执行       │    │
│  │  风险分析 │ 可视化生成   │ 报告撰写 │ 用户自定义技能  │    │
│  └─────────────────────────────────────────────────────┘    │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                       数据与执行层                            │
│                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────────┐   │
│  │  Data Layer  │  │   Sandbox    │  │ Artifact Store  │   │
│  │  DuckDB +    │  │  隔离执行环境  │  │ 实验归档 + 版本  │   │
│  │  Parquet     │  │  (Docker)    │  │  管理           │   │
│  └──────────────┘  └──────────────┘  └─────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## 四、核心概念与对象模型

### 4.1 Research Run（研究运行）

系统的原子单位。每一次从假设到结论的完整执行。

```yaml
research_run:
  id: "run_20260701_001"
  hypothesis: "RSI(14) 反转因子在 BTC/USDT 4h 上有预测力"
  status: completed | failed | promising | rejected

  # 输入
  universe: "top_80_usdt_perpetual"
  data_version: "binance_perp_v3_20260701"
  timeframe: "4h"
  date_range: "2022-01-01 / 2026-06-01"
  train_test_split: "2022-01-01~2025-01-01 / 2025-01-01~2026-06-01"

  # 信号定义
  signal:
    name: "rsi_reversal_14"
    code_hash: "sha256:abc123..."
    parameters: { period: 14, threshold_low: 30, threshold_high: 70 }

  # 持仓规则
  portfolio:
    method: "top_bottom_decile"
    rebalance: "daily"
    max_position: 0.05
    cost_model: { commission_bps: 5, slippage_bps: 5 }

  # 结果
  results:
    sharpe: 1.42
    annual_return: 0.18
    max_drawdown: -0.23
    turnover_annual: 24.3
    ic_mean: 0.031
    ic_ir: 0.45

  # 审查结论
  review:
    future_function_check: pass
    cost_sensitivity: "Sharpe drops to 0.8 at 15bps total cost"
    out_of_sample: "OOS Sharpe 0.6, significant decay"
    regime_dependency: "80% of returns from 2023 bull run"
    verdict: "WEAK — regime dependent, cost sensitive"

  # 溯源
  artifacts:
    - code/signal.py
    - code/backtest.py
    - config/params.yaml
    - results/equity_curve.png
    - results/ic_analysis.png
    - results/factor_returns_by_group.png
    - results/metrics.json
    - report/research_note.md

  parent_run: null  # 或 "run_20260630_003"（如果是从某个实验 fork 出来的）
```

### 4.2 核心对象清单

| 对象 | 说明 | 类比 Claude Science |
|---|---|---|
| **Idea** | 策略假设的文字描述 | 研究问题 |
| **Universe** | 交易标的池定义 + 筛选规则 | 实验样本集 |
| **Dataset** | 带版本的数据集（行情、资金费率、链上等） | 实验数据集 |
| **Signal / Factor** | 因子/信号的代码定义 + 参数 | 实验方法/模型 |
| **Backtest** | 回测配置 + 执行结果 | 实验执行 |
| **Review** | Reviewer Agent 的审查报告 | Reviewer Agent 的审查 |
| **Artifact** | 一次 run 产生的所有文件的归档包 | Auditable artifact |
| **Research Note** | 自动生成的结构化研究笔记 | 论文/manuscript |
| **Experiment Library** | 所有 run 的索引和搜索 | 项目历史 |

---

## 五、核心能力详述

### 5.1 协调 Agent（Coordinator）

用户用自然语言描述研究意图，协调 Agent 将其分解为可执行的研究计划：

```
用户: "测试 WQ Alpha 101 里的 price-volume 因子在 crypto perpetual 上是否有效"

Coordinator 生成计划:
  Step 1: 从 Alpha 101 中筛选 price-volume 类因子（约 15-20 个）
  Step 2: 拉取 top 80 USDT perpetual 的 OHLCV 数据
  Step 3: 逐一计算因子值
  Step 4: 做 IC/Rank IC 分析，初筛
  Step 5: 对 IC > 0.02 的因子做完整回测
  Step 6: Reviewer 审查每个结果
  Step 7: 输出对比报告 + 排序

  预计耗时: ~15 分钟
  需要确认: 数据范围？手续费假设？是否包含已退市合约？

用户: "2023-2026，5bps 双边，包含退市的"
```

### 5.2 Reviewer Agent（审查 Agent）

**这是产品灵魂。** 每个 research run 完成后，Reviewer 自动执行以下检查：

| 检查项 | 说明 | 严重级别 |
|---|---|---|
| **未来函数检测** | 扫描代码，检查是否使用了未来数据（如用收盘价计算当日信号） | 🔴 致命 |
| **样本外表现** | 对比训练期和测试期的 Sharpe/IC，检查衰减程度 | 🔴 致命 |
| **手续费敏感性** | 在 ±50% 手续费范围内重跑，检查 Sharpe 变化 | 🟡 重要 |
| **参数稳定性** | 对核心参数做 ±20% 扰动，检查结果一致性 | 🟡 重要 |
| **Regime 依赖** | 按年/按市场状态切分，检查收益是否集中在某一段 | 🟡 重要 |
| **极端交易依赖** | 剔除 top 5% 盈利交易后，检查策略是否仍盈利 | 🟡 重要 |
| **换手率现实性** | 检查年化换手率是否在合理范围（考虑流动性） | 🟠 一般 |
| **Beta 暴露** | 检查收益中有多少来自市场 beta 而非 alpha | 🟠 一般 |
| **标的池偏差** | 检查是否只在特定标的上有效（如只在 BTC 上赚钱） | 🟠 一般 |
| **数据质量** | 检查缺失值、异常值、时区问题 | 🟠 一般 |

Reviewer 输出格式：

```markdown
## Review Report: rsi_reversal_14

### 🔴 CRITICAL ISSUES
- **Regime Dependency**: 78% of cumulative returns come from 2023-03 to 2023-12.
  Without this period, Sharpe drops from 1.42 to 0.31.

### 🟡 WARNINGS
- **Cost Sensitivity**: At 15bps round-trip cost, Sharpe = 0.81.
  At 20bps, strategy is unprofitable.
- **Parameter Instability**: RSI period 12 gives Sharpe 0.9, period 16 gives 1.8.
  Wide variance suggests overfitting to period=14.

### ✅ PASSED
- No look-ahead bias detected in signal code.
- Factor returns not concentrated in top 5% trades.
- Turnover within reasonable bounds (24x annual).

### VERDICT: ⚠️ WEAK
Recommend: Test on different asset class or timeframe before proceeding.
Next experiments: [1] Try adaptive RSI period [2] Combine with volume filter
```

### 5.3 数据层（Data Layer）

统一的数据抽象，所有数据源通过相同接口访问：

```python
# 统一 schema
class MarketData:
    symbol: str          # "BTC/USDT:USDT"
    exchange: str        # "binance"
    timeframe: str       # "4h"
    timestamp: datetime  # UTC, timezone-aware
    open, high, low, close, volume: float
    
    # 元数据
    data_source: str     # "ccxt_binance_api"
    fetched_at: datetime
    adjusted: bool       # 是否复权
    
class PerpetualData(MarketData):
    funding_rate: float
    open_interest: float
    liquidation_volume: float

class UniverseDefinition:
    name: str
    criteria: str        # "top 80 USDT perpetual by 30d avg volume"
    as_of_date: date
    symbols: list[str]
    include_delisted: bool
    survivorship_bias_note: str
```

**数据验证器（Data Validator）内置检查：**

- 缺失值检测与填充策略记录
- 异常插针检测（价格跳变 > 3σ）
- 时区一致性校验
- 复权方式记录
- 退市合约标记
- 数据版本锁定（每次 run 记录数据快照 hash）

### 5.4 可视化渲染

对话流中原生渲染量化研究常用图表：

| 图表类型 | 用途 |
|---|---|
| Equity Curve | 策略净值曲线，含 benchmark 对比 |
| Drawdown Chart | 回撤曲线 |
| Factor IC Heatmap | 因子 IC 按时间/标的的热力图 |
| Decile Return Bar | 因子分层（十分位）收益柱状图 |
| Turnover Chart | 换手率时序图 |
| Cost Sensitivity Plot | 手续费 vs Sharpe 的敏感性曲线 |
| Parameter Heatmap | 参数网格搜索热力图 |
| Regime Decomposition | 按市场状态分解的收益归因 |
| Correlation Matrix | 因子/策略间相关性矩阵 |
| Risk Attribution | 风险因子暴露分解 |

### 5.5 实验库（Experiment Library）

所有 research run 的结构化索引，支持：

- **搜索**：按因子类型、资产、时间范围、Sharpe 范围、状态筛选
- **对比**：选择多个 run 横向对比所有指标
- **谱系追踪**：一个想法经过几次变体，每次改了什么，结果如何
- **知识沉淀**：系统知道 "momentum 类因子在 crypto 4h 上 IC 一般在 0.01-0.03"

```
实验库查询示例：

用户: "过去所有 momentum 类因子的结果汇总"

系统返回:
| Run ID | Factor | Universe | OOS Sharpe | Cost Sens | Verdict |
|--------|--------|----------|------------|-----------|---------|
| run_042 | mom_12h | top80_perp | 0.6 | fragile | WEAK |
| run_043 | mom_24h | top80_perp | 0.8 | ok | PROMISING |
| run_051 | mom_24h_vol | top80_perp | 1.1 | robust | STRONG |
| run_067 | mom_adaptive | btc_only | 1.4 | fragile | WEAK |

结论: 纯动量因子 IC 衰减快，加成交量过滤后显著改善。
      BTC-only 结果不可信（单标的偏差）。
```

### 5.6 Session Forking（实验分叉）

在任意节点分叉，对比不同路径：

```
用户: "当前因子用 RSI(14)，fork 一个用自适应 RSI"

系统:
  ├─ [original] RSI(14) → 继续当前分析
  └─ [fork-001] Adaptive RSI → 新的 run，继承数据和 universe 配置
                                只改变信号定义

两个分支独立运行，结果自动生成对比表。
```

---

## 六、技能注册表（Skill Registry）

### 内置技能（v1.0 目标）

| 技能 | 输入 | 输出 |
|---|---|---|
| `fetch_ohlcv` | symbol, timeframe, date_range | Parquet 文件 |
| `fetch_funding_rate` | symbol, date_range | Parquet 文件 |
| `fetch_open_interest` | symbol, date_range | Parquet 文件 |
| `build_universe` | criteria, as_of_date | UniverseDefinition |
| `compute_factor` | factor_code, data | 因子值 DataFrame |
| `run_backtest` | signal, portfolio_config | BacktestResult |
| `analyze_ic` | factor_values, forward_returns | IC 分析报告 |
| `analyze_risk` | portfolio_returns, benchmark | 风险归因报告 |
| `plot_equity_curve` | returns_series | 图表 |
| `plot_ic_heatmap` | ic_series | 图表 |
| `generate_research_note` | run_result, review | Markdown 报告 |
| `validate_data` | dataset | 数据质量报告 |
| `check_lookahead` | code_string | 未来函数检测结果 |
| `cost_sensitivity` | backtest_result, cost_range | 敏感性分析 |
| `regime_analysis` | returns, market_data | Regime 分解 |

### 用户自定义技能

用户可以将任何 pipeline 保存为可复用技能：

```python
@quantbench.skill("my_momentum_factor")
def compute_momentum(data, lookback=24, vol_filter=True):
    """我的动量因子：带成交量过滤的价格动量"""
    # ... 用户代码 ...
    return factor_values
```

保存后，未来所有 session 自动可用。

---

## 七、迭代计划

> **执行顺序调整（Phase 1 完成后）：** 原计划 Phase 2（Reviewer Agent）顺延，Phase UI（原 Phase 4 可视化与 UI 的核心部分）提前执行，详见 [PHASE_UI.md](PHASE_UI.md)。理由：Phase 0/1 产出的 artifact 已经过多轮 bug 修复、有警告护栏，值得先让它们在真正的 Web 工作台里被看见，而不是继续堆在终端和文件夹里；这个调整不影响"先正确性、后体验"的整体原则——Reviewer Agent 仍是下一个要做的审查能力。
>
> **Phase 2 完成（详细计划见 [PHASE2.md](PHASE2.md)）：** Reviewer 现在挂在 Coordinator 的 backtest 成功路径上自动运行，不是模型可选调用的工具，输出确定性、可测试的 verdict（STRONG/PROMISING/WEAK/REJECTED）。落地后用真实美股数据（而不只是合成 fixture）做了一轮校准，改掉了两处会让 Reviewer 结论不可信的问题：样本外符号翻转检查在训练期 Sharpe 偏低时会漏判；极端交易依赖检查原先用"剔除最赚钱的 5% 交易日后复利重算净值"，在多年期日频序列上无论策略好坏都会衰减到接近 -100%（纯数学的复利假象，不是真实信号），已改为不复利的"贡献占比"口径。

### Phase 0: 骨架 (Week 1)
**目标：一个能跑通的最小闭环**

- [ ] 项目结构搭建
- [ ] LiteLLM + DeepSeek 集成
- [ ] 简单 tool use 循环（Coordinator Agent）
- [ ] 一个 skill：`fetch_ohlcv`（通过 CCXT 拉 Binance 数据）
- [ ] 一个 skill：`run_backtest`（简单的向量化回测）
- [ ] Artifact 存储（每次 run 保存到本地目录）
- [ ] CLI 交互界面

**验收标准：** 输入 "测试 RSI 因子在 BTC 4h 上的表现"，系统自动拉数据、跑回测、输出结果和代码文件。

### Phase 1: 数据层 (Week 2-3)
**目标：可靠的数据基础**

- [ ] DuckDB + Parquet 本地数据仓库
- [ ] 数据版本管理（每次 run 记录数据 hash）
- [ ] Universe 构建（支持 top N by volume）
- [ ] 退市合约处理
- [ ] 数据验证器（缺失值、异常值、时区）
- [ ] 多数据源：OHLCV + funding rate + open interest

**验收标准：** 能构建 "top 80 USDT perpetual" universe，含退市合约，数据完整率 > 99%。

### Phase 2: Reviewer Agent (Week 4-5)
**目标：自动化研究审查**

- [x] 未来函数检测（代码静态分析）
- [x] 样本外自动切分与对比
- [x] 手续费敏感性分析
- [x] 参数稳定性检查
- [x] Regime 依赖分析
- [x] 审查报告自动生成

**验收标准：** 给一个故意包含未来函数的因子，Reviewer 能检测到并报告。给一个过拟合的因子，能指出参数不稳定。

### Phase 3: 实验管理 (Week 6-7)
**目标：研究记忆和知识积累**

- [x] Experiment Library（所有 run 的结构化索引）
- [x] Run 对比功能
- [x] 谱系追踪（parent/child runs）
- [x] Session forking
- [x] Research Note 自动生成（结构化 Markdown，fork run 含谱系区块）
- [x] 失败原因记录和知识沉淀

**当前状态：** CLI/API/Web 已支持实验库检索、对比、谱系和 fork；`library.summarize()` 会产出按 `factor_family × asset_class` 的确定性聚合表，Coordinator 的历史实验问答模式会先注入该表，再让模型只做解读。

**验收标准：** 跑完 20 个因子后，能问 "哪些类型的因子在 crypto 上最有希望"，系统基于实验历史给出有数据支撑的回答。

### Phase 4: 可视化与 UI (Week 8-10)
**目标：从 CLI 到 Web**

- [x] Web UI（对话 + 可视化面板）
- [x] 原生图表渲染（equity curve、drawdown、turnover、decile return、cost sensitivity、parameter perturbation、regime decomposition、symbol concentration、returns correlation）
- [x] Artifact 浏览器（查看历史 run 的所有文件，含 Parquet 预览）
- [x] 实验库可视化（表格 + 筛选 + 对比）
- [x] 交互式图表（hover 显示数值、点击 fork 联动谱系）

**当前状态（详细计划见 [PHASE4.md](PHASE4.md)）：** ChartsPanel 消费 `backtest_result.json`/`review_report.json` 两个已有的确定性 JSON artifact，渲染成一套零依赖手写 SVG 图表（不引入图表库），前端不做任何统计计算。按 run 有什么数据就渲染什么区块，没有的维度（比如单标的场景的 decile/symbol concentration）直接省略而不是画空图。Compare 视图新增 Returns Correlation 矩阵（`library/compare.py` 新增 `compute_returns_correlation`，对齐时间戳、样本不足显式返回 null）。落地过程中发现并修复了一个历史遗留 bug：截面回测结果曾经存成 `cross_sectional_backtest_result.json`，和单标的路径的 `backtest_result.json` 不一致，导致新图表和相关性计算对截面 run 完全读不到数据——已统一成单一文件名，并加了回归测试锁定。

**明确保留的缺口（详见 PHASE4.md 第四节，不是遗忘）：** 真正的按标的展开的 Factor IC Heatmap（QuantBench 未持久化逐标的 IC，v1 用 decile-by-time 热力图诚实替代）；多因子 Risk Attribution（没有因子模型数据源，只有单一 benchmark 的 beta exposure）。两者留给 Phase 5 多资产工作把数据源建起来后再做。

**验收标准：** 完整的 Web 体验，用户不需要看终端。

### Phase 5: 多资产与高级功能 (Week 11-14)
**目标：扩展到更多市场和更复杂的研究**

- [ ] 多 agent 协作（研究 agent + 审查 agent 并行）
- [ ] 自定义 skill 系统
- [ ] 组合优化
- [x] 多资产支持（crypto 截面补全：当前成交量 Top-N USDT 永续合约 universe、BTC/USDT benchmark 路由、funding rate 未建模警告）
- [ ] 期货支持（推迟：需要连续合约/展期规则，详见 [PHASE5.md](PHASE5.md) 第一节和第五节）
- [ ] Paper trading 集成
- [ ] 远程计算支持（SSH / Modal）

**当前状态（详细计划见 [PHASE5.md](PHASE5.md)）：** Phase 5 先只补齐 crypto 截面研究，而不是一次性吞下期货、多 agent、组合优化等所有高级能力。系统现在可以构建当前按 24h 成交量排名的 Top-N USDT 永续合约 universe，明确标注这不是 point-in-time universe；截面 Reviewer 的 beta exposure 会按资产类别路由，crypto 使用 BTC/USDT，equity 仍使用 SPY；crypto 永续合约 run 会自动写入 funding rate carry cost 未建模的警告。期货支持没有打勾，后续需要先单独设计 continuous contract 和 roll 规则。

### Phase 6: 生产化 (Week 15+)
- [ ] Live signal monitoring
- [ ] 策略衰减预警
- [ ] 团队协作
- [ ] 权限管理

---

## 八、不做的事（产品边界）

明确排除以下内容，避免范围蔓延：

| 不做 | 原因 |
|---|---|
| 自动交易执行 | 早期产品不应该碰实盘下单，风险太大 |
| 多用户 SaaS | 先做单用户本地工具，验证价值 |
| 高频策略 | 需要极低延迟，不适合 AI workbench 场景 |
| 基本面分析 | 先聚焦量价因子，范围可控 |
| 华丽 UI | 研究者要的是结果可信，不是界面好看 |
| 多 LLM 集成 | 先用一个模型跑通，后面再切换 |

---

## 九、成功标准（终态验收）

当以下场景能流畅完成时，产品达到 v1.0：

> **场景：** 用户说 "我想找一个在 crypto perpetual 市场上夏普大于 1.5、手续费稳健、样本外不衰减的量价因子"
>
> **系统：**
> 1. 自动从 Alpha 101 + 自定义因子库中筛选候选因子
> 2. 构建包含退市合约的 universe
> 3. 逐一计算、回测、审查
> 4. 淘汰不通过审查的因子
> 5. 对存活因子做多因子组合优化
> 6. 生成完整 research note，含所有 artifact
> 7. 记录到实验库，可随时复现
> 8. 推荐下一轮实验方向
>
> **耗时：** < 30 分钟（含数据拉取）
>
> **关键：** 结果可信。不是因为 AI 说它好就好，而是因为每一步都有代码、有数据、有审查、有溯源。

---

## 十、技术选型（当前决策）

| 组件 | 选型 | 理由 |
|---|---|---|
| LLM 接入 | LiteLLM | 统一接口，方便切换模型 |
| 底层模型 | DeepSeek V3 (MVP) → Claude/GPT (审查场景) | 成本控制，代码能力够用 |
| 数据存储 | DuckDB + Parquet | 本地高性能分析，无需数据库服务 |
| 数据获取 | CCXT | 统一加密货币交易所 API |
| 代码执行 | subprocess (MVP) → Docker sandbox | 先简单后安全 |
| 后端 | Python (FastAPI) | 量化生态天然适配 |
| 前端 | CLI (MVP) → Streamlit → React | 逐步升级 |
| Artifact 存储 | 本地文件系统 + JSON 索引 | 简单可靠 |

---

## 十一、核心设计准则：模型写什么，代码写什么

这条准则贯穿整个项目，来自 Phase 1 完成后的一次复盘，必须一直守住：

**模型（LLM）负责需要判断力和创意的部分；代码负责必须绝对正确、可审计、不能有半点漂移的部分。**

对应到 Claude Science 的设计：60+ 个 curated skills/connectors（UniProt、PDB、BioNeMo 工具包等）是预先配置好的，不是模型现场写出来的；但把这些工具串起来解决具体研究问题的分析逻辑，是模型自己写的，用户还可以把成功的流程存成新的可复用 skill。

对应到 QuantBench：

| 谁负责 | 内容 | 原因 |
|---|---|---|
| **模型写** | `compute(df) -> pd.Series` 因子/信号的具体逻辑 | 这是"研究创意"——用什么指标、要不要加成交量过滤、参数怎么定，需要判断力，每次可能不一样，理应现场生成 |
| **代码写（写死、有测试）** | 数据拉取（`fetch_ohlcv`）、universe 构建、回测数学（对齐逻辑、Sharpe/IC/年化换算）、数据质量校验、画图 | 这些必须绝对正确且每次结果一致，不能有漂移；一旦让模型每次重新生成这部分逻辑，相当于放弃了"可测试、可审计"这个核心承诺 |

**这不是随便定的边界，是有教训的**：这一路上抓出来的几个致命 bug（回测时序错位、年化换算把周末算成交易日、截面复现静默出错）全部出在"代码写"这一侧——恰恰因为这一侧本该是最可靠的部分，一旦出错就是系统性地影响所有 run，而且不容易被发现。如果反过来让模型每次自己重写回测引擎，这类 bug 只会更多、更难抓，因为没有一份稳定实现可以写回归测试锁定。

**后续任何新增功能，先问一句：这段逻辑属于"研究创意"还是"必须绝对正确的基础设施"？** 前者放进 system prompt 让模型写 `compute()` 风格的代码；后者写成经过测试的 Python 工具函数，模型只调用、不生成。Phase 2 的 Reviewer Agent 设计时要特别注意这条——审查逻辑本身（怎么检测未来函数、怎么算手续费敏感性）应该是"代码写"的部分，Reviewer Agent 只是调用这些检查工具并解读结果，不应该让模型自己现场发明"怎么判断有没有未来函数"这套逻辑。

---

*本文档随项目演进持续更新。每个 Phase 完成后回顾并修订。*

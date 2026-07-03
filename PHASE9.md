# Phase 9 详细实施计划：多因子组合优化——把"优化"关进"回测 + 审查 + 溯源"的笼子里

> 对应 [VISION.md](VISION.md) 第七节 Phase 5 未完成项"组合优化"，以及第九节 v1.0 验收场景的第 5 步"对存活因子做多因子组合优化"。
> 前置条件：[PHASE0.md](PHASE0.md)～[PHASE8.md](PHASE8.md) 均已完成并合并到 `main`。特别依赖 Phase 8 的 `screen_factors`（产出一批各自带独立收益序列的子 run）与独立 Critic Agent，以及 [quantbench/library/compare.py](quantbench/library/compare.py) 里已有的"读取子 run 收益序列 + 按时间戳对齐 + 算相关性"逻辑。
> 目标：在 `screen_factors` / Factor Library 产出多个候选因子之后，把它们组合成一个多因子组合。**但这件事在本项目里的正确做法，和一般"跑个 Markowitz 最大化夏普"完全不同**——本计划先把金融上为什么这么做讲清楚，再给出工程实现。

---

## 一、金融论证：为什么"最大化夏普的均值方差优化"是这个项目最不该直接暴露给用户的东西

组合优化是本项目里金融陷阱最密集的一步。如果只是接一个 `scipy.optimize` 最大化样本夏普，会同时违反这个项目从 Phase 2 起就在坚持的两条准则（[VISION.md](VISION.md) 第十一节"模型写什么、代码写什么"，以及 Reviewer/Critic 存在的全部理由："结果可信不是因为算出来好看，而是因为每一步都有审查"）。要点分四层：

**第一层：我们组合的是"策略"，不是"资产"。** 每个候选因子的输入是它自己的多空收益序列（`long_short_returns`，已经是 dollar-neutral 的价差），不是某支股票的价格收益。所以这是一个"strategy-of-strategies / 因子配置"问题，不是经典的资产配置。含义：这里的"权重"= 分给每个因子多少风险预算，而不是买多少股票；"权重和为 1、不做空"这些约束的金融含义也随之改变。

**第二层：均值方差优化（MVO）是"误差最大化器"。** Markowitz 用样本均值 + 样本协方差最大化夏普，是过拟合的教科书案例（Michaud 1989 直接称之为 "error maximization"）：输入里最难估计的就是期望收益，而 MVO 恰恰对期望收益的估计误差最敏感，输入动一点点、权重就剧烈摆动并高度集中/加杠杆。DeMiguel、Garlappi & Uppal（2009，*Optimal Versus Naive Diversification*）的著名结论是：**样本外，1/N 等权常常打败一大票"最优"组合**，因为估计误差吞掉了优化本该带来的好处。这就是本步骤的核心谦卑点。

**第三层：能通过审查的方法，是那些"尽量少估计、尤其不估计期望收益"的方法。** 按稳健性从高到低：
- **等权 1/N**：诚实的基线，必须永远算出来并摆在最显眼处。
- **逆波动率 / 风险平价（ERC）**：按波动率倒数（或等风险贡献）配权，只用协方差、完全不碰期望收益 → 最稳健。呼应 Robert Carver 的模块化风险框架（[quant-research skill] 引用）。
- **最小方差**：用完整协方差、仍不碰期望收益，稳健但会集中在低波动因子上。
- **HRP（Hierarchical Risk Parity，López de Prado 2016）**：对相关性矩阵聚类后递归二分配权，避开对病态协方差矩阵求逆。现代稳健法的代表，正好契合本项目已经引用的 López de Prado 方法论（[quant-research skill] 的 DSR/PBO/CPCV）。
- **最大夏普（切点组合）**：同时用均值和协方差 → 最容易过拟合。**要实现，但要作为"警示性对照"呈现，而不是默认推荐**，且对输入做收缩、对权重加约束防止荒唐杠杆。

**第四层：协方差本身要估得稳。** K 个因子、T 个观测，样本协方差在 T 不远大于 K 时是病态的。标准修法是 Ledoit-Wolf 收缩到结构化目标。这里 K 很小（≤20），没有 500 资产那么灾难，但收缩仍是负责任的默认。

**结论（本计划的架构基石）：** 组合优化的产出不是"一份权重 + 一个好看的样本内夏普"。它必须：
1. **默认走稳健方法**（风险平价 / HRP），把最大夏普作为对照而非推荐；
2. **同时给出所有方法的权重 + 样本内/样本外夏普对照表**，让用户亲眼看到"最大夏普样本内赢、样本外常输给 1/N"——这本身就是最好的过拟合教育；
3. **组合后的收益序列，必须再过一遍确定性 Reviewer + 独立 Critic**，和任何单因子 run 一样拿 verdict、进实验库、可溯源、可 fork。否则就是"AI 说好就好"，正是这个项目要消灭的东西。

第 3 点是让"组合优化"真正属于 *这个* 项目、而不是一个通用金融计算器的关键。

---

## 二、范围决策（先把边界钉死，避免做成大杂烩）

**D1 — 输入是什么：一组 run_id。** 不绑定 `screen_factors`，而是接受任意 run_id 列表（截面因子子 run、单标的策略 run 都行，只要有 `backtest_result.json` 收益序列）。`screen_factors` 的父 run 只是这批 ID 的一个方便来源。这样能跨筛选会话、跨实验库组合，和现有 `compare`（对任意 run_id 列表通用）一致。**直接复用 [compare.py](quantbench/library/compare.py) 的 `_read_returns_series`**（已同时处理 `returns` 与 `long_short_returns` 两种 key）。

**D1 附带 — 兼容性闸门（这是个金融正确性特性，不是工程细节）：** 只允许组合 **同一 asset_class、且时间戳重叠观测数 ≥ 阈值** 的 run。把一个 equity 因子的 2020–2024 日线序列和一个 crypto 因子的 4h 序列拼在一起做协方差，是没有金融意义的。重叠不足 / asset_class 混杂 → 直接报错或高声警告，绝不静默算一个数。阈值复用 `compare.py` 已有的 `MIN_CORRELATION_OBSERVATIONS = 30` 哲学。

**D2 — 数学是代码，编排是模型。** 优化本身没有"让模型写代码"的空间（不像因子 `compute()`），所以核心是确定性模块。调用方式三管齐下，但数学只有一份：
- **LLM 工具** `optimize_portfolio(run_ids, method, ...)`：让 Coordinator 能在 `screen_factors` 之后链式调用（"筛这 5 个因子，然后对存活的建一个优化组合"——正是 VISION §9 第 5 步）。模型只负责编排 + 解释，绝不算数。
- **CLI** `portfolio optimize <run_id...>`：脚本化 / 直接使用，对齐现有 `compare`、`factor` 的 CLI 入口。
- **确定性核心模块** `quantbench/portfolio/`：以上两者都只是薄壳。

**D3 — 组合是一个一等公民 Run。** `optimize_portfolio` 创建一个子 run（`parent_run_id` = 传入的 screen_factors 父 run，或第一个输入 run），写标准 artifacts，跑组合专属 Reviewer + 独立 Critic，`finalize(parent_run_id=...)`。于是它自动继承实验库、lineage、compare、ChartsPanel、Critic 整套信任/溯源栈。**关键工程约束：组合后的收益序列要用和 `backtest_result.json` 完全相同的 schema 落盘**，这样 `_read_returns_series` / compare / 相关性矩阵 / 前端 ChartsPanel 不改一行就能读它。

**D4 — 组合专属 Reviewer（本步骤的智力核心，见第四节）。** 现有 `run_review` 的签名重度依赖 `compute(df)` 代码和数据面板的回调，组合没有 `compute()`。所以不复用 `run_review` 整体，而是复用它 **可迁移的子检查**、新增组合专属检查，最终仍产出同一个 `ReviewReport` dataclass，让 `determine_verdict`、markdown、manifest、Critic、前端全部零改动继续工作。

**D5 — 诚实机器（见第五节）。** 训练/测试切分拟合权重、多样化比率、方法对照表、多重检验警告——这些是让组合优化"属于本项目"的部分。

---

## 三、具体改动

### 3.1 新增包 `quantbench/portfolio/`（与 `review/`、`engine/` 平级）

**`quantbench/portfolio/optimize.py`** — 纯函数，输入一个收益 DataFrame（列 = run_id，行 index = 时间戳），无 I/O：

```python
@dataclass(frozen=True)
class OptimizationResult:
    method: str
    weights: dict[str, float]          # run_id -> weight，和为 1
    diagnostics: dict[str, Any]        # 协方差条件数、是否触约束、迭代收敛等

def ledoit_wolf_covariance(returns: pd.DataFrame) -> tuple[np.ndarray, float]:
    """闭式 Ledoit-Wolf 收缩协方差 + 收缩强度。自己实现（~30 行），不引入 sklearn，
    保持依赖不变（当前只有 scipy/numpy）。"""

def optimize(returns: pd.DataFrame, method: str, *,
             max_weight: float = PORTFOLIO_MAX_WEIGHT,
             cov: np.ndarray | None = None) -> OptimizationResult: ...
```

实现的方法（`method` 取值）：
1. `equal_weight` — 1/N，永远计算，作为锚。
2. `inverse_variance` — 1/σ 归一化。不碰均值、不求逆。
3. `min_variance` — 二次规划（`scipy.optimize.minimize`, SLSQP），完整（收缩后）协方差，不碰均值。
4. `risk_parity` — 等风险贡献（ERC），迭代解，完整协方差，不碰均值。
5. `max_sharpe` — 切点组合，同时用均值和协方差，**警示性对照**；对均值和协方差都收缩，权重加 `0 ≤ w ≤ max_weight` 约束防止荒唐杠杆/集中。
6. `hrp` — Hierarchical Risk Parity：相关性 → 距离矩阵 → 层次聚类（scipy.cluster.hierarchy）→ quasi-diagonalization → 递归二分配权。

约束（QP / 切点）：权重和为 1，long-only（`0 ≤ w ≤ max_weight`）。退化情形（单因子、协方差奇异、优化不收敛）必须显式处理并在 `diagnostics` 里标注，绝不返回 NaN 权重。

**`quantbench/portfolio/combine.py`** — 权重 + 各 run 收益序列 → 组合收益：

```python
@dataclass(frozen=True)
class CombinedPortfolio:
    returns: pd.Series
    equity_curve: pd.Series
    drawdown: pd.Series
    turnover: pd.Series          # 来自再平衡时的权重变动
    metrics: dict[str, float]    # 复用 engine/metrics.py：sharpe/annual_return/max_drawdown/turnover_annual
    diversification_ratio: float # 加权平均波动 / 组合波动，量化"组合到底有没有帮上忙"

def combine(returns: pd.DataFrame, weights: dict[str, float], cost_bps: float) -> CombinedPortfolio: ...

def to_json_dict(combined: CombinedPortfolio) -> dict:
    """输出与 CrossSectionalBacktestResult.to_json_dict / BacktestResult.to_json_dict
    完全一致的 schema（series.timestamp + series.returns + equity_curve + drawdown +
    turnover），使 backtest_result.json 的读取方/ChartsPanel/compare/相关性零改动可用。"""
```

指标全部走 [engine/metrics.py](quantbench/engine/metrics.py)（`annualized_sharpe`、`annualized_return`、`compute_drawdown`、`periods_per_year_from_timestamps`），保证和单因子回测同口径（尤其是按实际 bar 密度推断年化因子那套，避免 crypto/equity 混口径）。

**`quantbench/portfolio/review.py`** — 组合专属审查，产出标准 `ReviewReport`（详见第四节）。

**`quantbench/portfolio/report.py`**（或并入 [skills/report.py](quantbench/skills/report.py)）— `build_portfolio_research_note(...)`：新增 `## 组合优化` 段落，含方法对照表（每方法：权重 + 样本内夏普 + 样本外夏普）、多样化比率、相关性矩阵摘要、被选中权重，和现有 `## Reviewer 审查报告` / `## Critic Agent 独立复核` 并列。

### 3.2 `quantbench/agent/coordinator.py`

- `_build_registry` 新增第 6 个工具 `optimize_portfolio(run_ids, method=None, train_test_split=None, cost_bps=None, max_weight=None)`：
  1. 读取每个 run_id 的收益序列（复用 compare 的读取逻辑，抽到公共位置）；跑兼容性闸门（asset_class 一致、重叠观测 ≥ 阈值），不通过则返回 `{"error": ...}`。
  2. `run_store.create_run(...)` 建子 run。
  3. 全样本 + 各方法算权重（`optimize.py`），训练/测试切分算被选方法的样本内/样本外（`combine.py`）。
  4. 组合收益按 `backtest_result.json` schema 落盘；权重落 `portfolio_weights.json`；方法对照 + 诊断落 `portfolio_summary.json`。
  5. 跑组合专属 Reviewer（`portfolio/review.py`）→ `review_report.json`；跑独立 Critic → `critic_report.json`。
  6. `build_portfolio_research_note` → `research_note.md`；画组合 equity/drawdown 图（复用 [skills/plot.py](quantbench/skills/plot.py)）。
  7. `finalize(parent_run_id=父 run, review=..., critic=..., metrics=组合指标)`。
  8. 工具返回值：被选方法、权重、组合夏普、多样化比率、样本外衰减、每个方法一行的对照、verdict、critic 是否认同——够模型直接写最终答复，不需要二次调用。
- Critic 接入：现有 `_run_critic_for_context` 的门是 `if ctx.review_report is None or not ctx.signal_code`。组合没有 `signal_code`——把 `ctx.signal_code` 设为**权重+方法的可读 JSON 描述**（"这个组合是什么"），让 Critic 有据可依；`_critic_context` 里加入组合上下文（方法、成分 run_id、多样化比率、样本外衰减）。Critic 复核的是"组合结论是否夸大"，语义与单因子一致。
- `ctx.screened` 之后新增 `ctx.optimized` 之类的幂等标记，防止模型对同一批因子反复优化刷 run。

### 3.3 `quantbench/config.py`

```python
PORTFOLIO_DEFAULT_METHOD = "risk_parity"   # 默认稳健法，不是 max_sharpe
PORTFOLIO_TRAIN_TEST_SPLIT = 0.7           # 按时间前 70% 拟合权重、后 30% 检验
PORTFOLIO_MAX_WEIGHT = 0.60                # 单因子权重上限，防止"组合"退化成单押
PORTFOLIO_MIN_FACTORS = 2
PORTFOLIO_MAX_FACTORS = 20
PORTFOLIO_MIN_OVERLAP_OBS = 60             # 组合拟合比单点相关性更需要样本，取严于 compare 的 30
```

### 3.4 `quantbench/cli.py`

新增 `portfolio` 子命令：`portfolio optimize <run_id...> [--method=] [--split=] [--cost-bps=] [--max-weight=] [--json-output]`，走 `Coordinator` 的同一条组合逻辑（抽成 `Coordinator.optimize_portfolio(...)` 供 CLI 和工具共用，模式同 `run_from_factor`）。表格输出复用 `_echo_*` 风格。

### 3.5 `quantbench/agent/prompts.py`

`SYSTEM_PROMPT` 新增第 6 个工具说明 `optimize_portfolio`，并在 workflow 里写明：**只在用户明确要"组合/配权/portfolio/多因子组合"时调用**；调用前通常已有一批 run_id（来自本会话的 `screen_factors` 或用户指定）；结果是 FINAL，不要再去重跑单因子。措辞强调：报告里必须如实转述"最大夏普是警示性对照、默认推荐稳健法"以及样本外衰减，不得只报样本内好看的数。呼应现有"你的最终陈述会被独立 Critic 核对"。

### 3.6 API / 前端（最小但真实）

- 组合子 run 因为写了标准 artifacts，已自动出现在 `/api/runs`、`/api/library`、`/api/runs/{id}/lineage`、ChartsPanel（组合 equity 曲线）、compare、相关性矩阵里——**零后端改动即可用**。
- 新增只读端点 `/api/runs/{id}/portfolio` 读 `portfolio_summary.json`（方法对照表 + 权重 + 多样化/样本外诊断）；schema 加 `PortfolioSummarySchema`。
- [web/src/types.ts](web/src/types.ts) 加 `PortfolioSummary` 类型；[web/src/components/LiveProgress.tsx](web/src/components/LiveProgress.tsx) 的 `TOOL_LABEL` 加 `optimize_portfolio: "组合优化"`。
- 前端展示：一个组合摘要卡片/tab，渲染方法对照表（高亮"被选中的稳健方法"与"max_sharpe 对照"，样本外列用颜色标出衰减）+ 权重条形。**刻意不做**复杂交互式有效前沿图（见第六节 scope 边界）。

---

## 四、组合专属 Reviewer（本步骤的智力核心：哪些检查能迁移、哪些要新造、哪些不适用）

组合后的收益序列没有 `compute(df)` 代码、没有 factor_panel，所以不能整体套 `run_review`。逐项判断（这张表就是本节的价值）：

| 现有检查 | 对组合是否适用 | 处理 |
|---|---|---|
| `lookahead`（AST 扫代码） | 不适用 | 组合无 compute() 代码。成分因子各自已过此检查；组合层跳过。 |
| `out_of_sample` | **高度相关但要改造** | 现有版本是"同一 compute() 在 train/test 数据上重跑"。组合层要**组合专属**：在 train 上拟合权重、把**固定权重**套到 test，比较样本内/外夏普。这是最重要的检查，必须新写 `portfolio_out_of_sample`。 |
| `cost_sensitivity` | 部分相关 | 组合有再平衡换手成本，但我们只有各因子的**净收益序列**、没有底层持仓，无法精确建模组合增量成本。v1 只按权重变动的再平衡换手估一个粗成本并做 ×1.5/×2 敏感性；不足处高声说明。 |
| `parameter_stability` | **概念直接迁移** | 组合的"参数"就是权重向量。对权重做 ±20% 扰动、看夏普 spread——和现有参数扰动检查同philosophy。新写 `weight_stability`。 |
| `regime`（年度贡献集中度） | **直接复用** | `yearly_return_contribution` 只吃一条收益序列，直接作用在组合收益上。 |
| `tail_dependence` | **直接复用** | `best_days_contribution_share` 同上。 |
| `turnover` | 部分 | 来自权重变动的再平衡换手（+ 可选叠加成分因子换手的加权）。 |
| `beta_exposure` | **直接复用** | `compute_beta` 吃组合收益 + benchmark；benchmark 按 asset_class 路由（复用 `_benchmark_symbol_for_asset`，equity→SPY，crypto→BTC/USDT），只 fetch 一次。 |
| `symbol_concentration` | 不适用 → **替换** | 组合没有 factor_panel。换成 `factor_concentration`：组合的风险/收益是否被单个因子（权重 × 波动贡献）主导。若单因子风险贡献 > 阈值 → warning。这是"组合其实没分散"的直接信号。 |
| （新） `correlation_health` / 多样化 | **新增** | 若成分因子两两相关性都很高（多样化比率 ≈ 1），"优化"是表演——组合相对最好的单因子几乎无增益。此时 warning，并在结论里直说。 |
| （新） `improvement_over_best_single` | **新增** | 组合夏普是否显著超过**最好的单个成分因子**。若没有，"组合"没有加价值，应如实标注（避免用户误以为优化带来了 alpha）。 |

`portfolio/review.py` 把上述可迁移子检查（`regime`/`tail_dependence`/`beta_exposure`，从 `quantbench.review` 直接 import 复用）+ 新检查（`portfolio_out_of_sample`/`weight_stability`/`factor_concentration`/`correlation_health`/`improvement_over_best_single`）组装成 `list[ReviewFinding]`，调用现有 `determine_verdict` 得 verdict/reason，返回标准 `ReviewReport`。于是 markdown、manifest、Critic、前端 verdict badge、实验库 verdict 过滤全部零改动继续工作。

---

## 五、诚实机器（让组合优化"属于本项目"的部分）

1. **训练/测试切分拟合权重**：默认按时间前 70% 拟合、后 30% 检验被选方法。绝不用全样本拟合权重再报全样本夏普（那是循环论证——权重就是为了最大化那个数选出来的）。
2. **方法对照表**：所有 6 种方法的权重 + 样本内夏普 + 样本外夏普并排。典型现象是 max_sharpe 样本内最高、样本外输给 1/N——把这个现象摆在用户面前，本身就是最好的过拟合教育。
3. **多样化比率**（加权平均波动 / 组合波动）：量化组合到底有没有降低风险。≈ 1 → 没帮上忙。
4. **多重检验警告**：被推荐方法是从 N 个候选里挑出来的，其样本内夏普天然向上有偏（选择偏差 / 多重检验）。至少加一条明确警告；可选实现闭式 **Probabilistic Sharpe Ratio (PSR)** 给一个"这个夏普显著为正的概率"作为轻量严谨性补充（对齐 [quant-research skill] 的 López de Prado 方法论，为将来接 Deflated Sharpe / PBO 留口）。
5. **高声警告触发条件**（进 `ctx.warnings`，走现有 "⚠️ DO NOT TRUST" 机制）：样本外夏普较样本内大幅衰减；任一因子权重触上限（组合退化成单押）；所有两两相关性偏高（多样化 ≈ 0）；重叠观测不足；asset_class 混杂；组合夏普未显著超过最好单因子。
6. **独立 Critic 复核**：和任何 run 一样，Critic 只看确定性证据（组合 Reviewer 结果 + 组合指标 + Coordinator 最终陈述），核对是否夸大、给独立 verdict。

---

## 六、明确不做的事（scope 边界）

- **不做**组合层交易成本的微观结构建模（我们没有各因子的逐笔持仓，只有净收益序列）——只做权重变动的再平衡换手估计，并说明局限。
- **不做**完整 Deflated Sharpe Ratio / PBO / CPCV（本 phase 的严谨性 = 诚实 train/test + 多重检验警告 + 可选 PSR；DSR/PBO 作为将来扩展，已在 [quant-research skill] 里有方法论）。
- **不做**滚动/walk-forward 动态再配权（单次 train 拟合 → test 上固定权重；rolling 是后续扩展）。
- **不做**杠杆/做空（long-only 有界权重）。
- **不做**复杂交互式有效前沿可视化（前端只做方法对照表 + 权重条 + 样本外诊断的静态展示）。

---

## 七、测试 `tests/test_phase9_portfolio.py`

1. **优化数学**：已知协方差 → 逆波动率/最小方差权重对上闭式解；等权平凡；权重和为 1 且满足 `0≤w≤max_weight`；单因子退化优雅处理；奇异/不收敛在 `diagnostics` 里标注而非返回 NaN。
2. **HRP**：构造已知聚类结构的相关性矩阵，验证配权落在预期簇上、和为 1。
3. **combine**：两条反相关合成序列 → 组合波动 < 各自波动、多样化比率 > 1；指标算对；`to_json_dict` 输出能被 `compare._read_returns_series` 读回（schema 契约测试）。
4. **兼容性闸门**：asset_class 混杂 / 重叠观测不足 → 报错，不静默出数。
5. **样本外诚实性**：构造一组序列使 max_sharpe 样本内明显高于样本外 → 衰减警告触发；样本外优于最好单因子的正常情形不误报。
6. **组合专属 Reviewer**：迁移检查（regime/tail/beta）在组合收益上产出与单因子同款 finding；新检查（factor_concentration/correlation_health/improvement_over_best_single/weight_stability/portfolio_out_of_sample）各自的 pass/warning 分支；`determine_verdict` 聚合正确。
7. **Coordinator 工具端到端**（FakeLLMClient 脚本化 screen→optimize）：子 run 建立、`parent_run_id` 正确、组合 Reviewer + Critic 都跑、artifacts（portfolio_weights.json / portfolio_summary.json / backtest_result.json / research_note.md / review_report.json / critic_report.json）齐全、manifest 有 review/critic/metrics。
8. **Critic 优雅降级**：给 critic_llm 一个会抛异常的 fake，组合 run 仍正常 finalize，`critic_report.json["status"]=="unavailable"`（复用 Phase 8 模式）。
9. **CLI** `portfolio optimize`：多 run_id 输入产出组合 run；`--method` 覆盖生效。
10. **产物复用**：组合子 run 的 `backtest_result.json` 能进 `/api/compare` 的相关性矩阵、能被 ChartsPanel 读取。
11. **回归**：全量跑一遍，确认新增第 6 个工具 / 新 config 常量 / prompt 改动没有破坏现有 97 个测试。

---

## 八、验证

1. `uv run pytest tests/test_phase9_portfolio.py -q`，再全量 `uv run pytest -q` 确认零回归。
2. 手动真实链路：建小 S&P universe（limit=10）→ `screen_factors` 3 个因子 → `optimize_portfolio` 对存活因子。检查：`portfolio_weights.json` 权重和为 1 且合理；`portfolio_summary.json` 六种方法对照表齐全、样本外列反映衰减；`research_note.md` 里"组合优化 / Reviewer / Critic"三段都在且内容不同；`manifest.json` 的 `review`/`critic`/`metrics` 有值；组合夏普与多样化比率、以及"是否超过最好单因子"的结论一致。
3. 手动构造一批高相关因子，确认"多样化 ≈ 0 / 组合无增益"的警告如实触发（负向用例，验证诚实机器生效，而不是只在好情形下好看）。
4. 前端 `preview_start` 起 web：组合 run 出现在 library；ChartsPanel 渲染组合 equity 曲线；组合摘要卡片显示方法对照表 + 权重条 + 样本外诊断；compare 视图能把组合和其成分因子放一起看相关性。

---

## 九、来源与学术依据

- DeMiguel, Garlappi & Uppal (2009), *Optimal Versus Naive Diversification: How Inefficient Is the 1/N Portfolio Strategy?* —— 1/N 样本外常胜，本计划把等权设为强制锚的依据。
- Michaud (1989), *The Markowitz Optimization Enigma: Is 'Optimized' Optimal?* —— MVO 作为"误差最大化器"，本计划把 max_sharpe 降级为警示性对照的依据。
- Ledoit & Wolf (2004), 协方差收缩 —— 默认协方差估计器。
- López de Prado (2016), *Building Diversified Portfolios that Outperform Out of Sample*（HRP）—— `hrp` 方法，及与本项目已引用的 López de Prado 方法论（DSR/PBO/CPCV，见 [quant-research skill]）的衔接。
- Bailey & López de Prado (2012/2014), Probabilistic / Deflated Sharpe Ratio —— 第五节多重检验警告与可选 PSR 的依据，为将来接 DSR 留口。
- Robert Carver, 模块化风险配置框架 —— 风险平价/逆波动率作为稳健默认的依据（与 [quant-research skill] 一致）。

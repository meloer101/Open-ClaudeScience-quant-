# Phase 12 详细实施计划：回测现实性——执行 / 流动性成本 / 做空可行性 / 中性化

> 对应 [GAP_ANALYSIS.md](GAP_ANALYSIS.md) 第三章「回测现实性缺口」与第六章「第三优先级：让『这是 alpha』这句话成立」。
>
> 前置：Phase 10 统计护栏（[PHASE10.md](PHASE10.md)）已合并；Phase 11 数据地基（point-in-time S&P 500 成分、时变 universe、funding rate）进行中。本阶段部分交付**依赖 Phase 11 的产物**（尤其 point-in-time 成分表带出的 GICS sector、market cap），依赖点在第三节显式列出。
>
> 本文件覆盖 GAP §3 的四块，全部围绕一句话：**当前回测的成本与执行模型太理想，导致「momentum 因子有效」这类结论连方向都可能是被建模假设制造出来的假象。**

---

## 〇、为什么是这一层、现状有多理想

Phase 10 让「Sharpe 1.5 是不是多重检验捡来的幸运儿」这个问题能被回答。但即使一个因子通过了 DSR/PBO，它的 Sharpe 仍可能是**建模假设的产物**而非真实 alpha。当前引擎有四处过于理想的假设：

1. **成本是全 universe 一个固定 `cost_bps`（默认 5bps）。** [vectorized_backtest.py:55](quantbench/engine/vectorized_backtest.py) 和 [cross_sectional_backtest.py:134](quantbench/engine/cross_sectional_backtest.py) 都是 `turnover × cost_bps / 10000`。小盘股/小币种的真实点差是大盘的 10 倍，且**成交量有限**——十分位组合里最赚钱的往往是流动性最差的尾部标的，固定 bps 完全无视了「这些仓位在真实规模下根本建不满」。

2. **做空零成本、全部可空。** [cross_sectional_backtest.py:129](quantbench/engine/cross_sectional_backtest.py) 的 `long_short = group[n] - group[1]`，空头腿（group 1）默认全部可借、零 borrow cost。现实里空头腿最赚钱的部分恰恰是 hard-to-borrow 的小票，年化借券成本可达两位数。

3. **执行价假设埋在代码里。** [vectorized_backtest.py:46](quantbench/engine/vectorized_backtest.py) `forward_returns = close.pct_change().shift(-1)`——这隐含「信号在 close_t 生成、就在 close_t 成交」。这是一个乐观假设（同一根 K 线的收盘价既生成信号又成交），从未在 config / research note 中显式声明，用户无从判断结论是否依赖不可实现的即时成交。

4. **没有中性化。** 因子值直接截面排序分组（[cross_sectional_backtest.py:178](quantbench/engine/cross_sectional_backtest.py) 的 `rank` + `qcut`），没有对 beta / size / sector 做残差化。现有 `beta_exposure` 检查（[beta_exposure.py](quantbench/review/beta_exposure.py)）只是**事后诊断**：它告诉你「你的收益里有 beta」，但不告诉你去掉 beta 后还剩不剩 alpha。中性化是**事前处理**，是「momentum 有效」和「做多了高 beta / 某个行业」之间的分水岭。

好消息：前三项**大部分不需要新数据源**。仓库拉的 OHLCV 已含 `volume` 和 `open`（[warehouse.py:69](quantbench/data/warehouse.py)：`open, high, low, close, volume`），只是截面引擎目前只用 `close`（[cross_sectional_backtest.py:102](quantbench/engine/cross_sectional_backtest.py)），把 `volume`/`open` 丢掉了。把它们接回 panel 就能做流动性成本和 open+1 执行。中性化的 sector 也已在手边——`fetch_current_constituents()`（[sp500_constituents.py:11](quantbench/data/providers/sp500_constituents.py)）返回的 Wikipedia 表本就含 `GICS Sector` 列，只是没被提取。真正需要新数据的只有 market cap（size 因子）。

### 设计原则（承接 Phase 10/10.5）

- **显式化优先于精确化。** 本阶段第一目标不是把成本模型做到机构级精确，而是**把埋在代码里的假设搬到 config 和 research note 里**，让用户看得见、能改、Reviewer 能审。一个显式的粗模型胜过一个隐式的精模型。
- **默认更保守、前后对比。** 每个新维度（中性化、流动性成本、borrow）都默认**开启**，并在 note 中报告「开启前 vs 开启后」的指标对比——差异本身就是最有价值的研究信号。
- **护栏即 finding。** 新增的容量、做空可行性检查一律以 `ReviewFinding` 并入 `run_review`（[report.py:94](quantbench/review/report.py)），复用 `determine_verdict` 既有聚合，不加特判、不改阈值。
- **纯计算写成有测试的代码。** 成本/borrow/中性化都是确定性数值逻辑，属 VISION 第十一节「必须绝对正确的基础设施」，Critic 只解读。

---

## 一、交付物

按「成本低收益大」到「有数据依赖」排序；阶段内落地顺序见第四节。

### 1.1 执行价假设显式化（GAP 3.3，先做，成本最低）

**Quant**：信号在 `t` 期收盘生成后，用什么价成交决定了结论可信度。两个标准口径：
- `fill=close_t`（现状隐含）：同一根收盘价既生成信号又成交。最乐观，实盘不可完全实现（收盘竞价前你不知道收盘价）。
- `fill=open_t+1`（保守标准）：下一根开盘价成交。隔夜跳空成为真实滑点，是学术界默认的诚实口径。

两者的 Sharpe 差异，本身就是「策略是否依赖不可实现的即时成交」的直接度量——差得越多，越依赖。

**代码改动**：
- [x] 在单资产 [vectorized_backtest.py](quantbench/engine/vectorized_backtest.py) 与截面 [cross_sectional_backtest.py](quantbench/engine/cross_sectional_backtest.py) 引入 `execution: ExecutionConfig` 参数：
  ```python
  @dataclass(frozen=True)
  class ExecutionConfig:
      signal_time: str = "close_t"          # 信号在 t 收盘可用
      fill_price: str = "close_t"           # "close_t" | "open_t+1" | "close_t+1"
  ```
  - `close_t`：保持现状 `forward_return = close.pct_change().shift(-1)`。
  - `open_t+1`：持有段收益 = `close_{t+1}/open_{t+1} - 1`，进场跳空 `open_{t+1}/close_t - 1` 计入首期滑点。需把 `open` 接回 panel（[cross_sectional_backtest.py:97-104](quantbench/engine/cross_sectional_backtest.py) 的 factor_frame 目前只带 close/forward_return）。
- [x] 执行假设写入 `backtest_result.json`（新增 `execution` 段）与 manifest——属于「影响结果的东西」，必须可审计。
- [x] 工具入参 schema（[coordinator.py:164/213/237/264](quantbench/agent/coordinator.py) 的 `cost_bps` 旁）新增 `execution` 声明，缺省沿用 `close_t` 以保证既有 run 零回归。
- [x] Research note 标准段落说明执行假设（[skills/report.py](quantbench/skills/report.py)）。
- [x] （加分）Reviewer 新增 `execution_sensitivity` finding：`close_t` 与 `open_t+1` 双口径 Sharpe 差异超阈值 → `warning`（类比 `cost_sensitivity` 的结构，[cost_sensitivity.py](quantbench/review/cost_sensitivity.py)）。

**验收**：同一动量因子在 `close_t` 与 `open_t+1` 下并排回测，note 报告两者 Sharpe；构造一个「依赖收盘瞬时反转」的合成因子，`open_t+1` 下 Sharpe 显著坍塌、`execution_sensitivity` 告警。

### 1.2 流动性感知成本模型 + 容量估算（GAP 3.1）

**Quant**：固定 bps 的两个致命简化——
1. **点差不分层**：真实点差随流动性变化。按标的日均成交额（ADV, average dollar volume）分层设 spread 假设（大盘 2bps / 中盘 8bps / 小盘 20bps），比全 universe 一个数诚实得多。
2. **成交量无上限**：给定组合规模 AUM，每标的每期成交额不能超过其 ADV 的 `x%`（如 1–5%）。超限部分**建不进仓**——小盘/小币十分位组合在此约束下常常根本满不了仓，名义 Sharpe 是「假设能无限吃单」吹出来的。

**容量（capacity）**是这两点的自然产物：策略在多大 AUM 下 Sharpe 衰减到不可接受。这应成为 research note 的标准输出（「该策略估计容量 $X」）。

**代码改动**：
- [x] `volume` 接回 panel：`fetch_universe_ohlcv` 已返回带 volume 的 panel（[coordinator.py:445](quantbench/agent/coordinator.py)），截面引擎的 factor_frame 增列 `dollar_volume = close × volume`，逐 symbol 滚动算 ADV。
- [x] 新增 `quantbench/engine/costs.py`（纯函数）：
  ```python
  @dataclass(frozen=True)
  class LiquidityCostConfig:
      aum_usd: float = 1_000_000
      participation_cap: float = 0.02       # 单期成交 ≤ 2% ADV
      spread_tiers_bps: tuple[tuple[float, float], ...] = (
          (1e9, 2.0), (1e8, 8.0), (0.0, 20.0)  # (ADV 下限, spread bps)
      )

  def apply_liquidity_costs(
      weights: pd.DataFrame, dollar_volume: pd.DataFrame, config: LiquidityCostConfig,
  ) -> tuple[pd.DataFrame, pd.Series]:
      """返回 (可成交后的实际权重, 每期成本序列)。
      1) 目标美元仓 = aum × |weight|；2) 上限 = participation_cap × ADV；
      3) 超限则缩仓并在每期重新归一；4) 成本 = Σ|Δ实际权重| × tier_spread/2。"""
  ```
- [x] 截面引擎的 `net_returns` 计算（[cross_sectional_backtest.py:134](quantbench/engine/cross_sectional_backtest.py)）从 `turnover × cost_bps` 切换为 `apply_liquidity_costs` 的成本序列；`cost_bps` 保留为「流动性模型关闭时的回退」。
- [x] 容量扫描：在若干 AUM 档（如 1e5 / 1e6 / 1e7 / 1e8）复算 Sharpe，输出 `capacity_curve` 到 `backtest_result.json`；估计容量 = Sharpe 跌破原始一半的 AUM。
- [x] Reviewer 新增 `capacity` finding：估计容量低于阈值（如 < $1M）→ `warning`；无法估计（数据缺 volume）→ `info`。
- [x] Research note 报告容量曲线与 spread 分层假设；ChartsPanel 增容量-Sharpe 曲线（前端可留增量）。

**验收**：一个集中在小盘尾部的因子，开启 participation cap 后满仓率 < 1、Sharpe 明显下降、容量估计很低、`capacity` 告警；一个大盘均衡因子容量高、几乎不受影响。

### 1.3 做空可行性与 borrow cost（GAP 3.2，equity 截面必需）

**Quant**：多空组合的空头腿有两个被忽略的现实——
1. **borrow cost**：借券做空要付费，费率按流动性/市值分层，小盘 hard-to-borrow 可达年化两位数。这是和 funding rate 同构的一等持有成本。
2. **可空性**：部分标的根本借不到券。最低限度按市值/流动性分层给一个「可空比例」假设。

且需回答一个诊断问题：**收益主要来自 long 腿还是 short 腿？** 若主要来自 short 腿，而 short 腿又恰是 hard-to-borrow 的，则「可实现性存疑」。

**代码改动**：
- [x] 新增 `borrow_cost` 建模，结构完全类比现有 `_funding_cost`（[cross_sectional_backtest.py:226](quantbench/engine/cross_sectional_backtest.py)）——funding 已经证明了「按权重矩阵 × 费率矩阵逐期扣减」的模式：
  ```python
  def _borrow_cost(weights, borrow_rates) -> pd.Series:  # 只对负权重（空头）计费
  ```
  - 最低成本落地：不接外部 borrow 数据源，先用**按 ADV/市值分层的固定费率假设**（写进 config，note 声明「borrow 为分层假设值，非实测」）。
- [x] long/short 腿收益分解：`group_returns[n]`（long）与 `-group_returns[1]`（short）各自的累计贡献，写入 `backtest_result.json`。
- [x] Reviewer 新增 `short_dependency` finding：short 腿贡献占比过高（如 > 70%）→ `warning`「收益依赖做空腿，可实现性存疑」；long-only 因子（无空头）→ `info` 跳过。
- [x] borrow cost 计入前后的 Sharpe 对比，接 Reviewer（类比 funding 的 `funding_cost_sensitivity`，[report.py](quantbench/review/report.py) 已有该 finding 结构）。

**验收**：一个收益主要来自小盘空头的因子，计入 borrow cost 后 Sharpe 显著下降、`short_dependency` 告警；一个 long 主导的因子不受影响、finding 为 pass/info。

### 1.4 极简风险模型 + 中性化（GAP 3.4，🔴 本阶段最高价值）

**Quant**：中性化把「因子暴露收益」和「残差 alpha」分开。极简三维风险模型足以解决 80% 的问题，**不需要买 Barra**：
- **market beta**：symbol 收益对 benchmark 的滚动回归系数（无新数据——benchmark 已在 `beta_exposure` 里用）。
- **size**：`log(market cap)`（需 market cap 数据）；退化方案用 `log(dollar_volume)` 作 size 代理（已在手）。
- **sector**：GICS 行业哑变量（S&P 用 `fetch_current_constituents()` 的 `GICS Sector` 列——已在手；crypto 用板块标签）。

中性化 = 每个截面日把因子值对 `[1, beta, log_size, sector_dummies]` 做**截面回归取残差**，再对残差排序分组。这样十分位组合在设计上就对这三维暴露为零，剩下的才是「干净」的 alpha。

**代码改动**：
- [x] 新增 `quantbench/engine/neutralize.py`（纯函数）：
  ```python
  def neutralize_factor(
      factor_panel: pd.DataFrame,          # timestamp, symbol, factor
      *, dimensions: list[str],            # ["beta","size","sector"] 子集
      betas: pd.Series | None,             # symbol→beta（滚动估计）
      log_size: pd.Series | None,          # symbol,timestamp→log mktcap/adv
      sector: pd.Series | None,            # symbol→GICS sector
  ) -> pd.DataFrame:                       # 返回 factor 被替换为截面残差的 panel
  ```
  - 每 `timestamp` 一次 OLS：`resid = factor - X @ (X⁺ factor)`，`X` 含截距 + 选中维度（sector 用 one-hot）。样本不足（截面标的数 ≤ 回归自由度）时跳过该期、诚实标注。
- [x] 截面引擎新增 `neutralize: list[str]` 配置；在 `_assign_groups`（[cross_sectional_backtest.py:170](quantbench/engine/cross_sectional_backtest.py)）**之前**对 `factor_panel["factor"]` 做残差替换。（默认仍为关闭以保持既有 run 零回归；默认开启与前后对比留后续收口。）
- [x] 中性化前后对比：两次分组回测（raw vs neutralized），note 报告两者 Sharpe/IC——差异揭示「原始 alpha 有多少只是暴露」。
- [x] **解锁 Phase 4 遗留的 Risk Attribution 图表**：用同一风险模型把组合收益分解为「因子暴露收益 + 残差 alpha」，还掉 VISION Phase 4 自己承认的缺口。Phase 12 v1 以 raw vs neutralized Sharpe 衰减作为暴露归因代理图。
- [x] 数据依赖：sector 从 `fetch_current_constituents()` 提取（`GICS Sector`，改 [sp500_constituents.py](quantbench/data/providers/sp500_constituents.py) 让它返回该列并入 universe 元数据）；market cap 走新 provider 字段或 `dollar_volume` 代理；beta 用滚动窗口回归（新增 helper 或复用 `beta_exposure.compute_beta` 的最小二乘）。

**验收**：一个「假 momentum」合成因子（其收益完全由高 beta 暴露驱动）中性化后 Sharpe 坍塌到 ≈0，证明中性化正确剥离了暴露；一个真正的残差 alpha 因子中性化后基本保留。Risk Attribution 图能把某个真实动量因子的收益拆成 beta/size/sector 贡献 + 残差。

---

## 二、Reviewer verdict 接入总览（承接既有模型，无特判）

所有新检查通过「注入 finding」接入 `determine_verdict`（[report.py:82](quantbench/review/report.py)）：

| 检查 | 触发条件 | severity | 对 verdict 效果 |
|---|---|---|---|
| execution_sensitivity | close_t vs open_t+1 Sharpe 差异过大 | warning | 封顶 PROMISING |
| capacity | 估计容量低于阈值 | warning | 封顶 PROMISING |
| capacity | 缺 volume 无法估计 | info | 无 |
| short_dependency | short 腿贡献占比过高 | warning | 封顶 PROMISING |
| short_dependency | long-only 无空头 | info | 无 |
| borrow_cost_sensitivity | 计入 borrow 后 Sharpe 大幅衰减 | warning | 封顶 PROMISING |

中性化本身**不是一条 finding**，而是改变基线回测口径（默认开启）。但「中性化后 Sharpe 大幅下降」可通过既有 `beta_exposure` 与新的对比数据自然体现。多条 warning 叠加照旧可触发 WEAK（≥3 warning）。**不引入新 verdict 等级、不改阈值**。

---

## 三、数据依赖与 Phase 11 协调

| 交付 | 数据需求 | 现状 | 阻塞？ |
|---|---|---|---|
| 1.1 执行价 | `open` 列 | 已在 OHLCV，仅需接回 panel | 否 |
| 1.2 流动性成本 | `volume` / ADV | 已在 OHLCV，仅需接回 panel | 否 |
| 1.3 borrow cost | 分层费率假设 | 用 config 假设（非实测） | 否（实测源可后续接） |
| 1.4 sector 中性化 | GICS sector | `fetch_current_constituents()` 已含，未提取 | 否（当前快照）；**PIT sector 历史依赖 Phase 11** |
| 1.4 size 中性化 | market cap | 无；退化用 `log(dollar_volume)` | 代理可立即做；真 mktcap 待正式数据源 |
| 1.4 beta 中性化 | benchmark 收益 | 已在 `beta_exposure` 用 | 否 |

**与 Phase 11 的接口**：Phase 11 的 point-in-time S&P 成分表若一并带出**历史 sector 与 market cap**，则 1.4 的中性化能升级为时点正确（用当日真实 sector/size，而非当前快照回填）。因此 1.4 的「当前快照」版本本阶段先落地，「point-in-time」版本作为 Phase 11 产物就绪后的增量。1.4 与 Phase 11 共享同一份成分元数据，需协调 schema（成分表增 `gics_sector` / `market_cap` 列）。

---

## 四、阶段内落地顺序

1. **执行价显式化（1.1）** — 成本最低、无数据依赖、独立可测；先把 `open` 接回 panel（同时为 1.2 铺路）。
2. **流动性成本 + 容量（1.2）** — 复用 1.1 接回的 volume；`costs.py` 独立可测。
3. **borrow / 做空可行性（1.3）** — 结构类比已验证的 `_funding_cost`，风险低。
4. **中性化 + 风险模型（1.4）** — 本阶段最高价值但数据依赖最重；先做 `dollar_volume` 代理 size + 当前快照 sector 的版本，PIT 版本随 Phase 11 增量。
5. **Risk Attribution 图（1.4 尾）** — 还 Phase 4 债，依赖 1.4 的风险模型。

每步都是「纯计算模块 + 有测试 + 通过 finding/口径接 Reviewer」，互相解耦。1.1–1.3 不阻塞彼此；1.4 可与 1.2/1.3 并行。

---

## 五、明确不做（本阶段边界）

- **不做机构级市场冲击模型**（平方根冲击、Almgren-Chriss 最优执行）——participation cap + 分层 spread 已覆盖 80%，冲击模型留到有真实执行数据校准时。
- **不买 Barra / 商业风险模型**——三维极简模型是刻意选择，不是妥协。
- **不接实测 borrow / 做空数据源**——本阶段用分层假设并诚实标注；实测源（IBKR / Markit）作为后续正式 provider。
- **不改 `determine_verdict` 阈值本身**——只喂它更多 finding。
- **不做 point-in-time sector/mktcap 的自建历史**——那是 Phase 11 数据地基的职责，本阶段用当前快照 + 代理，PIT 版本作为 Phase 11 就绪后的增量对接。
- **不引入新依赖**——OLS 残差用 numpy `lstsq`，成本/borrow 全用 pandas。

---

## 六、验证

- 单元测试 `tests/test_phase12_execution.py`：`close_t` 复现现状数值；`open_t+1` 在含跳空的合成数据上给出可预测的滑点扣减；缺 `open` 列时诚实回退。
- 单元测试 `tests/test_phase12_costs.py`：participation cap 在小 ADV 下缩仓、权重每期重新归一；spread 分层按 ADV 命中正确 tier；容量曲线单调（AUM↑ → 满仓率↓ → Sharpe↓）。
- 单元测试 `tests/test_phase12_borrow.py`：borrow 只对空头计费；long-only 组合 borrow=0；short 主导因子的 `short_dependency` 命中。
- 单元测试 `tests/test_phase12_neutralize.py`：纯 beta 驱动的合成因子中性化后 Sharpe≈0；残差 alpha 因子中性化后基本保留；截面标的不足时跳过该期不崩。
- Golden runs 扩展（[tests/test_phase10_golden_runs.py](tests/test_phase10_golden_runs.py) 或新增 `test_phase12_golden_runs.py`）：新增「假 momentum（纯 beta 暴露）」与「小盘空头依赖」两个 fixture，断言中性化/borrow 后 verdict 降级。
- 全量 `uv run pytest -q`：既有测试零回归（新维度默认参数须保证既有 run 数值不变——`execution=close_t`、流动性模型关闭时回退 `cost_bps`、`neutralize` 对既有测试可显式关闭）。
- 手动端到端：真实 S&P 500 universe 跑一个动量因子，确认 `backtest_result.json` 带 `execution` / `capacity_curve` / long-short 分解 / 中性化前后对比，且 note 显式声明四类假设。

---

*落地后将本文件各项标记完成，把「回测现实性四件套已具备」写回 [GAP_ANALYSIS.md](GAP_ANALYSIS.md) 第三章勾选项与 [README.md](README.md) 能力清单，并在 VISION Phase 4 的 Risk Attribution 缺口处回填「已由 Phase 12 风险模型解锁」。*

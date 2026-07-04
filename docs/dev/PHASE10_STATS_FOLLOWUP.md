# Phase 10.5 详细实施计划：统计严谨性收尾——CPCV / Purge-Embargo / IC 显著性

> 对应 [GAP_ANALYSIS.md](GAP_ANALYSIS.md) 第二章「统计严谨性缺口」中 **Phase 10 未覆盖的残项**。
>
> 前置：Phase 10（[PHASE10.md](PHASE10.md)）已合并——DSR（[deflated_sharpe.py](quantbench/review/deflated_sharpe.py)）、PBO/CSCV（[pbo.py](quantbench/review/pbo.py)）、单层 walk-forward（[walk_forward.py](quantbench/review/walk_forward.py)）、block bootstrap CI（[bootstrap.py](quantbench/review/bootstrap.py)）、试验次数记账（[trials.py](quantbench/library/trials.py)）、golden runs（[tests/test_phase10_golden_runs.py](tests/test_phase10_golden_runs.py)）均已落地并接入 Reviewer。
>
> 本文件只处理 Phase 10 **明确标注延后**的两块，二者是 GAP 第二章目前唯一真正未闭合的勾选项：
> 1. **CPCV + purge/embargo**（GAP 2.2 / PHASE10 2.4.1，原文「留到 Phase 11 一并处理」）
> 2. **IC t 统计量 / Newey-West 修正标准误**（GAP 2.3，原文标为加分项、非必做）

---

## 〇、为什么单独成篇、为什么是现在

Phase 10 把「制造幸运儿的机器」配上了「识别幸运儿的报警器」，但报警器有两处**已知的近似**当时为了不阻塞主线而接受：

1. **Walk-forward 是顺序单切，不是组合式、且不 purge。** 现有 [walk_forward.py:29](quantbench/review/walk_forward.py) 用 `np.linspace` 把样本切成 N 段**互不重叠的连续窗口**，再逐段当 OOS 跑；`embargo_bars`（[walk_forward.py:24](quantbench/review/walk_forward.py)）只是从每段头部裁掉几根，**不是** López de Prado 意义上的 purge/embargo。后果：
   - 因子有 lookback（如 20 日动量）时，训练段末尾与测试段开头的样本共享重叠的 rolling window，**信息从训练泄漏进测试**，OOS 指标偏乐观。
   - 单一顺序切分只给出 N 个高度相关的窗口，方差估计不诚实。CPCV 用 `C(S, S/2)` 组合把有效 OOS 路径数放大一到两个量级，才配得上「报告分布而非单点」这句话。

2. **IC 只有点估计，没有显著性。** [metrics.py:53](quantbench/engine/metrics.py) 的 `information_coefficient` 返回一个 Spearman 标量；截面引擎已有逐期 `ic_series`（[cross_sectional_backtest.py:27](quantbench/engine/cross_sectional_backtest.py)），但**从未对它做过 t 检验**。IC 序列几乎总有自相关（信号持续、行情有惯性），朴素 `mean/std·√T` 会高估 t 值。缺 Newey-West HAC 标准误，等于让 research note 报一个不可信的「IC=0.03」而不敢说它显不显著。

这两项都属于 VISION 第十一节的「必须绝对正确的基础设施」：**纯确定性计算、写成有测试的 Python、Critic/Coordinator 只解读**。且都无外部数据依赖，可立即开工——放在 Phase 11（数据地基）真正动到时变 universe 之前收掉，避免统计层与数据层的改动互相纠缠。

### 设计原则（承接 Phase 10）

- **护栏即 finding。** 一切新检查以 `ReviewFinding` 并入 `findings`，复用 `determine_verdict`（[report.py:73](quantbench/review/report.py)）既有聚合，不加特判、不改阈值、不引入新 verdict 等级。
- **诚实降级而非误伤。** 样本不足 / 配置太少 / 无法确定 lookback 时一律返回 `info`（不影响 verdict），只有在**能可靠判定**时才 `warning`。
- **不引入新依赖。** numpy / scipy / pandas 现有栈足够（组合数用 `itertools.combinations`，正态分位用 `scipy.stats.norm`，HAC 用手写 Bartlett 核）。

---

## 一、交付物

### 1.1 因子 lookback 声明（purge/embargo 的输入前提）

purge/embargo 的宽度必须等于「一个样本的信息向前污染多少根 bar」，即因子的 rolling lookback。当前系统**没有任何地方声明这个数**（`grep lookback` 只命中数据刷新模块，与因子无关）。先把这个输入做出来，CPCV 才有正确的 purge 宽度。

**改动**：
- [x] 因子 `compute()` 的元数据里新增可选声明 `lookback_bars: int`。两条获取路径，按可靠度排序：
  1. **显式声明（主）**：factor spec / config 里带 `lookback_bars`，直接用。
  2. **推断（辅，保守）**：无显式声明时，从 `compute()` 源码里的 rolling 窗口参数启发式提取（`.rolling(N)` / `.shift(N)` / `.ewm(span=N)` 的最大 N）。提取失败则回退到一个**保守默认**（如 `max(21, 0.02·T)`），并在 finding 里标注「lookback 为推断值」。
- [x] `lookback_bars` 与其来源（`declared` / `inferred` / `default`）写入 manifest 与 `backtest_result.json`，让 purge 宽度可审计——这是「每个影响结果的东西都进 manifest」承诺的一部分。

**验收**：一个声明了 `lookback_bars=20` 的动量因子，CPCV 的 purge 宽度精确等于 20；一个未声明的因子拿到 `inferred` 或 `default` 并在 note 里被诚实标注。

### 1.2 CPCV（Combinatorial Purged Cross-Validation）

Bailey/López de Prado。把样本按时间切成 `S` 个等长 group，每次选 `S/2` 个 group 作 test、其余作 train，遍历全部 `C(S, S/2)` 组合；每个 train/test 边界两侧按 `lookback_bars` 做 **purge**（删掉与测试段 rolling window 重叠的训练样本）+ **embargo**（测试段之后再留一段禁区，防止反向泄漏）。产出的是**一组 OOS 路径**上的指标分布。

**改动**：
- [x] 新增 `quantbench/review/cpcv.py`（纯函数，无 I/O）。**关键设计决定**：CPCV 作用在**已算好的逐期组合收益序列 `returns`（timestamp 索引）**上，而**不是**在子集上重算因子。原因是重算方案有两个致命缺陷：① 把不相邻的 test group `concat` 起来重算 rolling 因子会跨接缝算 lookback；② 截面 panel 是长格式（每个 timestamp 多行），按行位置 `iloc` 切会切穿单个 timestamp 的截面。对已算好的收益序列**只做选择、不重算**，两个问题一起消失——`t` 时刻的收益保持它真实的值。
  ```python
  @dataclass(frozen=True)
  class CPCVResult:
      path_test_sharpes: list[float]     # 每条组合路径的 OOS Sharpe
      median_test_sharpe: float
      iqr_test_sharpe: float
      p05_test_sharpe: float             # 5% 分位——尾部诚实度
      positive_path_share: float         # OOS Sharpe>0 的路径占比
      n_paths: int
      n_groups: int
      purge_bars: int
      embargo_bars: int

  def run_cpcv(
      returns: pd.Series,                # 逐期组合收益，timestamp 索引
      *,
      n_groups: int = 6,                 # C(6,3)=20 条路径，算量可控
      lookback_bars: int = 0,            # → purge 宽度
      embargo_frac: float = 0.01,        # → embargo = ceil(embargo_frac·T)
  ) -> CPCVResult: ...
  ```
  - 组合用 `itertools.combinations(range(n_groups), n_groups // 2)`。
  - **Purge/embargo 真正生效**：一个 test 期 `i` 只有当它整个 `[i − purge_bars, i + embargo_bars]` 邻域**全部**仍是 test 期时才纳入评估；只要 lookback 邻域碰到任何 train（非 test）期，该期被丢弃。因此调大 `lookback_bars` 会丢掉更多边界期、改变 OOS Sharpe——「purged」是真实效果而非标签。年化用 [metrics.py](quantbench/engine/metrics.py) 的 `annualized_sharpe` + `periods_per_year_from_timestamps`，口径与引擎一致。
  - `n_groups < 4`、非偶数、或 `len(returns) < n_groups`（配置太少）→ 返回空结果，上层转 `info`。
- [x] `run_review`（[report.py:81](quantbench/review/report.py)）新增 `_cpcv_finding`，接入方式与既有 `_walk_forward_finding`（[report.py:322](quantbench/review/report.py)）完全一致：
  - `positive_path_share < 0.5`（半数以上 OOS 路径 Sharpe 非正）→ `warning`（封顶 PROMISING）。
  - `p05_test_sharpe`（尾部路径）远差于 median → detail 里点名「OOS 分布左尾很重」，但严重度仍由 `positive_path_share` 决定，避免双重降级。
  - 路径不足 → `info`。
- [x] **与既有 walk-forward 的关系**：CPCV 不替换、而是**升级** walk-forward。保留单层 walk-forward 作为「快速、直觉」的信号；CPCV 是「慢、严谨」的分布证据。二者并存，各出一条 finding（与 Phase 10「单次 OOS 与 walk-forward 并存」同构）。
- [x] `_screen_factors`（[coordinator.py](quantbench/agent/coordinator.py)）对每个候选跑 CPCV，`CPCVResult` 作为 `factor_screen_summary.json` 每条候选的输出列（与 DSR 列并列）。

**验收**：
- 已知过拟合因子（`overfit_factor` golden fixture）：CPCV 的 `positive_path_share` 明显低于单层 walk-forward 给出的乐观值，warning 触发、verdict 封顶。
- 稳健因子（`robust_factor`）：purge 前后 OOS 分布几乎不变（说明本就没有泄漏），不被误伤。
- **泄漏可见性测试**（`test_cpcv_purge_drops_boundary_periods_and_changes_oos_sharpe`）：在每个 group 边界注入正收益尖峰，断言开启 purge 后这些边界期被丢弃、median OOS Sharpe **真的下降**——直接证明 purge 在起作用（而非只改一个未被消费的 attrs 字典）。

### 1.3 IC t 统计量 + Newey-West HAC 标准误

对逐期 `ic_series` 做带自相关修正的显著性检验，让 note 敢说「IC 显著」。

**改动**：
- [x] `quantbench/engine/metrics.py` 新增纯函数（与既有 `information_coefficient` 并列，不改其签名）：
  ```python
  @dataclass(frozen=True)
  class ICSignificance:
      ic_mean: float
      ic_std: float
      t_stat: float                  # Newey-West HAC 修正后
      p_value: float                 # 双边
      n_periods: int
      nw_lags: int                   # 用的滞后阶数
      is_significant: bool           # |t| > 1.96（默认 5%）

  def ic_newey_west(ic_series: pd.Series, *, lags: int | None = None) -> ICSignificance: ...
  ```
  - HAC 方差 = γ₀ + 2·Σ_{k=1..L} w_k·γ_k，Bartlett 核 `w_k = 1 − k/(L+1)`；默认 `L = floor(4·(T/100)^(2/9))`（Newey-West 经验规则）。
  - `t = mean / sqrt(HAC_var / T)`，`p_value` 用 `scipy.stats.norm.sf`（或 `t.sf`，样本小时更保守）。
  - `T < 10` → 返回 `is_significant=False` 且 `t_stat=nan`，上层转 `info`。
- [x] 截面引擎在产出 metrics 时顺带算一次，把 `ICSignificance` 写入 `backtest_result.json`（新增 `ic_significance` 字段，与 Phase 10 的 `metrics_ci` 并列，不动既有 `metrics`）。截面引擎已持有 `ic_series`（[cross_sectional_backtest.py:134](quantbench/engine/cross_sectional_backtest.py)），零额外计算成本。
- [x] `run_review` 新增 `_ic_significance_finding`：截面 run 且 `is_significant=False` → `warning`（IC 方向对不代表统计上站得住）；显著 → `pass`；样本不足或非截面 run → `info`。
- [x] Research note 模板（[skills/report.py:272](quantbench/skills/report.py) 的 `_metrics_rows` 已支持 CI 展示）扩展：IC 行改为 `IC 0.03 (t=2.4, p=0.02, NW-lags=3)` 格式；不显著时显式标红「未通过显著性」。

**验收**：
- 已知 IC 高度自相关的合成序列：Newey-West 的 t 值**明显低于**朴素 `mean/std·√T`，证明修正在起作用。
- `robust_factor` 的 IC 显著（t>2）；`noise_batch` 里挑出的「最高 IC」因子经 NW 修正后不显著。

### 1.4 Golden runs 扩展

把两个新检查纳入既有回归护栏，防止后续 prompt/模型/阈值漂移。

**改动**：
- [x] 复用 [tests/fixtures/golden/](tests/fixtures/golden/) 现有 fixture，新增断言：
  - `overfit_factor` / 泄漏合成因子 → CPCV `positive_path_share` 低、warning 触发。
  - `robust_factor` → CPCV purge 前后稳定、IC NW-t 显著。
  - `noise_batch` → 批内最高 IC 因子 NW 修正后不显著。
- [x] `tests/test_phase10_golden_runs.py` 增加对应用例（或新增 `tests/test_phase105_golden_runs.py`，与 Phase 10 golden 并列跑）。

---

## 二、Reviewer verdict 接入总览（承接 Phase 10 §三，无特判）

| 检查 | 触发条件 | severity | 对 verdict 效果 |
|---|---|---|---|
| cpcv | 半数以上 OOS 路径 Sharpe 非正 | warning | 封顶 PROMISING |
| cpcv | 路径/样本不足、窗口被 purge 吃空 | info | 无 |
| ic_significance | 截面 run 且 NW-t 不显著（\|t\|<1.96） | warning | 封顶 PROMISING |
| ic_significance | 样本不足 / 非截面 run | info | 无 |

多条 warning 叠加照旧可自然触发 WEAK（≥3 warning）。**不改 `determine_verdict` 阈值，不加新等级**——只喂它更多 finding。与 Phase 10 完全同构。

---

## 三、阶段内落地顺序

1. **lookback 声明（1.1）** — purge 的输入，先行。先做显式声明路径，推断/默认作为回退。
2. **CPCV（1.2）+ verdict 接入** — 本阶段核心，依赖 1.1 的 purge 宽度。含泄漏可见性测试。
3. **IC Newey-West（1.3）+ verdict 接入 + note** — 独立于 CPCV，可与 2 并行。
4. **Golden runs 扩展（1.4）** — 收尾，锁定 1.2 / 1.3 行为。

每步都是「纯计算模块 + 有测试 + 通过 finding 接 Reviewer」，互相解耦，任一步不阻塞其余。

---

## 四、明确不做（本阶段边界）

- **不改 `determine_verdict` 阈值本身**——校准是独立议题（Phase 2 遗留），本阶段只喂更多 finding。
- **不做 IC 的贝叶斯 / 因子模型级显著性**——NW-t 已够。
- **不做远程/并行加速**——`C(6,3)=20` 条路径 × 每候选，本地单机可承受。若批量筛选把算量顶上去，性能优化留到真正成为瓶颈时（GAP 4.6）。
- **不动 Phase 10 已落地的 DSR/PBO/bootstrap/单层 walk-forward 的对外接口**——只在其旁并列新增，零回归。
- **不替换单层 walk-forward**——CPCV 与之并存（见 1.2 最后一条）。

---

## 五、验证

- `uv run pytest tests/test_phase105_statistics.py -q`：
  - CPCV：`n_groups=6` → 20 条路径；purge 宽度 = `lookback_bars`；泄漏合成因子开 purge 后 OOS Sharpe 显著下降；全同配置矩阵路径分布退化正确。
  - IC NW：已知自相关序列 NW-t < 朴素 t；白噪声序列 NW-t ≈ 朴素 t；`T<10` 退 `info`。
- `uv run pytest tests/test_phase105_golden_runs.py -q`：新断言全命中。
- 全量 `uv run pytest -q`：既有测试零回归（新检查对既有单 run / 非截面测试默认转 `info`，不改变既有 verdict）。
- 手动端到端：对真实 S&P 500 universe 跑一批含 `overfit_factor` 的 `screen_factors`，确认 `factor_screen_summary.json` 每条候选带 CPCV 列，截面 run 的 `backtest_result.json` 带 `ic_significance`，且过拟合候选被 CPCV warning 封顶。

---

*落地后将本文件各项标记完成，把「CPCV / purge-embargo / IC 显著性已具备」写回 [GAP_ANALYSIS.md](GAP_ANALYSIS.md) 第二章 2.2 / 2.3 的对应勾选项与 [README.md](README.md) 能力清单，并在 [PHASE10.md](PHASE10.md) §2.4.1 的延后标注处回填指针。*

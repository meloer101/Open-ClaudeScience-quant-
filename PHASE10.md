# Phase 10 详细实施计划：统计护栏——多重检验修正 / DSR / PBO / Walk-forward / Bootstrap CI

> 对应 [GAP_ANALYSIS.md](GAP_ANALYSIS.md) 第二章「统计严谨性缺口」与第六章「第一优先级：统计护栏」。
> 前置条件：Phase 0–9 已完成并合并到 `main`；确定性 Reviewer（[quantbench/review/report.py](quantbench/review/report.py)）、独立 Critic、批量因子筛选（[quantbench/agent/coordinator.py](quantbench/agent/coordinator.py) 的 `_screen_factors`）、实验库（[quantbench/library/](quantbench/library/)）均已落地。
> 目标：给**已经上线的批量因子筛选能力**补上多重检验护栏。当前系统能一次筛 N 个因子却没有任何统计修正——即使 N 个全是噪声，也几乎必然有 1–2 个 OOS Sharpe 好看，系统会把它们标成 PROMISING/STRONG。这是当前最危险的能力错配，且不依赖任何新数据源，纯确定性计算，可立即开工。

> **关于编号**：老 `PHASE10.md`（Live Signal Monitoring）已随「生产化」工作落地（commit `513e20a`，代码在 [quantbench/monitor/](quantbench/monitor/)），其计划文档已在清理中删除。GAP_ANALYSIS v1.0 重新基线化了后续编号：Phase 10 = 统计护栏、Phase 11 = 数据地基、Phase 12 = 风险模型与回测现实性、Phase 13+ = 产品形态。本文件采用该基线。

---

## 一、为什么是现在、为什么是这一层

Reviewer 现有 9 项检查（lookahead / out_of_sample / cost_sensitivity / parameter_stability / regime / tail_dependence / turnover / beta_exposure / symbol_concentration）覆盖面不错，但有一个共同的盲点：**它们全部是针对「单个 run」的检查**。没有任何一项会问：

> 「你这个 Sharpe 1.5 好看的因子，是从你今天试的 20 个因子里挑出来的那一个吗？」

这正是多重检验（multiple testing）问题。`_screen_factors` 的 fan-out 已经把「同时试很多个」这件事做成了产品能力（[coordinator.py:496](quantbench/agent/coordinator.py)），但挑出赢家之后没有任何统计打折。**制造幸运儿的机器开着，识别幸运儿的报警器没装。**

本阶段遵循 VISION 第十一节准则：DSR / PBO / bootstrap / walk-forward 都是「必须绝对正确的基础设施」——**写成有测试的纯 Python，Critic/Coordinator 只解读结果，不参与计算**。

### 设计原则：护栏即 finding，verdict 自然降级

现有 `determine_verdict`（[report.py:73](quantbench/review/report.py)）的聚合规则是：任一 critical → REJECTED；≥3 warning → WEAK；任一 warning → PROMISING；否则 STRONG。

这意味着**「DSR 不显著就封顶 PROMISING、不给 STRONG」等价于「注入一条 warning finding」**——无需给 verdict 逻辑加任何特判。新增的统计检查全部以 `ReviewFinding` 形式并入 `findings` 列表，复用既有聚合。这是最小侵入、且与全系统「一切皆 finding」模型一致的接法。

---

## 二、交付物

按依赖和收益排序，阶段内落地顺序见第四节。

### 2.1 试验次数记账（DSR/PBO 的输入前提）

多重检验修正的核心输入是「试验次数 N」。有两个来源，可靠度不同，本阶段都做但分清主次：

- **批内 N（主，可靠）**：一次 `_screen_factors` 调用里 `len(candidates)` 就是精确的试验次数。这是 DSR 最可辩护的输入——你**确切知道**这一轮试了多少个。
- **跨历史 N（辅，近似）**：针对同一 `universe × 时段`，实验库里历史上一共试过多少个因子/参数。这是人工研究者记不住、只有平台能自动做到的部分，但「同一 universe×时段」的匹配是模糊的，作为对批内 N 的**增量放大**，不作为唯一依据。

**改动**：
- [x] 新增 `quantbench/library/trials.py`：`count_trials(universe_signature: str, start: str, end: str) -> TrialCount`，扫描 `ExperimentIndex.build()`（[library/index.py:16](quantbench/library/index.py)），按 universe 签名 + 日期区间重叠归并计数。`universe_signature` 从 `config["universe"]`（asset_class + provider + symbols 排序 hash）派生。
- [x] `ExperimentRecord`（[library/record.py:36](quantbench/library/record.py)）新增派生字段 `universe_signature`、`window_start`、`window_end`（从 config 读，无则 None），供 `count_trials` 归并。
- [x] `_screen_factors` 在 fan-out 前计算 `effective_trials = len(candidates) + count_trials(...).prior_trials`，写入 `factor_screen_summary.json` 的顶层，并逐候选传入 DSR 计算。

**验收**：连续对同一 S&P 500 universe、同一时段跑两批各 10 个因子，第二批的 `effective_trials` 反映累计（≈20+），research note / 筛选结果显式标注「本结论基于 N 次试验修正」。

### 2.2 Deflated Sharpe Ratio（DSR，本阶段核心）

Bailey & López de Prado (2014)。给定观测 Sharpe、试验次数 N、以及候选 Sharpe 的横截面方差 + 收益序列的偏度/峰度/样本长度，计算「在 N 次试验的多重检验下，这个 Sharpe 仍显著为正的概率」。

**改动**：
- [x] 新增 `quantbench/review/deflated_sharpe.py`（纯函数，无 I/O）：
  ```python
  @dataclass(frozen=True)
  class DeflatedSharpeResult:
      observed_sharpe: float
      deflated_sharpe: float        # P(true SR > 0)，已对多重检验修正
      expected_max_sharpe: float    # N 次试验下纯噪声能达到的期望最大 SR（SR0）
      n_trials: int
      sharpe_std_across_trials: float
      n_observations: int
      skew: float
      kurtosis: float
      is_significant: bool          # deflated_sharpe > 0.95

  def deflated_sharpe_ratio(
      returns: pd.Series,
      *,
      n_trials: int,
      trial_sharpes: list[float] | None = None,  # 无则用保守默认方差
      periods_per_year: float,
  ) -> DeflatedSharpeResult: ...
  ```
  - SR0（expected max under null）用 Bailey-LdP 的 Euler-Mascheroni 近似：`SR0 = sqrt(Var_SR) * ((1-γ)·Z⁻¹(1-1/N) + γ·Z⁻¹(1-1/(N·e)))`。
  - `deflated_sharpe` 用带偏度/峰度修正的 SR 标准误（PSR 公式），对 `SR0` 做单边检验。
  - 复用 [engine/metrics.py](quantbench/engine/metrics.py) 的 `periods_per_year_from_timestamps` 保证年化口径一致。
- [x] `run_review`（[report.py:81](quantbench/review/report.py)）新增可选参数 `n_trials: int = 1`、`trial_sharpes: list[float] | None = None`；新增 `_dsr_finding`：`is_significant=False` → `warning`（自然封顶 PROMISING），显著 → `pass`，`n_trials<=1 或样本不足` → `info`（诚实跳过，不误伤单 run 研究）。
- [x] `_screen_factors` 把每个候选的 DSR 作为 `factor_screen_summary.json` 每条候选的**强制输出列**，并把 DSR finding 注入该候选自己的 `review_report`。

**验收**：构造 20 个纯随机噪声因子（synthetic）跑 `screen_factors`，「原始最高 Sharpe」的那个因子 DSR 显示不显著、verdict 被封顶到 PROMISING 或以下；对一个真实稳健因子（N=1）DSR finding 返回 `info` 不误伤。

### 2.3 PBO / CSCV（回测过拟合概率）

Bailey et al. (2017) 的组合对称交叉验证（CSCV）。把收益矩阵（N 配置 × T 时点）切成 S 个等长子块，遍历 `C(S, S/2)` 种 train/test 组合，看「样本内最优配置在样本外落到中位数以下」的频率，logit 变换为 PBO 概率。

**改动**：
- [x] 新增 `quantbench/review/pbo.py`：
  ```python
  @dataclass(frozen=True)
  class PBOResult:
      pbo: float                    # P(IS-best 在 OOS 低于中位数)
      n_configs: int
      n_splits: int
      logits: list[float]
      is_overfit: bool              # pbo > 0.5

  def probability_of_backtest_overfitting(
      returns_matrix: pd.DataFrame,  # columns=候选名, index=时间, values=每期收益
      *, n_splits: int = 16,
  ) -> PBOResult: ...
  ```
- [x] `_screen_factors` 用各候选的逐期收益序列拼 `returns_matrix`，跑一次 PBO，写入 `factor_screen_summary.json` 顶层（PBO 是**批级**指标，不是逐候选）。`is_overfit=True` 时给整批打一条顶层 warning，并在每个候选 review 里注入 `pbo_batch` 提示。
- [x] N<4（配置太少，CSCV 无意义）时诚实返回 `info` 跳过。

**验收**：对上面 20 个噪声因子的批次，PBO 显著偏高（≫0.5）；对一组已知彼此独立的稳健因子，PBO 明显更低。

### 2.4 Walk-forward 多窗口验证

现状 `out_of_sample.py` 只切一刀（`split_ratio=0.7`），单次切分方差大、运气成分重。Walk-forward 滚动切多个窗口，报告 OOS 指标的**分布**而非单点。

**改动**：
- [x] 新增 `quantbench/review/walk_forward.py`（照 [out_of_sample.py](quantbench/review/out_of_sample.py) 的 `run_on_data` 回调协议写，复用同款 `Callable[[pd.DataFrame], dict]`）：
  ```python
  @dataclass(frozen=True)
  class WalkForwardResult:
      window_test_sharpes: list[float]
      median_test_sharpe: float
      iqr_test_sharpe: float
      positive_window_share: float   # OOS Sharpe>0 的窗口占比
      n_windows: int

  def run_walk_forward(
      data: pd.DataFrame,
      run_on_data: Callable[[pd.DataFrame], dict[str, float]],
      *, n_windows: int = 4, embargo_bars: int = 0,
  ) -> WalkForwardResult: ...
  ```
  - 滚动 anchored / rolling 窗口；`embargo_bars` 预留 purge/embargo（见 2.4.1）。
- [x] `run_review` 新增 `_walk_forward_finding`：`positive_window_share < 0.5`（半数以上窗口 OOS 为负）→ `warning`；窗口数不足 → `info`。与既有单次 OOS 检查并存（单次是快速信号，walk-forward 是分布证据）。

#### 2.4.1 CPCV + purge/embargo（Phase 10.5 已落地）

- [x] 组合式覆盖（Combinatorial Purged CV）+ purge/embargo，防止信号 lookback 导致训练/测试边界信息泄漏。`embargo_bars` / `purge_bars` 与因子 lookback 联动——从 `compute()` 的 rolling / shift / ewm / pct_change 参数推断，或要求 config 显式声明 `lookback_bars`。实现见 [PHASE10_STATS_FOLLOWUP.md](PHASE10_STATS_FOLLOWUP.md)、[cpcv.py](quantbench/review/cpcv.py) 和 [lookback.py](quantbench/review/lookback.py)。
- [x] 若时间紧，本阶段先落地无 purge 的 walk-forward，CPCV 留到 Phase 11（数据地基期一并处理时变 universe 时更顺）。**明确标注此项可延后，不阻塞 2.1–2.3 主线。**

### 2.5 Bootstrap 置信区间

现状 research note 报「Sharpe 1.42」单点值，误导。改为区间。

**改动**：
- [x] 新增 `quantbench/review/bootstrap.py`：`block_bootstrap_ci(returns, *, metric="sharpe", n_boot=1000, block_size=None, alpha=0.05) -> tuple[float, float, float]`（返回 point / lower / upper）。用 **block bootstrap**（默认 block_size 按 `sqrt(len)` 或收益自相关长度）尊重收益自相关，不用朴素 iid bootstrap。
- [x] Sharpe 和 annual_return 各算一次 CI，写入 `backtest_result.json` 的 metrics 旁（新增 `metrics_ci` 字段），不改动既有 `metrics`。
- [x] Research note 模板（report 生成技能）改为 `Sharpe 1.42 [95% CI: 0.6, 2.1]` 格式。
- [ ] （加分）Web `ChartsPanel` 相应展示区间——本阶段仅落地数据层 `metrics_ci`，前端展示可留到 Phase_UI 增量。

### 2.6 Golden runs 评测集（本阶段一起建，用来锁定新检查项行为）

Coordinator/Reviewer/Critic 的判断质量目前没有任何回归保障——改一版 prompt、换一代模型、动一个阈值，verdict 可能整体漂移无人察觉。本阶段新增的统计检查尤其需要一组「标准答案」来锁定行为。

**改动**：
- [x] 新增 `tests/fixtures/golden/`：**合成 fixture 数据**（不依赖外部 API），每个含已知标签：
  - `lookahead_factor`：含未来函数（Reviewer lookahead 必须抓到 → REJECTED）
  - `overfit_factor`：参数扰动 / walk-forward 必暴露（DSR 不显著 + 参数不稳 → 封顶）
  - `robust_factor`：稳健经典因子（不应被误杀 → 允许 STRONG/PROMISING）
  - `regime_factor`：单一年份贡献主导（regime 必须 warning）
  - `noise_batch`（20 个纯噪声）：DSR/PBO 必须整批打低
- [x] 新增 `tests/test_phase10_golden_runs.py`：跑 Reviewer + 新统计检查，断言 verdict 与关键 finding severity。
- [x] 纳入 `uv run pytest` 常规套件（合成数据，CI 友好，零外部依赖）。

---

## 三、Reviewer verdict 接入总览

所有新检查通过「注入 finding」接入既有 `determine_verdict`，无特判：

| 检查 | 触发条件 | severity | 对 verdict 的效果 |
|---|---|---|---|
| deflated_sharpe | DSR 不显著（<0.95）且 N>1 | warning | 封顶 PROMISING（不给 STRONG）|
| deflated_sharpe | N≤1 或样本不足 | info | 无（不误伤单 run 研究）|
| pbo_batch | 批 PBO > 0.5 | warning | 该批每个候选封顶 PROMISING |
| walk_forward | 半数以上窗口 OOS 为负 | warning | 封顶 PROMISING |
| walk_forward | 窗口不足 | info | 无 |

多条 warning 叠加自然可触发 WEAK（≥3 warning），与既有语义一致。**不引入新的 verdict 等级，不改 `determine_verdict` 的阈值逻辑本身**——只是给它更多 finding。

---

## 四、阶段内落地顺序

1. **试验次数记账（2.1）** — DSR 的输入，先行。批内 N 优先，跨历史 N 增量。
2. **DSR（2.2）+ verdict 接入** — 本阶段核心收益，独立可测。
3. **Golden runs（2.6）** — 与 2.2 并行建立，用 noise_batch 锁定 DSR 行为。
4. **PBO（2.3）** — 批级，依赖 2.1 的收益矩阵拼装。
5. **Walk-forward（2.4，不含 CPCV）** — 独立于 DSR/PBO，可并行开发。
6. **Bootstrap CI（2.5）+ note 模板** — 收尾，低风险。
7. **CPCV/purge（2.4.1）** — 已在 Phase 10.5 落地，见 [PHASE10_STATS_FOLLOWUP.md](PHASE10_STATS_FOLLOWUP.md)。

每步都是「纯计算模块 + 有测试 + 通过 finding 接 Reviewer」，互相解耦，任一步不阻塞其余。

---

## 五、明确不做（本阶段边界）

- **不改 `determine_verdict` 的阈值本身**（≥3 warning→WEAK 等）——那是 Phase 2 标注的「待校准估计值」，校准是独立议题，本阶段只喂它更多 finding。
- **不做贝叶斯 / 因子模型级的显著性**（IC 的 Newey-West t 统计已在 Phase 10.5 落地；更复杂的显著性模型仍不做）。
- **不引入新依赖**——DSR/PBO/bootstrap/walk-forward 均可用 numpy/scipy/pandas 现有栈实现（scipy 已在依赖内，见 [pyproject.toml](pyproject.toml)）。若 DSR 的正态分位数需要，用 `scipy.stats.norm`。
- **不做远程/并行加速**（GAP 4.6）——CPCV/bootstrap 抬升算量，但本阶段规模本地单机可承受；性能问题留到真正成为瓶颈时。

---

## 六、验证

- `uv run pytest tests/test_phase10_golden_runs.py -q`：golden set 全部命中预期 verdict / finding。
- 单元测试（`tests/test_phase10_statistics.py`）：
  - DSR：N=1 退化为普通显著性；N 增大时同一 Sharpe 的 deflated 值单调下降；已知 fixture 对拍 López de Prado 论文数值。
  - PBO：全同配置 → PBO≈0.5；一个明显占优配置 → PBO 低；纯噪声批 → PBO 高。
  - Walk-forward：窗口切分覆盖全样本、无重叠泄漏；分布统计正确。
  - Bootstrap：CI 覆盖 point estimate；block bootstrap 对自相关序列给出比 iid 更宽的区间。
- 全量 `uv run pytest -q`：新增测试全过，既有测试零回归（新检查对既有单 run 测试默认 `n_trials=1` → info，不改变既有 verdict）。
- 手动端到端：对真实 S&P 500 universe 跑一批 10 个动量/反转候选 `screen_factors`，确认 `factor_screen_summary.json` 每条候选带 DSR 列、顶层带 `effective_trials` 和 `pbo`，且 DSR 不显著的候选 verdict 被封顶。

---

*落地后将本文件各项标记完成，并把「统计护栏已具备」写回 [README.md](README.md) 能力清单与 [GAP_ANALYSIS.md](GAP_ANALYSIS.md) 第二章的对应勾选项。*

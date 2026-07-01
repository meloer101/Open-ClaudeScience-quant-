# Phase 0 详细实施计划：骨架闭环

> 对应 [VISION.md](VISION.md) 第七节 Phase 0
> 目标：**7 个工作日内**，跑通"一句话 → 自动研究 → 可复现 artifact"的最小闭环
> 范围严格锁定：**单因子、单标的、单 timeframe、无审查、无 UI**

---

## 一、Phase 0 的验收标准（先定终点）

```
$ python -m quantbench "测试 RSI(14) 反转因子在 BTC/USDT 4h 上的表现，2023-01-01 到 2026-06-01"
```

系统必须自动完成，无需人工干预（除非缺参数需要追问）：

1. 解析意图 → 生成结构化研究计划
2. 拉取 BTC/USDT 4h OHLCV 数据（本地缓存优先，否则调 CCXT）
3. 计算 RSI(14) 信号
4. 用向量化回测跑出 top/bottom 分组策略
5. 计算核心指标：Sharpe、年化收益、最大回撤、换手率、IC
6. 生成图表：equity curve、drawdown
7. 生成 research note（Markdown）
8. 把本次 run 的所有产物存到 `runs/run_<timestamp>_<id>/` 目录，包含：
   - `config.yaml`（本次 run 的完整参数快照）
   - `signal.py`（生成信号的实际代码，可独立重跑）
   - `backtest_result.json`（结构化指标）
   - `equity_curve.png`, `drawdown.png`
   - `research_note.md`
   - `manifest.json`（数据版本 hash、代码 hash、执行时间、模型调用日志）
9. 终端打印摘要 + artifact 目录路径

**Definition of Done：** 同一条命令跑两次，第二次因为数据已缓存应明显更快；把 `runs/` 目录下某次的 `signal.py` 单独拿出来能独立执行并得到一致结果（这就是"可复现"的最低验收）。

---

## 二、明确不做的事（Phase 0 边界）

| 不做 | 留到哪个 Phase |
|---|---|
| Reviewer Agent（过拟合/未来函数检查） | Phase 2 |
| 多标的 universe 构建 | Phase 1 |
| DuckDB（Phase 0 直接用 Parquet + pandas） | Phase 1 |
| Docker 沙箱执行（Phase 0 直接本地 subprocess/exec） | 后续视安全需求 |
| Web UI / Streamlit（Phase 0 纯 CLI） | Phase 4 |
| 实验库检索/对比（Phase 0 只落盘，不做检索） | Phase 3 |
| 多 agent 协作（Phase 0 只有一个 Coordinator） | Phase 5 |
| Session forking | Phase 3 |
| 手续费敏感性分析等审查项 | Phase 2 |

**红线：任何一个功能想加进来，先问"Phase 0 的验收标准需要它吗？"不需要就不做。**

---

## 三、项目结构

```
quantbench/
├── VISION.md
├── PHASE0.md
├── pyproject.toml              # 依赖: litellm, ccxt, pandas, pyarrow, matplotlib, pyyaml, click
├── .env.example                 # DEEPSEEK_API_KEY=...
├── quantbench/
│   ├── __init__.py
│   ├── cli.py                   # 入口：python -m quantbench "自然语言请求"
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── coordinator.py       # 核心 agent loop（tool use 循环）
│   │   ├── llm.py                # LiteLLM 封装，统一 chat() 接口
│   │   └── prompts.py            # System prompt 模板
│   ├── skills/
│   │   ├── __init__.py
│   │   ├── registry.py          # @skill 装饰器 + 工具schema自动生成
│   │   ├── data_fetch.py        # fetch_ohlcv skill
│   │   ├── signal.py             # compute_signal skill（写因子代码并执行）
│   │   ├── backtest.py           # run_backtest skill
│   │   ├── report.py             # generate_research_note skill
│   │   └── plot.py               # 图表生成
│   ├── data/
│   │   ├── __init__.py
│   │   ├── exchange.py           # CCXT 封装
│   │   └── cache.py               # 本地 Parquet 缓存 + hash
│   ├── engine/
│   │   ├── __init__.py
│   │   ├── vectorized_backtest.py # 向量化回测核心
│   │   └── metrics.py             # Sharpe/回撤/IC/换手率计算
│   ├── artifact/
│   │   ├── __init__.py
│   │   └── store.py               # Run 目录创建、manifest 写入
│   └── config.py                  # 全局配置（模型名、缓存路径等）
├── data_cache/                    # OHLCV parquet 缓存（gitignore）
└── runs/                          # 每次 run 的 artifact（gitignore）
    └── run_20260701_143022_a1b2/
        ├── config.yaml
        ├── signal.py
        ├── backtest_result.json
        ├── equity_curve.png
        ├── drawdown.png
        ├── research_note.md
        └── manifest.json
```

---

## 四、核心模块设计

### 4.1 Agent Loop（`agent/coordinator.py`）

不用框架，纯手写 tool-use 循环：

```python
class Coordinator:
    def __init__(self, llm, skills: SkillRegistry, run_store: ArtifactStore):
        ...

    def run(self, user_request: str) -> RunResult:
        messages = [{"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_request}]
        run = self.run_store.create_run()

        for step in range(MAX_STEPS):  # 上限 12 步，防止死循环
            response = self.llm.chat(messages, tools=self.skills.schemas())
            run.log_llm_call(messages, response)

            if response.tool_calls:
                for call in response.tool_calls:
                    result = self.skills.execute(call.name, call.args, run)
                    messages.append(tool_result_message(call, result))
            else:
                # 模型没有调用工具，说明它认为任务完成或需要追问
                messages.append(response.message)
                if self._is_final_answer(response):
                    break

        run.finalize()
        return run.result
```

**关键设计点：**
- `MAX_STEPS` 硬上限，防止死循环烧 token
- 每一步的 LLM 调用（prompt + response）都记录到 `manifest.json`，这本身就是"可审计"的一部分
- 工具执行失败要把错误信息喂回给模型，让它自己重试/调整，而不是直接崩溃

### 4.2 Skill Registry（`skills/registry.py`）

用装饰器自动生成 OpenAI-style tool schema（LiteLLM 通用格式）：

```python
@skill(
    name="fetch_ohlcv",
    description="拉取指定交易对的 OHLCV 数据，优先使用本地缓存",
)
def fetch_ohlcv(symbol: str, timeframe: str, start: str, end: str) -> str:
    """返回值：数据文件路径 + 基本统计信息（行数、缺失率、时间范围）"""
    ...

@skill(name="compute_signal", description="编写并执行一段因子计算代码")
def compute_signal(code: str, data_path: str) -> str:
    """
    code: 用户/模型生成的 Python 代码字符串，必须定义 compute(df) -> pd.Series
    执行方式：exec 到隔离命名空间，捕获异常喂回模型
    """
    ...

@skill(name="run_backtest", description="对信号跑向量化回测")
def run_backtest(signal_path: str, data_path: str, config: dict) -> str:
    ...

@skill(name="save_artifact", description="将当前分析步骤的产物保存到 run 目录")
def save_artifact(filename: str, content: str) -> str:
    ...
```

**Phase 0 只需要 5 个 skill：** `fetch_ohlcv`, `compute_signal`, `run_backtest`, `plot_results`, `write_research_note`。

### 4.3 数据层（`data/exchange.py` + `data/cache.py`）

Phase 0 极简版，不做 universe，只做单标的。数据源通过 provider 抽象接入：

- `data/providers/ccxt_binance.py`：crypto pair（如 `BTC/USDT`）默认走 Binance/CCXT
- `data/providers/yfinance_equity.py`：美股 ticker（如 `AAPL`、`MSFT`、`SPY`）默认走 yfinance
- 上层统一调用 `fetch_ohlcv(symbol, timeframe, start, end)`，不关心底层 provider
- 美股建议默认使用 `1d`；yfinance 分钟级历史通常只有近 60 天，长区间回测不稳定

```python
def fetch_ohlcv(symbol="BTC/USDT", timeframe="4h", start=..., end=...) -> pd.DataFrame:
    provider = select_provider(symbol)
    cache_key = f"{provider}_{symbol}_{timeframe}_{start}_{end}"
    cache_path = CACHE_DIR / f"{hash(cache_key)}.parquet"
    if cache_path.exists():
        return pd.read_parquet(cache_path)

    df = provider.fetch_ohlcv(symbol, timeframe, start, end)
    df = normalize(df)  # 统一 schema: timestamp(UTC), open, high, low, close, volume
    df.to_parquet(cache_path)
    return df
```

**数据 schema 锁死（为 Phase 1 铺路）：**

```python
COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]
# timestamp: pandas UTC-aware datetime64
```

### 4.4 回测引擎（`engine/vectorized_backtest.py`）

Phase 0 只支持最简单的策略形式：**信号排序 → 等权 top/bottom 分组 → 按周期调仓**，不做真实订单模拟：

```python
def run_vectorized_backtest(
    price_df: pd.DataFrame,
    signal: pd.Series,
    rebalance_freq: str,       # e.g. "1D"
    cost_bps: float,           # 双边手续费+滑点，单位 bps
    method: str = "long_short_decile",
) -> BacktestResult:
    """
    单标的场景下 Phase 0 简化为: 
    signal 高于历史分位数 -> 做多；低于 -> 做空/空仓
    这是"单标的时序策略"而不是"截面分层"（截面分层要多标的，留给 Phase 1）
    """
    forward_returns = price_df["close"].pct_change().shift(-1)
    position = derive_position(signal, method)
    gross_returns = position.shift(1) * forward_returns
    turnover = position.diff().abs()
    net_returns = gross_returns - turnover * cost_bps / 10000

    return BacktestResult(
        returns=net_returns,
        sharpe=annualized_sharpe(net_returns, periods_per_year=...),
        max_drawdown=compute_max_drawdown(net_returns),
        annual_return=annualize(net_returns),
        turnover_annual=turnover.sum() * periods_per_year_factor,
        ic=compute_ic(signal, forward_returns),
    )
```

**注意：** Phase 0 是单标的时序回测，不是截面因子分层（那需要 universe，属于 Phase 1）。这个简化要在 VISION.md 的 Phase 1 验收里明确"从时序策略升级为截面因子分析"。

### 4.5 Artifact Store（`artifact/store.py`）

```python
class ArtifactStore:
    def create_run(self) -> Run:
        run_id = f"run_{timestamp()}_{short_uuid()}"
        run_dir = RUNS_DIR / run_id
        run_dir.mkdir(parents=True)
        return Run(run_id, run_dir)

class Run:
    def save_config(self, config: dict): ...      # config.yaml
    def save_code(self, filename: str, code: str): ...  # signal.py 等
    def save_result(self, result: BacktestResult): ...  # backtest_result.json
    def save_plot(self, filename: str, fig): ...
    def log_llm_call(self, messages, response): ...  # 累积写入 manifest.json 的 llm_log
    def finalize(self):
        # 写入 manifest.json: 
        #   - data_hash (输入数据的 hash)
        #   - code_hash (signal.py 的 hash)
        #   - created_at, duration_seconds
        #   - llm_calls (每一步的模型调用记录，脱敏后的 prompt+response 摘要)
        #   - model_name, model_provider
```

**`manifest.json` 示例：**

```json
{
  "run_id": "run_20260701_143022_a1b2",
  "user_request": "测试 RSI(14) 反转因子在 BTC/USDT 4h 上的表现",
  "created_at": "2026-07-01T14:30:22Z",
  "duration_seconds": 47.3,
  "model": "deepseek/deepseek-chat",
  "data_hash": "sha256:9f8e...",
  "code_hash": "sha256:1a2b...",
  "steps": [
    {"tool": "fetch_ohlcv", "args": {...}, "duration_ms": 1200},
    {"tool": "compute_signal", "args": {...}, "duration_ms": 340},
    {"tool": "run_backtest", "args": {...}, "duration_ms": 89},
    {"tool": "write_research_note", "args": {...}, "duration_ms": 2100}
  ]
}
```

---

## 五、Research Note 模板（Phase 0 简化版）

```markdown
# Research Note: RSI(14) Reversal on BTC/USDT 4h

**Run ID:** run_20260701_143022_a1b2
**Date:** 2026-07-01
**Hypothesis:** RSI(14) 反转因子在 BTC/USDT 4h 上有预测力

## 配置
- 标的: BTC/USDT (Binance Perpetual)
- 周期: 4h
- 区间: 2023-01-01 ~ 2026-06-01
- 手续费假设: 5bps 双边

## 结果
| 指标 | 数值 |
|---|---|
| Sharpe | 1.12 |
| 年化收益 | 14.2% |
| 最大回撤 | -18.3% |
| 年化换手率 | 32.1x |
| IC (mean) | 0.024 |

## 图表
![equity curve](equity_curve.png)
![drawdown](drawdown.png)

## 局限性声明（Phase 0 尚未做审查）
⚠️ 本报告未经过 Reviewer Agent 审查（该功能在 Phase 2 实现）。
以下问题**尚未检查**，解读结果时需自行注意：
- 是否存在未来函数
- 样本外表现是否衰减
- 手续费敏感性
- 是否依赖极端行情（如单边牛市）

## 代码
完整可复现代码见 `signal.py`，数据版本 hash: `9f8e...`
```

**这个"局限性声明"很重要** —— 它诚实地告诉用户 Phase 0 还不能自动把关质量，避免用户对着一个 Sharpe 1.12 就冲进市场。这也是和最终版本的差异点，写进报告本身，形成清晰的产品成长记录。

---

## 六、按日拆解（7 个工作日）

| Day | 任务 | 产出 |
|---|---|---|
| **Day 1** | 项目骨架 + LiteLLM/DeepSeek 打通 | `cli.py` 能对话，`llm.py` 能拿到 tool_calls |
| **Day 2** | Skill Registry + `fetch_ohlcv` | 能自然语言触发 CCXT 拉数据并缓存为 parquet |
| **Day 3** | `compute_signal`（代码生成+执行）| 模型生成的因子代码能安全执行并返回信号序列 |
| **Day 4** | 向量化回测引擎 + 核心指标 | `run_backtest` 跑出 Sharpe/回撤/换手率/IC |
| **Day 5** | 图表生成 + Artifact Store | equity curve/drawdown 落盘，`manifest.json` 完整 |
| **Day 6** | Research Note 生成 + 端到端联调 | 完整跑通验收标准里的那条命令 |
| **Day 7** | 打磨 + 边界情况处理 + 复现验证 | 独立重跑 `signal.py` 验证结果一致；处理常见报错（网络失败、模型输出格式错误等） |

---

## 七、关键技术决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| 代码执行方式 | Phase 0 用 `exec()` + 受限命名空间，不上 Docker | 先跑通闭环，Docker 沙箱是安全加固，不影响功能验收；但要在 `compute_signal` 里限制可导入的模块（只允许 pandas/numpy） |
| 信号定义方式 | 模型直接生成 Python 代码字符串（而非 DSL） | 灵活度最高，符合"研究者会写代码"的定位；DSL 是过度设计 |
| 单标的 vs 截面 | Phase 0 只做单标的时序策略 | 截面分层需要 universe 概念，是 Phase 1 的核心工作，Phase 0 强行做会把两个 Phase 的复杂度叠在一起 |
| 工具调用格式 | 依赖 LiteLLM 统一的 OpenAI tool-calling 格式 | DeepSeek 原生支持该格式，无需额外适配层 |
| 错误处理 | 工具执行异常捕获后作为 tool_result 喂回模型，而非抛出 | 让模型有机会自我纠正（比如因子代码有语法错误时重写） |
| MAX_STEPS | 12 | 防止死循环；Phase 0 场景正常应在 5-8 步完成 |

---

## 八、风险与应对

| 风险 | 应对 |
|---|---|
| DeepSeek tool-calling 格式偶尔不稳定 | 在 `llm.py` 里做一层重试 + 格式校验，失败时退化为纯文本解析 |
| CCXT 拉取历史数据慢（分页限制） | Day 2 就做好本地缓存，避免每次调试都重新拉取 |
| 模型生成的因子代码有 bug | `compute_signal` 执行失败时把 traceback 完整返回给模型，让它自己修 |
| exec() 执行任意代码的安全性 | Phase 0 仅限本地个人使用，做基础的 import 白名单即可，不做进程隔离（留给后续沙箱化工作） |

---

## 九、Phase 0 完成后的检查清单

- [ ] 验收命令跑通，产出完整 artifact 目录
- [ ] 独立重跑某次 run 的 `signal.py`，结果与 `backtest_result.json` 一致
- [ ] `manifest.json` 完整记录所有 LLM 调用和工具调用
- [ ] 第二次跑相同请求时数据缓存命中，明显加速
- [ ] research_note.md 内容准确、诚实标注局限性
- [ ] 回顾 VISION.md，确认 Phase 1 的优先级仍然成立（数据层 > Reviewer）

---

*完成 Phase 0 后，回到 [VISION.md](VISION.md) 更新 Phase 1 计划，并视实际情况调整后续时间估算。*

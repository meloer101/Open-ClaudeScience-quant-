# Phase 1 详细实施计划：美股 Universe 数据层

> 对应 [VISION.md](VISION.md) 第七节 Phase 1（原计划以 crypto perpetual 为主，本轮改为美股优先）
> 前置条件：[PHASE0.md](PHASE0.md) 已完成 —— 单标的、单信号、LLM 驱动的可复现闭环已跑通
> 目标：从"单标的时序策略"升级到"多标的截面因子分析"，并把数据层从"一个 parquet 文件"升级成"可查询的数据仓库"

---

## 一、为什么换成美股、为什么现在做这件事

1. **Binance 在美国被地区封锁**，Phase 0 里 crypto 的"真实数据"验证长期只能靠合成 fallback，没法真正验证数据质量问题。美股用 yfinance 在这个环境下能拿到真实数据，能让 Phase 1 的每一项工作都在真实数据上验证，而不是靠猜测。
2. Phase 0 的回测引擎目前是"单标的时序策略"（一个信号在一个标的上做多空），这只是 VISION.md 里"研究闭环"的一个简化角落。量化研究真正的日常形态是**截面因子分析**：在一批标的里，每个时间点计算所有标的的因子值，排序分组，构建多空组合。这是 Phase 1 必须补上的核心能力，不管资产类别是什么。
3. 之后要扩展到 A 股、期货，"universe 构建 + 截面回测 + 数据质量校验"这套骨架是资产类别无关的，现在用美股练手成本最低（免费数据、无地区限制、Wikipedia/公开信息就能拿到成分股变更历史）。

---

## 二、Phase 1 要交付什么（先定终点）

**验收命令：**

```
$ python -m quantbench "在标普500成分股里测试20日动量因子的表现，2018-01-01 到 2024-01-01，等权十分位多空组合"
```

系统必须自动完成：

1. 构建 universe（标普 500 成分股列表，标注是否为 point-in-time 或当前成分股投影）
2. 批量拉取/缓存这批标的的日线 OHLCV（DuckDB 管理，不是逐个 parquet 手动拼）
3. 数据质量校验：缺失值、停牌、退市/被收购标的的处理方式、除权除息一致性
4. 对每个标的计算因子值（模型生成的 `compute(df) -> pd.Series`，和 Phase 0 一样）
5. **按时间截面**把所有标的的因子值排序，分成十分位，构建多空组合（做多因子值最高的十分位，做空最低的十分位）
6. 计算组合级别指标：Sharpe、年化收益、最大回撤、换手率、**截面 IC/Rank IC**、**分层单调性**（十分位收益是否单调递增）
7. 生成图表：组合净值曲线、分层收益柱状图、IC 时序图
8. 生成 research note，包含 universe 定义、数据质量报告、截面回测结果
9. artifact 归档，`universe.yaml` 作为新增的一类可复现产物

**Definition of Done：** 同一个 universe 定义第二次跑应该命中缓存（不重新拉取全部成分股数据）；`signal.py` 依然可以独立对单个标的的数据复现验证；数据质量报告里能看到"这批标的里有多少缺失/停牌/退市"的诚实统计,而不是静默跳过。

---

## 三、明确不做的事（Phase 1 边界）

| 不做 | 留到哪个 Phase |
|---|---|
| 真正的 point-in-time 历史成分股变更（Phase 1 用当前成分股列表，明确标注生存者偏差风险） | Phase 1 的 stretch goal 或 Phase 2 |
| Reviewer Agent 检查过拟合/未来函数 | Phase 2（Phase 1 只做数据层的质量校验，不做策略层的审查） |
| 组合优化（风险模型、约束优化） | Phase 5 |
| A 股、期货、期权 | Phase 1 之后视情况 |
| 基本面因子（PE、ROE 等） | 明确排除，VISION.md 定的边界，专注量价 |
| Web UI | Phase 4 |
| 全市场（3000+ 标的）覆盖 | 先做标普 500（500 支），验证跑通再考虑扩展 |

**红线不变：任何功能想加进来，先问"验收命令需要它吗"。**

---

## 四、项目结构变化

```
quantbench/
├── data/
│   ├── cache.py                    # 改造：从"单文件 parquet"变成"DuckDB 视图管理"
│   ├── exchange.py                 # 保留，单标的 fetch 逻辑不变
│   ├── warehouse.py                 # 新增：DuckDB 连接、批量写入、跨标的查询
│   ├── universe.py                  # 新增：universe 构建、成分股列表、生存者偏差标注
│   └── providers/
│       ├── base.py
│       ├── ccxt_binance.py
│       ├── yfinance_equity.py
│       └── sp500_constituents.py    # 新增：标普 500 成分股列表来源
├── engine/
│   ├── vectorized_backtest.py       # 保留（单标的场景仍用得到）
│   ├── cross_sectional_backtest.py  # 新增：截面因子回测核心
│   └── metrics.py                   # 扩展：加截面 IC、分层单调性等指标
├── skills/
│   ├── codeexec.py                  # 保留
│   ├── universe_builder.py          # 新增：build_universe skill
│   ├── data_quality.py               # 新增：数据质量校验 skill
│   └── report.py                     # 扩展：支持截面回测的 research note 模板
└── agent/
    ├── coordinator.py                # 扩展：新增 build_universe / run_cross_sectional_backtest 工具
    └── prompts.py                    # 扩展：教模型什么时候用截面回测 vs 单标的回测
```

---

## 五、核心模块设计

### 5.1 Universe 构建（`data/universe.py` + `providers/sp500_constituents.py`）

Phase 1 第一版用**当前标普 500 成分股列表**（来源：Wikipedia 的 `List_of_S%26P_500_companies` 页面，有公开维护的成分股表格，包含"何时被剔除/加入"的变更历史表，可以直接解析）。

```python
@dataclass(frozen=True)
class UniverseDefinition:
    name: str
    as_of_date: str
    symbols: list[str]
    point_in_time: bool          # False = 用当前成分股反推历史，有生存者偏差
    survivorship_bias_note: str
    source: str


def build_sp500_universe(as_of_date: str, point_in_time: bool = False) -> UniverseDefinition:
    """Phase 1 v1: point_in_time=False，即用当前成分股列表整段回测。
    生存者偏差是真实存在的已知限制，必须写进 warnings，不能假装没有这个问题。
    """
```

**诚实声明（对应 VISION.md 的"数据污染"担忧）：** 用当前成分股做历史回测，会漏掉那些"曾经在标普 500 里、后来因为表现差被剔除"的公司——这会让回测结果系统性偏乐观。Phase 1 v1 不解决这个问题，但要在 `universe.yaml` 和 research note 里**显著标注**，而不是当作"数据已经很完整"来呈现。如果时间允许，会做一个 stretch goal：从 Wikipedia 变更历史表解析出 point-in-time 成分股，把 `point_in_time` 设为 `True`。

### 5.2 数据仓库（`data/warehouse.py`）

Phase 0 是"一个 symbol 一个 parquet 文件，Python 里 `pd.read_parquet` 逐个读"。Phase 1 需要跨几百个标的做批量拉取、批量查询、跨标的对齐时间戳——这正是 DuckDB 的用武之地。

```python
import duckdb

def get_connection(db_path: Path) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(db_path))


def upsert_ohlcv(conn, symbol: str, df: pd.DataFrame) -> None:
    """写入/更新单个标的的 OHLCV，去重按 (symbol, timestamp) 主键。"""


def query_universe_ohlcv(conn, symbols: list[str], start: str, end: str) -> pd.DataFrame:
    """一次查询返回整个 universe 在 [start, end] 区间的长表 (symbol, timestamp, ohlcv...)，
    截面回测引擎直接消费这个长表。"""
```

**设计决策：** 不用 DuckDB 替换 Phase 0 已经跑通的单 parquet 缓存机制（`fetch_ohlcv` 保持不变），而是在其上加一层：universe 场景下，`fetch_universe_ohlcv` 循环调用现有的 `fetch_ohlcv`（每个标的仍然走 parquet 缓存+ provider 分发），拉回来的数据统一写入一个 DuckDB 表，供截面查询用。这样单标的场景（Phase 0 的所有测试和逻辑）完全不受影响，DuckDB 是纯增量能力。

### 5.3 截面因子回测引擎（`engine/cross_sectional_backtest.py`）

这是 Phase 1 最大的一块新代码。核心逻辑：

```python
def run_cross_sectional_backtest(
    panel: pd.DataFrame,      # 长表：columns = [timestamp, symbol, open, high, low, close, volume]
    compute_factor: Callable[[pd.DataFrame], pd.Series],  # 对单标的子表算因子，和 Phase 0 的 compute() 签名一致
    n_groups: int = 10,
    cost_bps: float = 5.0,
    rebalance: str = "1D",
) -> CrossSectionalBacktestResult:
    """
    1. 按 symbol groupby，对每个标的的时间序列跑 compute_factor，得到 (timestamp, symbol, factor_value) 长表
    2. 按 timestamp 分组，每个截面上把 factor_value 按分位数切成 n_groups 组
    3. 每组等权，做多最高分位、做空最低分位（或者输出全部分位的收益用于单调性检验）
    4. 逐日/逐期计算组合收益，同样用"当期因子值 = 因子值本身已经是因果的 -> 直接乘下一期收益"，
       不再引入 Phase 0 回测引擎里修过的那个 off-by-one 陷阱
    5. 输出：组合净值曲线、分层收益、截面 IC 时序、Rank IC 均值、分层单调性得分
    """
```

**关键正确性设计（直接继承 Phase 0 修复的教训）：**
- 因子计算函数本身必须是因果的（这点和 Phase 0 一样，靠 system prompt 约束 + codeexec 沙箱）
- 组合收益对齐方式复用 Phase 0 验证过的对齐逻辑：`position（本期已知）* forward_return（下一期收益）`，不做多余的滞后
- **单调性检验**是新增的、截面因子分析特有的诊断：如果十分位收益不是从低到高（或高到低）单调，说明因子在整个分布上没有稳定的方向性，这本身就是一个信号质量问题，要在 research note 里体现，不能只看多空组合的 Sharpe 就下结论

### 5.4 数据质量校验（`skills/data_quality.py`）

截面场景下数据质量问题会被放大（500 个标的里总有几个有问题），必须做基本校验，且**校验结果要出现在 research note 里，不能悄悄丢弃有问题的标的**：

```python
@dataclass
class DataQualityReport:
    total_symbols: int
    symbols_with_data: int
    symbols_missing_entirely: list[str]     # 拉取失败/无数据
    symbols_with_gaps: dict[str, int]        # 标的 -> 缺失交易日数量
    symbols_delisted_or_dropped: list[str]   # 期间可能退市/被收购（价格数据在结束日期前中断）
    suspicious_price_jumps: dict[str, list]  # 单日涨跌幅 > 50% 的标的和日期（可能是未处理的拆股）


def validate_universe_data(panel: pd.DataFrame, universe: UniverseDefinition) -> DataQualityReport:
    ...
```

这个报告直接决定了 research note 里要不要加警告——比如"500 支里有 12 支完全拉不到数据，34 支有缺口，回测结果基于剩余 454 支"，这种情况必须显式告诉用户，而不是让分母悄悄变小。

### 5.5 Coordinator / 工具扩展

新增两个工具（保留 Phase 0 的 `fetch_ohlcv` / `run_signal_backtest`，用于单标的场景）：

```python
BUILD_UNIVERSE_PARAMS = {
    "type": "object",
    "properties": {
        "universe_name": {"type": "string", "description": "e.g. sp500"},
        "as_of_date": {"type": "string", "description": "YYYY-MM-DD"},
    },
    "required": ["universe_name", "as_of_date"],
}

RUN_CROSS_SECTIONAL_BACKTEST_PARAMS = {
    "type": "object",
    "properties": {
        "code": {"type": "string", "description": "同 Phase 0，def compute(df) -> pd.Series，逐标的调用"},
        "n_groups": {"type": "integer", "description": "分层数量，默认 10"},
        "cost_bps": {"type": "number"},
        "start": {"type": "string"},
        "end": {"type": "string"},
        "timeframe": {"type": "string", "description": "美股建议 1d"},
    },
    "required": ["code", "start", "end"],
}
```

System prompt 需要教会模型：**什么时候该用单标的回测、什么时候该用截面回测**——用户如果只提了一个标的（"测试 XX 因子在 AAPL 上"），走 Phase 0 老路径；如果提到"一批股票"、"标普 500"、"截面"、"多空组合"这类描述，走新的 universe + 截面回测路径。这是本阶段 prompt 设计的核心难点，需要几轮实测调整措辞。

---

## 六、按日拆解（预计 8-10 个工作日）

| Day | 任务 | 产出 |
|---|---|---|
| **Day 1** | Universe 构建：解析标普 500 成分股列表 | `build_sp500_universe()` 能返回 500 个 symbol + 生存者偏差标注 |
| **Day 2** | DuckDB 数据仓库骨架 | `warehouse.py` 能批量写入/查询多标的 OHLCV |
| **Day 3** | 批量拉取 + 限流处理 | `fetch_universe_ohlcv` 跑通标普 500 全量拉取（预计接口限流是最大风险，需要重试/退避） |
| **Day 4** | 数据质量校验 | `DataQualityReport` 能识别缺失/缺口/可疑跳变，并生成人类可读摘要 |
| **Day 5-6** | 截面回测引擎 | `run_cross_sectional_backtest` 跑通，分层收益、截面 IC、单调性指标都对 |
| **Day 7** | Coordinator 工具扩展 + prompt 调优 | 模型能正确判断走单标的还是截面路径，工具调用链路通 |
| **Day 8** | Research note 模板扩展 + 图表（分层柱状图、IC 时序图） | 截面场景的 research note 完整、诚实 |
| **Day 9** | 端到端联调 + 测试补全 | 验收命令跑通，覆盖数据质量异常场景的测试 |
| **Day 10** | 打磨、复现验证、更新 VISION.md/PHASE0.md 的过时描述 | 收尾 |

---

## 七、关键技术决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| Universe 范围 | 先做标普 500，不做全市场 | 500 支标的用 yfinance 顺序拉取已经有明显耗时，全市场（3000+）会让 Phase 1 的联调周期不可控；跑通再考虑扩展 |
| Point-in-time 成分股 | v1 不做，明确标注生存者偏差 | 完整的历史成分股变更数据获取成本高（免费源有限），先诚实暴露限制，比强行做一个不完整的方案更负责任 |
| DuckDB 的定位 | 只做"多标的查询层"，不替换 Phase 0 的单文件缓存 | 保护已经跑通、有测试覆盖的 Phase 0 路径不受影响，DuckDB 是纯增量能力 |
| 批量拉取的并发策略 | 先用顺序 + 限流重试，不做并发 | yfinance 对并发请求容易触发限流/封禁，Phase 1 优先保证稳定性而不是速度 |
| 截面回测 vs 单标的回测的路由 | 靠 system prompt 让模型判断，不做规则硬编码 | 保持"真正的 agent 决策"这个 Phase 0 定下的架构原则，不要退回正则匹配 |

---

## 八、风险与应对

| 风险 | 应对 |
|---|---|
| yfinance 批量拉取 500 支标的时触发限流/被封 IP | 加指数退避重试；每个标的之间加小延迟；数据质量报告里记录"因限流未能获取"和"数据确实不存在"的区别，不要混为一谈 |
| 标普 500 成分股列表来源（Wikipedia）结构变化导致解析失败 | 解析失败时要明确报错，不能静默返回空列表或者不完整列表进入下游 |
| 截面回测引擎重蹈 Phase 0 的时序对齐 bug | 复用 Phase 0 已验证的对齐范式，并且新写一个类似 `test_backtest_captures_correct_sign_at_signal_transition` 的截面版回归测试 |
| 500 支标的里数据质量参差不齐，导致"回测结果好看"是因为样本偷偷变小 | `DataQualityReport` 强制在 research note 里出现，即使用户没问 |
| 全流程耗时过长（500 支 × LLM 逐个跑因子代码可能很慢） | 因子代码只需要生成一次，对 500 支标的的执行是纯 Python 循环，不需要为每个标的单独调用 LLM——这是设计截面回测工具时要保证的接口形状 |

---

## 九、Phase 1 完成后的检查清单

- [ ] 验收命令跑通，产出包含 `universe.yaml` 的完整 artifact
- [ ] `universe.yaml` 诚实标注生存者偏差（point_in_time=False 的限制）
- [ ] 数据质量报告出现在 research note 里，包含缺失/缺口/可疑跳变统计
- [ ] 截面 IC、分层单调性、分层收益图表都生成且数值合理
- [ ] 同一个 universe 定义第二次跑，批量拉取阶段明显加速（缓存命中）
- [ ] 新增的截面回测引擎有独立的时序对齐回归测试
- [ ] Coordinator 能正确区分"单标的请求"和"截面/universe 请求"并路由到对应工具
- [ ] 回顾 VISION.md，确认 Phase 2（Reviewer Agent）的设计是否需要因为截面场景做调整（比如"因子在全市场 vs 少数股票上是否有效"这类检查，Phase 0 的审查清单里已经列了"标的池选择偏差"，正好用得上 Phase 1 的 universe 基础设施）

---

*完成 Phase 1 后，回到 [VISION.md](VISION.md) 更新 Phase 2 计划。Phase 2 的 Reviewer Agent 将直接消费 Phase 1 产出的截面回测结果和数据质量报告，去做过拟合/未来函数/样本外表现等审查。*

# Phase 5 详细实施计划：多资产支持——补全 crypto 截面研究

> 对应 [VISION.md](VISION.md) 第七节 Phase 5（多资产与高级功能）
> 前置条件：[PHASE0.md](PHASE0.md)～[PHASE4.md](PHASE4.md) 均已完成并合并到 `main`——单标的和截面两条路径都能自动拉数据、跑回测、自动审查、渲染图表、存进实验库。
> 目标：VISION 第七节把 Phase 5 定义成"多资产支持（股票、期货）+ 多 agent 协作 + 自定义 skill + 组合优化 + paper trading + 远程计算"六件事的合集，范围横跨好几个不相关的能力面。这份计划**只做其中一件事**：把 crypto 从"能跑单标的回测但没有截面 universe"补成和股票对等的第二个完整资产类别。其余五项（多 agent、自定义 skill、组合优化、期货、paper trading、远程计算）明确不在这份计划里，理由见第一节和第五节。

---

## 一、先把现状和 VISION 原文的落差摊开——这是这份计划最重要的一步

上一轮（Phase 4）审核时吃过"计划写得漂亮但没对齐真实接口"的亏，这次先把账算清楚，再决定做什么：

**VISION 第七节 Phase 5 清单原文写的是"多资产支持（股票、期货）"——不是 crypto。** 但翻代码会发现一个反直觉的事实：

| 资产类别 | 现状 |
|---|---|
| **股票（equity）** | 完整：`yfinance_equity` provider、`build_sp500_universe`、单标的+截面两条路径、Reviewer 全部检查项都跑过真实数据校准（见 PHASE2.md 第十节） |
| **crypto** | **半成品**：`ccxt_binance` provider 从 Phase 0 起就存在（[data/exchange.py:53](quantbench/data/exchange.py:53) 按 symbol 形状路由，`"/" in symbol` 就走 CCXT），单标的回测能跑；但**从来没有 crypto 版本的 universe builder**——[data/universe.py](quantbench/data/universe.py) 的 `build_universe()` 只认识 `"sp500"`，crypto 截面研究（VISION 4.1 节 research_run 示例本身用的就是 "RSI(14) 反转因子在 BTC/USDT 4h" 这种单标的场景，但 VISION 5.5 节的截面例子"top_80_usdt_perpetual"从未落地） |
| **期货（futures）** | **完全没有**：没有 provider、没有 continuous contract/展期（roll）逻辑、没有任何 futures 相关代码（grep 全仓库为零命中） |

也就是说：VISION 文档点名要做的（期货）在代码里量最大、风险最高（期货需要连续合约展期这种和股票/crypto都不同的新问题，不是"换个 provider"就完事）；代码里已经半成品、复用度最高的（crypto 截面）反而没被点名。

**这份计划的立场：先把 crypto 截面补完，期货明确推迟到未来某个 Phase。** 理由：
1. crypto 补全几乎是纯粹的"接线"工作——`fetch_universe_ohlcv`（[data/warehouse.py:100](quantbench/data/warehouse.py:100)）本身按 symbol 委托给 `fetch_ohlcv`，是资产无关的；`periods_per_year_from_timestamps`（[engine/metrics.py:8](quantbench/engine/metrics.py:8)）的注释显式提到"crypto 4h bars"，说明年化逻辑本来就是按 asset-agnostic 设计的；Reviewer 的 `symbol_concentration`/`regime`/`tail_dependence` 检查全部只依赖收益率序列，不关心资产类别。真正缺的只是一个 `build_universe("top_n_usdt_perpetual", ...)` 入口。
2. 期货需要的展期/连续合约构造是一个和"新增一个 provider"完全不同量级的新问题（历史合约拼接、展期日选择、价格跳变处理），贸然现在做容易重蹈"计划写得漂亮但地基没打"的覆辙。
3. 审核过程中还发现两个**必须在做 crypto 截面之前修的真实 bug**（见第四节 4.2/4.3），如果不修，crypto 截面跑出来的 Reviewer 结论是错的——这比"要不要做期货"更紧急。

---

## 二、为什么现在做，以及和"模型写什么代码写什么"准则的关系

VISION 第十一节的准则在这里同样适用：universe 构建、benchmark 路由、资产分类都是"必须绝对正确"的确定性代码，不是模型判断的对象。具体到本 Phase：

- **crypto universe 的"按成交量选 top N"是确定性排序**，不是模型现场决定"这些币看起来有代表性"；
- **cross-sectional 场景下 benchmark 该用 SPY 还是 BTC/USDT，是根据 universe 的资产类别机械决定的**（第四节 4.2 会修一个这里的真实 bug——现在无论 universe 是什么资产，截面路径的 benchmark 永远硬编码成 SPY）；
- **crypto 永续合约的 funding rate 结转成本没有被建模，这是一个已知的正确性缺口**，Phase 5 不打算完整实现 funding-adjusted PnL（工作量大、需要新数据源），但必须让系统**诚实地说出这个缺口**（一条自动 warning），而不是让回测结果看起来完整可信却悄悄漏掉一块真实成本——这正是 VISION 反复强调的"结果好看不等于结果可信"。

---

## 三、验收标准（先定终点）

**验收命令（新增一条 crypto 截面命令，复用已有的两条equity验收命令做回归）：**

```
$ python -m quantbench "构建 top 30 USDT 永续合约的截面 universe，测试20日动量因子的截面表现，2023-01-01到2024-12-31，等权十分位多空组合"
$ python -m quantbench "测试20日动量因子在AAPL上的表现，2018-01-01到2024-01-01"                          # 回归：equity 单标的
$ python -m quantbench "在标普500成分股里测试20日动量因子的截面表现，2022-01-01 到 2024-12-31，等权十分位多空组合"  # 回归：equity 截面
```

系统必须在第一条命令里自动完成：
1. 构建一个"当前按 24h 成交量排名前 30 的 USDT 永续合约"universe，带上和 sp500 universe 同等级别的诚实声明（不是 point-in-time、排名是查询时刻的快照）
2. 走现有的 `fetch_universe_ohlcv` 拉数据、`run_cross_sectional_backtest` 跑回测——不需要新的回测引擎代码
3. Reviewer 的 `beta_exposure` 检查必须对 BTC/USDT 而不是 SPY 算 beta（第四节 4.2 的 bug 修复验证点）
4. `manifest.json`/`review_report.json`/`research_note.md` 里必须出现一条关于 funding rate 成本未建模的警告（第四节 4.3）
5. `library.record.build_record` 对这个 run 的 `asset_class` 分类必须是 `"crypto"`、`cross_sectional` 必须是 `True`（复用 Phase 3 已有的实验库分类逻辑，不需要新代码——用来验证第四节 4.1 的 `UniverseDefinition.asset_class` 字段确实接上了）

两条 equity 验收命令必须原样跑通，证明 universe 分发逻辑的改动没有破坏已有路径。

### 正确性测试场景

- **成交量排序确定性**：给定一组 mock 的 ccxt ticker 数据，`build_crypto_perpetual_universe` 选出的 top N 必须严格按 24h quote volume 降序，且过滤掉非 USDT 计价、非 swap 类型、非 active 状态的市场——用假数据断言，不依赖真实网络。
- **benchmark 路由回归**：一个 equity 截面 run 的 beta_exposure 必须仍然用 SPY（不能因为改了路由逻辑而误伤 equity 场景）；一个 crypto 截面 run 必须用 BTC/USDT。

---

## 四、模块拆解

### 4.1 `UniverseDefinition` 新增 `asset_class` 字段——这是本 Phase 唯一的数据模型改动

```python
@dataclass(frozen=True)
class UniverseDefinition:
    name: str
    as_of_date: str
    symbols: list[str]
    point_in_time: bool
    survivorship_bias_note: str
    source: str
    sample_limit: int | None = None
    asset_class: str = "equity"   # 新增，向后兼容默认值
```

**为什么加这个字段而不是在用到的地方现场用字符串猜（比如判断 `"/" in symbols[0]`）**：`library/record.py` 的 `_classify_asset` 已经在用"猜"的方式做资产分类（这是 Phase 3 里为了不引入模型判断而接受的 v1 局限，见 PHASE3.md 技术决策）——但那是**只读展示层**在事后猜测，猜错了顶多是实验库标签不准。这里的 `asset_class` 要**驱动 benchmark 路由这种影响 Reviewer 结论的决策**，不能靠字符串猜测这种脆弱的方式，必须是 universe 构建时就确定性写死的字段，源头正确。

### 4.2 修复：cross-sectional 路径的 benchmark 硬编码成 SPY（真实 bug，不是新功能）

现状（[agent/coordinator.py:336](quantbench/agent/coordinator.py:336)）：

```python
benchmark_returns=_fetch_benchmark_returns({"symbol": "SPY", "timeframe": timeframe, "start": start, "end": end}, None),
```

不管 universe 是什么资产，截面场景的 beta_exposure 检查永远算"多空组合收益 vs SPY"的 beta。单标的路径（[coordinator.py:247](quantbench/agent/coordinator.py:247) + [`_fetch_benchmark_returns`](quantbench/agent/coordinator.py:802)）已经会按 symbol 形状路由到 BTC/USDT，只有截面路径漏了这一步——这是纯粹的疏漏，不是"crypto 截面从来没跑过所以没人发现"的功能缺失。

修复：让 `_run_cross_sectional_backtest` 用 `ctx.universe.asset_class` 决定 benchmark symbol（`"crypto"` → `"BTC/USDT"`，否则 `"SPY"`），而不是硬编码。

### 4.3 新增：crypto 永续合约 funding rate 成本未建模——自动 warning，不是完整建模

`quantbench/review/report.py` 或 `agent/coordinator.py` 增加一个确定性检查：只要本次 run 交易的是 crypto 永续合约（`ctx.universe.asset_class == "crypto"` 或单标的场景 symbol 含 `/`），无条件在 `warnings` 里追加一条：

```
"Crypto perpetual backtests do not model funding rate carry cost. Long-short "
"positions held across funding intervals may have systematically biased PnL "
"that this backtest does not capture."
```

这条 warning 复用现有的"warnings 不能被模型省略或淡化"约束（`prompts.py` 已有的强约束模式，Phase 2 时就是这么处理 Reviewer verdict 的）。**明确不做**完整的 funding-adjusted 回测（需要新的数据源 `fetch_funding_rate` + 回测引擎改动去把 funding 计入每期收益）——这是诚实标注缺口，不是修复缺口，完整实现留给未来需要真实 crypto 永续策略上线时再做。

### 4.4 新增 `quantbench/data/providers/ccxt_binance.py`: `fetch_top_symbols_by_volume`

```python
def fetch_top_symbols_by_volume(quote: str = "USDT", limit: int = 30) -> list[dict]:
    """Current top-`limit` USDT-margined perpetual swap markets on Binance by
    24h quote volume, active markets only. Returns [{"symbol": ..., "quote_volume_24h": ...}, ...]."""
```

用 `ccxt.binance({"options": {"defaultType": "swap"}})` 的 `fetch_tickers()` 拿到全部 ticker（含 `quoteVolume`），过滤 `market["active"]` 且计价货币匹配 `quote` 且 `market["swap"]`，按 `quoteVolume` 降序取前 `limit` 个。**确定性排序，不涉及任何判断力**，符合"代码写"边界。

### 4.5 新增 `quantbench/data/universe.py`: `build_crypto_perpetual_universe`

```python
def build_crypto_perpetual_universe(as_of_date: str, limit: int = 30) -> UniverseDefinition:
    ...
    return UniverseDefinition(
        name="top_usdt_perpetual",
        as_of_date=as_of_date,
        symbols=[t["symbol"] for t in top],
        point_in_time=False,
        survivorship_bias_note=CRYPTO_UNIVERSE_NOTE,
        source="ccxt_binance_tickers",
        sample_limit=limit,
        asset_class="crypto",
    )
```

`CRYPTO_UNIVERSE_NOTE` 的措辞对齐 `SURVIVORSHIP_BIAS_NOTE` 的诚实程度：

> "This universe uses the current top-N USDT perpetual swap markets by 24h trading volume (queried at run time, not as of `as_of_date`), applied across the requested historical window. Perpetuals delisted before `as_of_date` are absent, and the volume ranking may not reflect the historical ranking at `as_of_date` — this is not a point-in-time universe."

`build_universe()` 的 dispatch 逻辑（[universe.py:74](quantbench/data/universe.py:74)）加一个分支：`normalized in {"topusdtperpetual", "cryptoperpetual", "usdtperpetual"}` → 调用新函数；不认识的名字继续抛 `ValueError`（不新增静默兜底）。

### 4.6 `build_sp500_universe` 补上 `asset_class="equity"`

一行改动，确保 4.1/4.2 的字段在 equity 路径上也有正确的值，而不是只在新代码路径里存在。

---

## 五、明确不做的事（避免把"多资产"做成一个筐）

| 不做 | 原因 |
|---|---|
| 期货（futures）支持 | 需要全新 provider + continuous contract 展期逻辑，是和"加一个 universe builder"完全不同量级的新问题；VISION 点名要做，但贸然现在做容易做出一个没有真实数据校准、Reviewer 也没针对性检查过的半成品。建议单独开一个 Phase，先把"期货连续合约怎么构造、展期规则怎么定义"作为独立的设计问题想清楚 |
| Funding-adjusted 回测数学 | 需要新数据源（`fetch_funding_rate`）和回测引擎改动；本 Phase 只做"诚实告知未建模"这一步（4.3），不做完整实现 |
| Open interest / liquidation volume 数据源 | VISION 5.3 节的 `PerpetualData` 提到这些字段，但当前没有任何检查逻辑依赖它们，加了也用不上，等真的有用到这些数据的 Reviewer 检查或因子逻辑时再加 |
| 多 agent 协作、自定义 skill 系统、组合优化、paper trading、远程计算 | VISION Phase 5 清单里的其余五项，和"多资产支持"没有直接依赖关系，各自都够独立开一个 Phase；硬塞进同一份计划会重蹈"Phase 5 是个筐"的问题 |
| Point-in-time crypto universe | 和 equity 的 point-in-time 一样（[universe.py:49](quantbench/data/universe.py:49) 现在也是 `raise NotImplementedError`），crypto 版本同样不做，保持两条路径的局限对称、诚实 |

---

## 六、关键技术决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| 资产类别怎么知道 | `UniverseDefinition.asset_class` 显式字段，构建时写死 | 见 4.1；避免用字符串猜测驱动会影响 Reviewer 结论的路由决策 |
| top N 怎么排序 | 24h quote volume 降序，来自 ccxt `fetch_tickers()` | 确定性、可测试、和 sp500 universe 的"按字母表截断"一样是纯代码规则，不需要模型判断"这些币有没有代表性" |
| Funding cost 处理方式 | v1 只加一条强制 warning，不做完整建模 | 见 4.3；避免"看起来功能齐全但数学是错的"这种比"功能缺失"更危险的状态 |
| 期货要不要一起做 | 不做，明确推迟 | 见第一节和第五节；期货的核心难点（展期）和"多资产支持"字面意思重叠但工程性质完全不同，一次性做容易两头做不好 |
| universe 名字怎么匹配 | 沿用 `build_universe()` 现有的字符串 normalize + 精确匹配分发模式（[universe.py:74](quantbench/data/universe.py:74)），不认识就报错 | 和 equity 路径完全一致的既有约定，不引入第二套 dispatch 风格 |

---

## 七、按日拆解（预计 5-6 个工作日——比前几个 Phase 短，因为大部分基础设施已经存在）

| Day | 任务 | 产出 |
|---|---|---|
| **Day 1** | `UniverseDefinition.asset_class` 字段 + `build_sp500_universe` 补上 `asset_class="equity"` + `library/record.py` 的 `_classify_asset` 优先读取该字段（显式字段优先于字符串猜测，猜测逻辑保留作为老 run 的兜底）+ 单测 | 字段贯通，equity 现有测试不回归 |
| **Day 2** | `ccxt_binance.fetch_top_symbols_by_volume` + 单测（mock `fetch_tickers`，覆盖过滤非 USDT/非 swap/非 active、按 volume 降序、`limit` 截断） | 排序逻辑独立可信，不依赖真实网络 |
| **Day 3** | `build_crypto_perpetual_universe` + `build_universe()` dispatch 分支 + 单测（含诚实声明文案的断言） | crypto universe 可构建 |
| **Day 4** | 修复 4.2（cross-sectional benchmark 路由）+ 4.3（funding cost warning）+ 回归测试（equity 截面场景 benchmark 仍是 SPY；crypto 截面场景 benchmark 是 BTC/USDT 且 warnings 里有 funding 提示） | 两个正确性修复到位，equity 路径不受影响 |
| **Day 5** | 端到端验收：三条验收命令跑通（含真实网络调用 ccxt）；`library.record.build_record` 对 crypto 截面 run 的分类正确；`uv run pytest` 全量通过 | 验收标准全部满足 |
| **Day 6**（缓冲） | 如果 ccxt 真实网络调用暴露限流/超时问题（参考 Phase 4 审核时发现的 yfinance 无超时问题），加对应的超时/重试防护；更新 VISION.md Phase 5 状态和 README | 端到端在真实网络条件下稳定，文档同步 |

---

## 八、风险与应对

| 风险 | 应对 |
|---|---|
| ccxt `fetch_tickers()` 对 Binance 全市场返回一次性拉取所有 symbol 的行情，可能较慢或触发限流 | 复用现有 `ccxt.binance({"enableRateLimit": True})` 配置（[ccxt_binance.py:16](quantbench/data/providers/ccxt_binance.py:16) 已经这么做）；如果 Day 5/6 端到端测试发现明显延迟，给 `fetch_top_symbols_by_volume` 加超时和清晰的失败信息，而不是让它像 Phase 4 审核发现的 yfinance 调用一样无限期挂起 |
| Top N 榜单在真实网络环境下随时间变化，导致"用真实数据验收"的测试不是确定性可重放的 | 正确性单测（第三节"成交量排序确定性"）全部用 mock ticker 数据，不依赖真实排名结果；端到端验收命令允许人工检查"结果合理"而不是断言具体 symbol 列表 |
| `asset_class` 字段加到 `UniverseDefinition` 后，`config.yaml`/`manifest.json` 里旧 run 没有这个字段，读取时可能报错 | `asset_class` 给默认值 `"equity"`（dataclass 默认参数），且 `library/record.py` 的读取路径本来就走 `config.get(...)` 风格的宽容读取（Phase 3 已经为老 manifest 缺字段做过 backfill 处理，见 PHASE3.md 风险一节），沿用同样的容错方式 |
| Funding cost warning 只加了"提示"，用户可能误以为这是"已经处理好了的功能"而不是"已知缺口" | Warning 文案明确写"do not model"（未建模），且复用 Phase 2/3 建立的"warnings 不能被模型省略或淡化"约束，Coordinator 的最终回答必须原样带出这条警告 |
| 期货相关的 VISION 承诺被无限期搁置，缺乏跟踪 | 在 VISION.md Phase 5 状态里明确写"期货支持推迟，原因见 PHASE5.md 第一节"，而不是让它在 checklist 里悄悄消失 |

---

## 九、执行过程中的追加改动：Binance 地区限制，换成可配置的 ccxt 交易所

计划落地后，实际执行发现 Binance 的网站/API 在部分地区（如中国大陆无代理环境）访问不了，`ccxt_binance.py` 里的两个函数在真实网络环境下直接拉不到数据。处理方式：

1. **模块改名为 `quantbench/data/providers/ccxt_perpetual.py`**，交易所改成可配置：`CCXT_EXCHANGE_ID = os.environ.get("QUANTBENCH_CCXT_EXCHANGE", "okx")`，默认 OKX。以后再遇到某个交易所被限制，只需要改这一个常量（或设置环境变量），不需要再动 `exchange.py`/`universe.py`/`coordinator.py` 里任何一行。
2. **顺带验证时发现一个比"换个交易所"更隐蔽的正确性 bug**：OKX 上裸 symbol（如 `"BTC/USDT"`）在 `defaultType: swap` 下解析到的是**现货市场**，不是永续合约——和 Binance 不一样（Binance 的裸 symbol 本身就是永续合约）。OKX 的永续合约实际是 `"BTC/USDT:USDT"` 这种带后缀的 unified symbol。如果只是简单地把 `ccxt.binance` 换成 `ccxt.okx`，系统会静默地把现货数据当永续合约在跑 Reviewer 的全部检查——这正是 VISION 反复强调的"结果好看但悄悄错了"，而且比数据源整个拉不到更危险，因为它不会报错，只会给出错误但看似合理的回测结果。
3. 修复方式：新增 `_resolve_swap_symbol(exchange, symbol)`，在 `download_ohlcv` 内部把裸 symbol 解析成该交易所真正的永续合约 unified symbol（不存在对应 swap 市场就原样透传，交给 ccxt 自己报错）。这样 `prompts.py`/`coordinator.py`/测试用例里"BTC/USDT"这种 Binance 风格的写法完全不用改，交易所特定的 symbol 格式差异被封在 provider 模块内部，不泄漏到系统其他地方。
4. 影响范围：`quantbench/data/exchange.py`（import 改名）、`quantbench/data/universe.py`（import 改名 + `source` 字段改成动态拼接 `f"{ccxt_perpetual.name}_tickers"`）、`quantbench/data/cache.py`（`cache_path_for` 的 `provider` 默认值从硬编码的 `"ccxt_binance"` 改成中性的 `"unknown"`——这个默认值本来就是死代码，从未被真正调用过，顺手清理避免同样的"硬编码交易所名字"问题在这里也悄悄过期）、以及三个测试文件（`test_data_providers.py`/`test_phase0_core.py`/`test_phase5_crypto_universe.py`）的 import 和 mock 对象改名。测试里能用 `ccxt_perpetual.name`/`ccxt_perpetual.CCXT_EXCHANGE_ID` 引用的地方都不再硬编码交易所名字字符串，避免以后再换交易所又要改一遍测试。
5. 新增 `test_resolve_swap_symbol_prefers_real_swap_market_over_bare_spot_symbol` 和 `test_download_ohlcv_fetches_the_resolved_swap_symbol_not_the_bare_one` 两个测试，专门锁定第 2 点这个 bug 不会回归。
6. **端到端联网验证时又发现第二个真实 bug**：`fetch_top_symbols_by_volume` 对着真实 OKX 跑，返回了 0 个 symbol——不是报错，是**静默返回空列表**。原因是 OKX 的永续合约 ticker 里 ccxt 统一字段 `quoteVolume` 是 `None`，实际 24 小时成交额只存在于原始 `info` 字段的 `volCcy24h` 里（Binance 的 ticker 会正常填充统一字段，这是两个交易所在 ccxt "统一接口"下的不一致，不是本项目的问题，但必须适配）。`_ticker_quote_volume` 加了一个已知交易所专属字段名的兜底列表（目前只有 `volCcy24h` 一项），并补了 `test_fetch_top_symbols_by_volume_reads_okx_style_raw_info_quote_volume` 锁定。**这个 bug 比第 2 点更值得警惕，因为它连"跑出错误结果"都算不上——是安静地返回空，`build_crypto_perpetual_universe` 那句 `if not top: raise ValueError(...)` 兜底才让它没有继续往下悄悄用一个空 universe 跑完整个流程。**

---

## 十、Phase 5 完成后的检查清单

- [ ] 三条验收命令（crypto 截面 + 两条 equity 回归）全部跑通——**需要在真实能访问 OKX 的网络环境下验证**，之前 Binance 被地区限制过一次，不能假设换了交易所就一定没事
- [ ] crypto 截面 run 的 `review_report.json` 里 `beta_exposure` finding 的 `detail` 显示是对 BTC 永续合约算的 beta（而不是默认的 SPY，也不是不小心用了现货数据）
- [ ] crypto 截面 run 的 `manifest.json.warnings` 和 Coordinator 最终自然语言回答里都出现 funding rate 未建模的警告
- [ ] equity 截面 run 的 beta_exposure 回归测试确认仍然对 SPY 算 beta（改动没有误伤 equity 路径）
- [ ] `library.record.build_record` 对新 crypto 截面 run 的 `asset_class` 分类为 `"crypto"`（验证 `UniverseDefinition.asset_class` 字段确实贯通到实验库）
- [ ] `fetch_top_symbols_by_volume` 有独立单测，覆盖过滤规则和排序，不依赖真实网络
- [ ] `build_crypto_perpetual_universe` 有单测，含诚实声明文案断言
- [x] `_resolve_swap_symbol` 有单测，覆盖"裸 symbol 本身就是 swap"和"裸 symbol 是现货、需要解析成 `:USDT` 后缀"两种交易所行为
- [x] `uv run pytest` 全量通过（71 passed），含 Phase 0-4 已有测试（回归不破坏）
- [x] 用真实 OKX 网络连接端到端验证：`build_universe("top_10_usdt_perpetual", ...)` 返回真实 top 10 永续合约 symbol 列表；`fetch_ohlcv("BTC/USDT", "4h", ...)` 正确解析成 `BTC/USDT:USDT` 并拉到真实 4h K 线（非 synthetic fallback）
- [ ] 回到 VISION.md 更新 Phase 5 状态：多资产支持标注为"crypto 截面完成（交易所从 Binance 换成 OKX），期货明确推迟"，不是笼统打勾或留白

---

*完成这部分 Phase 5 后，回到 [VISION.md](VISION.md) 评估：期货支持要不要单独立项、多 agent 协作/自定义 skill 系统/组合优化/paper trading/远程计算这五项里哪个对当前研究工作流最有价值，作为下一步的候选。*

# Phase 11 详细实施计划：数据地基——Point-in-time / 退市数据 / 数据源健壮性 / 版本锁定 / Funding

> 对应 [GAP_ANALYSIS.md](GAP_ANALYSIS.md) **第一章「数据层缺口」**(1.1–1.5)与第六章「第二优先级：数据地基」。
> 前置条件：[PHASE10.md](PHASE10.md)（统计护栏）已完成并合并到 `main`。
> 目标：把研究结论的**方向**变可信。统计护栏(Phase 10)回答"这是 alpha 还是运气",数据地基回答一个更底层的问题——**喂进回测的 universe 和价格本身是不是有偏的**。在有幸存者偏差的 universe 上，动量/反转类因子的截面结果连正负号都可能是错的，而这个偏差发生在数据进入回测**之前**，Reviewer 再严也审不出来。

> **总原则(承接项目既有立场)**：本章的价值不是一步到位"消除全部偏差"，而是把"诚实标注偏差"升级为"结构性消除主要偏差 + 对残余偏差诚实标注并影响 verdict"。任何一条轨道未完全落地时，残余偏差必须**被显式暴露**(universe 元数据 + Reviewer 警告)，绝不能重新藏回数据管线里。

---

## 〇、章节内轨道与依赖

第一章的 5 个小节不是线性依赖，但有两组强耦合，排序按此展开：

| 小节 | 优先级 | 资产 | 关键耦合 |
|---|---|---|---|
| **1.1 Point-in-time universe** | 🔴 最高 | equity | 与 1.2 绑定：PIT 并集含退市标的，拿不到数据则偏差从 universe 层漏到数据层 |
| **1.2 退市标的数据获取** | 🔴 高 | equity + crypto | 1.1 的完整性前提 |
| **1.5 Funding rate 与持有成本** | 🔴 高 | crypto | 独立轨道，crypto 结论可信的前提 |
| **1.3 数据源健壮性 + 正式数据源抽象位** | 🟡 中高 | equity | 独立，可增量 |
| **1.4 数据版本锁定闭环 + rerun** | 🟡 中高 | all | 独立，横切所有资产 |

**落地顺序**：1.1 →(立即衔接)1.2 → 1.5 → 1.4 → 1.3。理由见第七节。

---

## 一、1.1 Point-in-time universe（🔴 最高）

**现状**：`build_sp500_universe`([universe.py:58](quantbench/data/universe.py))已支持当前成分快照和 S&P 500 point-in-time membership intervals；`UniverseDefinition` 已包含 `membership_intervals` / `covers_delisted` 元数据。crypto PIT 仍未实现，等待每日快照积累方案。

**关键洞察**：截面引擎([cross_sectional_backtest.py](quantbench/engine/cross_sectional_backtest.py))已是长格式 `(timestamp, symbol, factor, forward_return)` 且**逐 timestamp 独立分组**(`groupby(["timestamp","group"])`)，对某标的某时刻缺 factor 已容忍。所以时变 universe **不是重构引擎**，而是在 `factor_panel` 建好后 mask 掉"标的不在成分内"的行。

### 1.1.1 历史成分重建（✅ 已完成）

- [x] 新增 [quantbench/data/providers/sp500_history.py](quantbench/data/providers/sp500_history.py)：解析 Wikipedia 变更表(表 1，402 行，`Effective Date / Added / Removed`)，`reconstruct_membership(as_of_date, current, changes)` 从当前成分反向回放，`membership_intervals(start, end, current, changes)` 产出 `{symbol: [(enter, exit), ...]}`，`build_point_in_time_sp500(start, end)` 一步到位并对覆盖不到的过早日期报错。
- [x] [tests/test_phase11_pit_membership.py](tests/test_phase11_pit_membership.py)：4 个合成数据测试(反推、区间裁剪、swap 追踪、earliest 边界)。
- [x] 真实数据验证：2020–2023 窗口曾在册并集 560、常驻 455，反推退出标的日期正确(WCG/XEC/ARNC/RTN)。

### 1.1.2 Universe 接线（✅ 已完成）

- [x] `UniverseDefinition`([universe.py:40](quantbench/data/universe.py))新增字段 `membership_intervals: dict[str, list[list[str]]] | None = None`(区间用 ISO 字符串，`to_dict`/`save_yaml` 自动可序列化)。
- [x] `build_sp500_universe` 的 `point_in_time=True` 分支：调 `build_point_in_time_sp500(start, end)`，`symbols` = 并集、`point_in_time=True`、`membership_intervals` 落地、`survivorship_bias_note` 改成"本 universe 为 point-in-time，无幸存者偏差"。**注意**：PIT 需要 `start`/`end`，当前 `build_universe` 只传 `as_of_date`——需把回测窗口透传进来(签名扩展 `start`/`end`，非 PIT 路径忽略)。
- [x] `build_universe` 分发处同步透传窗口；crypto 分支 `point_in_time=True` 仍 `NotImplementedError`(留给 1.2 的快照积累方案)。

### 1.1.3 引擎 mask（✅ 已完成）

- [x] `run_cross_sectional_backtest` 新增可选参数 `membership_intervals: dict[str, list[tuple[str, str]]] | None = None`；在 `factor_panel` 构建后、`_assign_groups` 前，用向量化 mask 剔除 `timestamp ∉ 该 symbol 任一区间` 的行。空 universe 时刻由已有的 `available_symbols < n_groups` 守卫兜底。
- [x] Coordinator `_run_cross_sectional_backtest` / `_screen_factors` 把 `ctx.universe.membership_intervals` 透传进引擎。
- [x] **边界处理(v1)**：某标的退出日的 `forward_return` 会跨到退出后一根 bar——v1 接受这 1-bar 边界效应，不特殊处理(截面里可忽略)，在文档标注。

### 1.1.4 Reviewer 并排对比（待办，即验收标准）

- [x] Reviewer/research note 报告本 run 用的是 PIT 还是快照 universe。
- [ ] 支持同一因子在 PIT 与快照两种 universe 上并排回测，展示差异(可通过两次 run + 既有 compare 视图，不必新建引擎路径)。

**验收**：同一 20 日动量因子，在 PIT S&P 500 与当前快照上分别回测，系统并排展示两者差异，note 明确说明用了哪种 universe，且 PIT run 的 universe 元数据 `point_in_time=True`。

---

## 二、1.2 退市标的的数据获取（🔴 高，1.1 的完整性前提）

**现状**：1.1 的 PIT 并集里含已退市/被收购标的(WCG、RTN 等)，但 yfinance 对退市 ticker 历史数据不可靠甚至拉空；crypto 侧 `fetch_top_symbols_by_volume` 显式 `active is True` 过滤([ccxt_perpetual.py:72](quantbench/data/providers/ccxt_perpetual.py))，退市永续根本进不了 universe。**若不处理，1.1 mask 出的历史成员里退市那部分会因拿不到数据被悄悄丢掉，偏差从 universe 层漏到数据获取层。**

**v1 策略：先诚实暴露覆盖率，再逐步补源**(符合项目"先标注后消除"原则)：

- [x] **数据覆盖率核算**：`fetch_universe_ohlcv`([warehouse.py:97](quantbench/data/warehouse.py))对 PIT universe 记录每个成员的实际数据覆盖(有数据的天数 / 应在册天数)，产出 `coverage_report`。
- [x] **Reviewer 新增检查项 `universe_coverage`**：退市成员数据缺失率超阈值(如 >10% 的在册-天缺数据) → `warning`，并封顶 verdict(不给 STRONG)；写入 note"本 PIT run 有 X 个历史成员数据缺失，结果仍有残余幸存者偏差"。
- [ ] **crypto 每日快照积累机制**(最低成本无偏方案)：新增 `quantbench snapshot universe` 命令，每日快照当前 universe + 行情写入 warehouse；随时间自然积累**真正 point-in-time、含当日在市全集**的无偏数据。这也是 1.1 crypto PIT 路径和 [PHASE10 未及的] alpha 生命周期(GAP 5.2)的共同地基。
- [x] **正式退市数据源评估位**(不强制本阶段接入)：在 `providers/base.py` 抽象下留好含退市覆盖的付费源实现位(Tardis / 交易所归档 / 付费 equity 源)，schema 映射文档化。
- [x] universe 元数据新增 `covers_delisted: bool`，Reviewer 对 `False` 的 PIT 截面 run 输出结构性警告并封顶 verdict。

**验收**：PIT run 的 note 明确列出"覆盖 X/Y 个历史成员，缺失 Z 个(退市/数据不可得)"；缺失率超阈值时 verdict 被封顶且 Reviewer 有 `universe_coverage` 警告。

---

## 三、1.5 Funding rate 与持有成本建模（🔴 高，crypto 结论可信前提）

**现状**：crypto 永续 run 只在 coordinator 写一条"funding 未建模"警告。永续多空里 funding 是一等成本项，做多高动量币种常年付正 funding，年化能吃掉几十个点，足以把 Sharpe 1.5 变亏损。

- [x] **`fetch_funding_rate` provider**：`ccxt_perpetual.py` 新增(CCXT `fetchFundingRateHistory` 支持)，返回逐期 funding rate，schema 落地 VISION 已定义的 `PerpetualData`(funding_rate / open_interest)。
- [x] **引擎计入 funding**：crypto 永续场景下 `run_cross_sectional_backtest` 按持仓方向逐期扣减 funding(多头付正 funding、空头收，或反之)，与 `cost_bps` 并列为独立成本项。
- [x] **Reviewer 新增检查项 `funding_cost_sensitivity`**：funding 计入前后的 Sharpe 对比(结构类比现有 `cost_sensitivity`)，衰减过大 → warning。
- [x] warehouse 缓存 funding rate 序列(复用 DuckDB upsert 幂等模式)。

**验收**：一个 crypto 永续动量截面 run，note 报告 funding 计入前后的 Sharpe，且 funding 序列被缓存、可复现。

---

## 四、1.4 数据版本锁定闭环 + rerun（🟡 中高，横切所有资产）

**现状**：manifest 记 `cache` meta 和 `data_path`，但无每分片内容 hash → 可复现闭环没合上。yfinance 复权数据会被追溯修改，**同一 run 半年后重跑结果不同，"可复现"承诺已破**。`cache.py` 已有 `file_sha256`([cache.py:57](quantbench/data/cache.py))可复用。

- [x] **每 run 记录数据指纹**：manifest 新增 `data_slices: [{symbol, timeframe, start, end, content_hash, rows}]`，hash 复用 `file_sha256`(单标的)或对 universe panel 逐分片记录。
- [x] **`quantbench rerun <run_id>` 命令(v1 漂移闸门)**：优先校验缓存中 hash 匹配的分片；缓存缺失或 hash 不匹配 → 显式报告"数据已漂移，结果不可直接对比"，而非静默出不同结果。完整 bit-level 指标重算仍需后续把 run 配置自动重放接上。
- [ ] **数据分片保留策略**：跑过 run 的分片不被缓存淘汰，或淘汰前归档(避免 rerun 时原始数据已丢)。

**验收**：跑一个 run 后 `quantbench rerun <run_id>`，缓存命中时逐指标 bit-level 一致；人为改动缓存分片后 rerun，系统明确报"数据已漂移"。

---

## 五、1.3 数据源健壮性与正式数据源抽象位（🟡 中高）

**现状**：美股唯一源是 yfinance——免费、非官方、随时挂、复权口径不透明且历史会被追溯改。`providers/base.py` 的 `MarketDataProvider` Protocol + `ProviderResult(df, source, fallback_reason)` 抽象已在，但只有 yfinance/ccxt 两个实现。

- [x] **付费正式源实现位**：为至少一个付费源(Polygon / Tiingo / Databento)留好 `MarketDataProvider` 实现，明确各字段 schema 映射(即使不填 API key，抽象和测试先就位)。
- [x] **复权方式显式记录**：当前 `adjusted: bool` 不足以描述——扩为 `adjustment: {method: raw|split|split_dividend, dividend_reinvested: bool}`，写入 dataset 元数据和 note。
- [x] **降级策略显式化**：主源失败时的行为(报错终止 vs 降级并警告)写进 `ProviderResult.fallback_reason` 语义，**不允许静默切换**；降级即在 manifest 和 note 留痕。

**验收**：research note 明确记录数据源、复权方式；主源失败时降级行为可见(manifest 有 `fallback_reason`)，无静默切换。

---

## 六、明确不做（本章边界）

- **不做 point-in-time 的 GICS 行业/市值历史**——那属于 Phase 12 风险模型的数据依赖，本章只做成分 membership。
- **不强制接入付费数据源**——1.2/1.3 只落地抽象位 + schema 映射 + 覆盖率诚实标注，真实付费源接入是独立的、有成本的后续工作。
- **不做 crypto 历史成交量快照重建**(用历史某日排名回填)——转而用 1.2 的"从今天起每日快照积累"这一无偏方案，历史 crypto PIT 暂标注为不可得。
- **不改统计护栏(Phase 10)阈值**——本章只给 Reviewer 增加 `universe_coverage` / `funding_cost_sensitivity` 两个新 finding，复用既有 verdict 聚合。

---

## 七、落地顺序与理由

1. **1.1.2 + 1.1.3 + 1.1.4**(PIT 接线 + 引擎 mask + 并排对比)——重建核心(1.1.1)已完成验证，先把 PIT 机制端到端打通。
2. **1.2 覆盖率诚实暴露**(紧接 1.1)——PIT 一通就立刻碰到退市数据缺口，先用 `universe_coverage` 警告把残余偏差暴露出来，别让它漏回数据层。付费退市源留位不强接。
3. **1.5 Funding**——独立轨道，crypto 结论可信的前提，与 equity 轨道解耦可并行。
4. **1.4 数据版本锁定 + rerun**——横切所有资产，复用已有 `file_sha256`，成本中等收益大(补上"可复现"承诺)。
5. **1.3 数据源抽象位 + 复权元数据**——最偏工程、外部依赖最重，放最后；抽象和 schema 先就位，真实接入延后。

每条轨道都遵循同一收尾准则：**残余偏差必须被 universe 元数据 + Reviewer 警告显式暴露，并影响 verdict 上限**——落地一部分就少一部分偏差，没落地的部分是被诚实标注、而非被藏起来。

---

## 八、验证（全章）

- 单元：`tests/test_phase11_*.py` 覆盖 membership 重建(✅)、universe PIT 接线、引擎 mask(合成时变 panel)、覆盖率核算、funding 计入前后 Sharpe、rerun 数据漂移检测、provider 降级留痕。
- 端到端：真实 S&P 500 PIT vs 快照并排对比(1.1 验收)；真实 crypto 永续 funding 前后对比(1.5 验收)。
- 全量 `uv run pytest -q` 零回归——本章新增均为可选参数/新 finding，默认路径(非 PIT、无 funding)行为不变。

---

*落地后将本文件各项标记完成，并把对应能力写回 [README.md](README.md) 能力清单与 [GAP_ANALYSIS.md](GAP_ANALYSIS.md) 第一章的勾选项。*

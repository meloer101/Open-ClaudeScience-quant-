# Phase 4 详细实施计划：可视化与 UI 收尾

> 对应 [VISION.md](VISION.md) 第七节 Phase 4、第 5.4 节（可视化渲染清单）
> 前置条件：[PHASE0.md](PHASE0.md)、[PHASE1.md](PHASE1.md)、[PHASE_UI.md](PHASE_UI.md)、[PHASE2.md](PHASE2.md)、[PHASE3.md](PHASE3.md) 均已完成并合并到 `main`——Web 工作台已经能跑对话、展示 run 进度、浏览单次 run 的 artifact、检索/对比/分叉实验库。VISION 的 Phase 4 状态目前是"部分完成"：实验库表格/筛选/对比（Phase 3 顺带做的）已经打勾，但 5.4 节列的大多数图表类型、真正的"交互式图表"、更完整的 artifact 预览都还没做。
> 目标：把 Reviewer（Phase 2）和 Backtest 引擎已经算出来、但现在只能在 `review_report.json`/`backtest_result.json` 里当死数据看的结构化结果，渲染成 VISION 5.4 节承诺的原生、可交互图表；同时补齐 artifact 预览的最后一块短板（Parquet 预览）。

---

## 一、现状盘点：这个 Phase 到底缺什么（先把"已经有"和"真的没有"分清楚）

这一步很重要——上一轮（Phase 3）审核暴露过"计划写得漂亮但没对齐真实接口"的风险，这次先把数据源逐项核实一遍：

| VISION 5.4 图表 | 现状 | 结论 |
|---|---|---|
| Equity Curve | `skills/plot.py` 生成静态 PNG；`backtest_result.json.series` 里已有完整 `timestamp/returns/equity_curve/drawdown/position` 时间序列（见 [vectorized_backtest.py:23](quantbench/engine/vectorized_backtest.py:23)） | **数据已在，只差前端交互渲染** |
| Drawdown Chart | 同上 | **数据已在，只差前端交互渲染** |
| Decile Return Bar | 静态 PNG（`save_group_returns_plot`）；`backtest_result.json.group_returns`（cross-sectional）已有每个分位每期收益（见 [cross_sectional_backtest.py:40](quantbench/engine/cross_sectional_backtest.py:40)） | **数据已在，只差前端交互渲染** |
| Turnover Chart | cross-sectional 的 `backtest_result.json.series.turnover` 已有时间序列；**单标的路径只存了 `turnover_annual` 标量，没有序列**（[vectorized_backtest.py:23-33](quantbench/engine/vectorized_backtest.py:23)） | 截面场景数据已在；**单标的场景需要补一处后端改动** |
| Cost Sensitivity Plot | `review_report.json` 的 `cost_sensitivity` finding 里有 `sharpe_by_multiplier`（1.0/1.5/2.0 三点） | **数据已在，纯前端图表** |
| Parameter Heatmap | `review_report.json` 的 `parameter_stability` finding 里有 `sharpe_by_perturbation`（base/-20%/+20% 三点，不是真正网格） | **数据已在，纯前端图表**（诚实起见，v1 只能是三点柱状图，不是网格热力图，命名和展示要如实反映） |
| Regime Decomposition | `review_report.json` 的 `regime` finding 里有 `yearly_contribution`（按年） | **数据已在，纯前端图表** |
| Correlation Matrix | **完全没有**——这是"多 run 相关性"，不是单 run 概念 | 新计算，见第三节 |
| Risk Attribution | 目前只有单因子 `beta_exposure`（vs 一个 benchmark 的 beta/r²），没有真正的多因子风险归因（size/value/momentum 暴露） | **不在本 Phase 范围**，见第四节 |
| Factor IC Heatmap（按时间/标的） | 现状只有一条聚合 rank IC 时间序列（`rank_ic.png`），没有按标的展开的矩阵 | **不在本 Phase 范围**，见第四节；用已有的 decile-by-time 数据做一个诚实改名的替代图表 |

**结论：这个 Phase 的大部分工作量在前端**（把已经序列化好的 JSON 渲染成可交互图表），后端新增工作只有三处：单标的 turnover 序列、跨 run 相关性矩阵、Parquet 预览端点。这和 Phase 2/3"模型不参与、代码算数据、前端只管渲染"的准则完全一致——本 Phase 甚至连模型都不用碰，是纯粹的"代码写"工作。

---

## 二、验收标准（先定终点）

**验收命令（复用已有的两条验收路径 + Phase 3 的 compare）：**

```
$ python -m quantbench "测试20日动量因子在AAPL上的表现，2018-01-01到2024-01-01"
$ python -m quantbench "在标普500成分股里测试20日动量因子的截面表现，2022-01-01 到 2024-12-31，等权十分位多空组合"
$ python -m quantbench compare <run_A> <run_B>
```

跑完后，Web 工作台里：

1. 打开任意一次 run，能看到一个新的"Charts"入口（不替换现有的静态 PNG 卡片，PNG 继续保留用于下载/归档），点开后：
   - Equity Curve / Drawdown：可交互折线图，hover 显示日期、净值、回撤百分比
   - （仅截面场景）Decile Return Bar：可交互柱状图，hover 显示具体分位和收益
   - （仅截面场景）Turnover 时间序列图；（单标的场景同样有，验证第一节提到的后端补丁生效）
   - Cost Sensitivity：1x/1.5x/2x 三点柱状图，hover 显示具体 Sharpe
   - Parameter Stability：-20%/base/+20% 三点柱状图
   - Regime Decomposition：按年贡献柱状图，标出 `REGIME_CONCENTRATION_THRESHOLD` 阈值线
   - Beta Exposure：一张简单的数值卡片（beta / r² / observations），不是假装精确的图
   - （仅截面场景）Symbol Concentration：top-5 标的贡献柱状图
2. Compare 视图（Phase 3 的 `CompareView.tsx`）新增"Returns Correlation"区块：选中的 run 两两收益相关系数矩阵（数据来自各自 `backtest_result.json` 的 returns 序列，按时间戳对齐求相关系数）
3. Artifact Inspector 打开一个 `.parquet` 文件时不再是"下载"提示，而是像 CSV 一样能预览前 200 行

### 正确性测试场景

- **图表数字和源 JSON 完全对得上**：给定一个已知 `review_report.json`（比如 `sharpe_by_multiplier = {1.0: 1.2, 1.5: 0.9, 2.0: 0.6}`），前端渲染出的柱状图三个柱子的数值必须精确等于这三个数（不是像素级近似，是断言渲染逻辑读取的原始数字）。
- **相关性矩阵在真实数据上验证**：拿两个已知强相关（同一父子 fork）和两个明显不相关的 run 算相关系数，数值要落在合理区间（fork 出来的子 run 和父 run 相关系数应该很高，因为大部分持仓没变）。

---

## 三、模块拆解

### 3.1 后端：三处新增，其余不动

| 改动 | 文件 | 内容 |
|---|---|---|
| 单标的 turnover 序列 | [quantbench/engine/vectorized_backtest.py:23](quantbench/engine/vectorized_backtest.py:23) `BacktestResult.to_json_dict` | 增加 `"turnover": turnover.fillna(0).round(6).tolist()`（`turnover` 变量在 `run_vectorized_backtest` 内已经算出来，见函数体第 50 行左右，只是没存进 `BacktestResult`——需要把 `turnover` 加进 dataclass 字段并在构造处传入） |
| 跨 run 相关性矩阵 | `quantbench/library/compare.py` 新增 `compute_returns_correlation(run_ids)` | 读取每个 run 的 `backtest_result.json`（单标的用 `series.returns`，截面用 `series.long_short_returns`），按 timestamp 取交集对齐（不足最小观测数——比如 30 个共同交易日——的 pair 标记 `"insufficient_overlap"` 而不是硬算一个不可信的相关系数），返回 `{run_id_a: {run_id_b: float | null}}` 对称矩阵 |
| `/api/compare` 响应扩展 | `quantbench/api/server.py` 的 `get_compare` | 在返回体里加一个 `returns_correlation` 字段，调用上面的新函数；两个以下 run 时该字段为空对象（相关性矩阵至少需要 2 个 run） |
| Parquet 预览端点 | `quantbench/api/server.py` 新增 `GET /api/runs/{run_id}/artifacts/{filename}/preview` | 用 `pandas.read_parquet` 读文件，`.head(200)` 转 `to_dict(orient="records")` 返回 JSON；非 `.parquet` 文件或文件不存在返回 404；这是本 Phase **唯一**读取 artifact 内容做"计算"的后端代码，但计算本身就是"截取前 200 行"，没有任何判断逻辑，符合"代码写"边界 |

**不改的地方，明确写出来避免范围蔓延**：`skills/plot.py` 的 matplotlib 图继续生成、继续存盘——它们是可下载归档的静态资产，不是本 Phase 要替换的东西；`review/report.py` 的检查逻辑和阈值一律不动，本 Phase 只消费它已经算好的 `detail` 字段，不改判定规则。

### 3.2 前端：新增一套零依赖的图表组件

**技术决策（详见第五节）：不引入图表库（recharts/visx/chart.js 等），手写一套轻量 SVG 图表组件。** 理由：现有代码库里所有图标（`ArtifactInspector.tsx` 的 `FileIcon` 等）都是手写内联 SVG，没有任何图表库依赖；QuantBench 的图表需求是"折线/柱状/简单表格"这种基础形状，不需要一个通用图表库的重量级抽象；图表的坐标换算、分箱、阈值线这些计算逻辑本身就应该是确定性、可单测的纯函数，符合 VISION 第十一节的准则。

新增 `web/src/components/charts/`：

| 文件 | 职责 |
|---|---|
| `charts/scale.ts` | 纯函数：`linearScale(domain, range)`、`niceTicks(min, max, count)` 等坐标换算，**独立可单测**（不依赖 DOM/React） |
| `charts/LineChart.tsx` | 折线图（equity curve / drawdown / turnover 序列），hover 显示最近点的 tooltip |
| `charts/BarChart.tsx` | 柱状图（decile return / cost sensitivity / parameter stability / regime / symbol concentration 复用同一个组件，只是传入不同数据和阈值线） |
| `charts/CorrelationMatrix.tsx` | 相关系数矩阵表格/热力网格（数值越接近 ±1 颜色越深，直接用已有 warm 色板的深浅，不引入新配色系统） |
| `charts/StatCard.tsx` | 简单数值卡片（beta exposure 用），明确不是图表，避免为了"看起来是图"而假装精确 |

`web/src/components/ChartsPanel.tsx`（新组件，装配上面这些原子图表）：
- 输入 `runId`，内部用现有 `useQuery` 模式拉取该 run 的 `backtest_result.json` 和 `review_report.json`（两个文件都已经通过 `GET /api/runs/{id}/artifacts/{filename}` 可读，不需要新端点）
- 根据 `review_report.json.findings` 里每个 `check` 是否存在、`detail` 是否非空，决定渲染哪些图表区块；找不到数据的区块直接不渲染（不画空图表、不显示"暂无数据"的占位框——如果数据没有，说明这个检查被跳过了，静默省略比强行画一个空图更诚实）

### 3.3 UI 接入点

- `web/src/components/ArtifactGallery.tsx`：在现有卡片列表前追加一张固定卡片"📊 Interactive Charts"（不是从 `artifacts` 列表派生的真实文件，是虚拟入口），点击后通过 `App.tsx` 现有的 `openArtifactTabs` 机制打开一个特殊 tab（`kind: "chart-dashboard"`，`OpenArtifactTab`/`ArtifactInfo` 的 `kind` 联合类型里加这个值，见 [web/src/types.ts:14](web/src/types.ts:14)）
- `web/src/components/ArtifactInspector.tsx` 的 `ArtifactBody`：给 `artifact.kind === "chart-dashboard"` 加一个分支渲染 `<ChartsPanel runId={...} />`；给 `artifact.kind === "binary" && filename.endsWith(".parquet")` 加一个分支调用新的 `/preview` 端点、复用现有 `CsvTable` 的表格渲染方式（那部分逻辑本来就是"给二维数组画表格"，和数据源是 parquet 还是 csv 无关，直接抽出复用而不是复制一份）
- `web/src/components/CompareView.tsx`（Phase 3 产物）：在现有指标对比表下面加一个 `<CorrelationMatrix />` 区块，消费扩展后的 `/api/compare` 响应里的 `returns_correlation`

---

## 四、明确不做的事（避免范围蔓延，也是对"假装精确"的拒绝）

| 不做 | 原因 |
|---|---|
| 真正的按标的展开的 Factor IC Heatmap（时间 × 标的矩阵） | 现有系统从未按标的持久化过逐期 IC 贡献；S&P 500 全量标的的热力图对普通研究者也没有实际可读性（500 列挤在一屏）。v1 用已有的 decile-by-time 数据做一个诚实命名的"Decile Return Heatmap"（时间 × 十分位，10 列，可读），不冒充"IC Heatmap"这个名字 |
| 多因子 Risk Attribution（size/value/momentum 暴露分解） | 需要一个因子模型（比如 Fama-French 因子收益序列）作为回归基础，目前系统里不存在这个数据源；伪造一个只回归单一 benchmark 的"风险归因"和 VISION 5.4 说的"风险因子暴露分解"名不副实，宁可留白等 Phase 5 多资产工作把因子数据源建起来 |
| 引入图表库依赖（recharts/d3/chart.js） | 见 3.2 技术决策；现有代码库零图表依赖，QuantBench 的图表复杂度不需要 |
| 把静态 PNG 图表下线 | PNG 是可下载归档的 artifact，交互图表是"锦上添花"，不是替代；两者并存 |
| 给单标的场景造一个假的 symbol concentration / regime by symbol | 这类检查本来就只对截面场景有意义（`review/report.py` 里 `symbol_concentration` 也只在 `factor_panel is not None` 时才跑），前端图表严格跟随后端"这个 check 有没有跑"的事实，不为了 UI 好看而在单标的场景硬造 |

---

## 五、关键技术决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| 图表实现方式 | 手写零依赖 SVG 组件，不引入图表库 | 见 3.2；和现有代码风格一致，图表需求复杂度低，坐标换算逻辑可以做成纯函数单测锁定 |
| 图表数据从哪来 | 前端直接消费已有的 `backtest_result.json` / `review_report.json`（通过现有 artifact 端点），**不新增聚合端点** | 这两个文件已经是"代码算好的确定性数据"，不需要再包一层后端 API；减少一个需要维护的响应格式 |
| 找不到数据时怎么办 | 静默不渲染该区块，不画空图/占位符 | 如果某个 check 被 `run_review` 里的 `_safe()` 吞掉异常标成 `info`（见 [review/report.py:117](quantbench/review/report.py:117)），或者截面专属的 check 在单标的场景压根没跑，前端应该如实反映"这个维度没有数据"，而不是画一个误导性的空坐标轴 |
| Parameter Stability 图表叫什么 | 明确叫"Parameter Perturbation"（三点柱状图），不叫"Parameter Heatmap" | VISION 原文用词是"Heatmap"，但现有 `review/parameter_stability.py` 只做 ±20% 单点扰动，不是网格搜索；如果照抄 VISION 的名字会给用户"这是网格搜索热力图"的错误预期。命名要对齐真实计算过程，这是本项目一路以来的准则（Phase 2 校准时就因为"复利假象"改过口径） |
| 相关性矩阵放在哪 | 扩展 Phase 3 的 `CompareView`，而不是单独开一个新页面 | 相关性天然是"比较多个 run"的一部分，`compare_runs` 已经是这个职责的代码入口；避免在 Phase 3 已经建好的 `/api/compare` 之外再造一个平行概念 |
| Parquet 预览要不要分页/流式 | 只取前 200 行（和现有 CSV 预览的 200 行上限一致），不做分页 | 复用 [ArtifactInspector.tsx](web/src/components/ArtifactInspector.tsx) 里 `CsvTable` 已经定的"前 200 行 + 提示下载完整文件"模式，不引入新的交互范式 |
| Turnover 序列要不要重算历史 run | 不重算——只对新产生的 run 生效 | 老 run 的 `backtest_result.json` 没有 `turnover` 字段，前端按"数据缺失就不渲染该图"的统一规则处理，不需要额外的迁移脚本；这和 Phase 3 `record.py` 处理老 manifest 缺字段的思路一致 |

---

## 六、按日拆解（预计 7-8 个工作日，比 Phase 2/3 短——大部分数据已就绪）

| Day | 任务 | 产出 |
|---|---|---|
| **Day 1** | 后端三处新增：单标的 turnover 序列（[vectorized_backtest.py](quantbench/engine/vectorized_backtest.py)）、`library/compare.py` 的 `compute_returns_correlation` + 单测（对齐/最小观测数门槛/fork 父子高相关性的真实数据校验）、`/api/runs/{id}/artifacts/{filename}/preview` 端点 + 测试 | 三处后端改动全部有单测，`uv run pytest` 通过 |
| **Day 2** | `web/src/components/charts/scale.ts` 纯函数 + 单测（用 vitest 或现有前端测试方式，若前端目前无测试基建则至少手工验证边界：空数据、单点数据、负值域） | 坐标换算逻辑独立可信 |
| **Day 3** | `charts/LineChart.tsx` + `charts/BarChart.tsx`，先用 equity curve / drawdown 数据接入验证折线图，用 cost sensitivity 数据验证柱状图 | 两个基础图表组件可用，hover tooltip 正确 |
| **Day 4** | `charts/CorrelationMatrix.tsx` + `charts/StatCard.tsx`；`ChartsPanel.tsx` 把上面所有图表按"该 run 有什么数据就渲染什么"的规则组装起来 | 单个 run 的完整 Charts 面板可用（equity/drawdown/turnover/cost/parameter/regime/beta，截面场景再加 decile/symbol concentration） |
| **Day 5** | UI 接入：`ArtifactGallery.tsx` 的虚拟"Interactive Charts"卡片、`types.ts` 的 `chart-dashboard` kind、`ArtifactInspector.tsx` 分支渲染 | 验收命令 1、2 在 Web 端能打开 Charts 面板 |
| **Day 6** | Parquet 预览前端接入（复用 `CsvTable` 渲染逻辑）；`CompareView.tsx` 接入 `CorrelationMatrix` | 验收命令 3（compare）在 Web 端显示相关性矩阵；打开 `.parquet` artifact 能预览 |
| **Day 7** | 端到端验证：用真实 run（复用 Phase 3 审核时验证过的 fork 场景，父子 run 应该高相关）跑一遍全部图表；检查数据缺失场景（单标的 run 打开 Charts 面板不应该报错或崩、应该干净地跳过截面专属图表） | 真实数据下所有图表和阈值线渲染正确，无控制台报错 |
| **Day 8** | 回归测试：`uv run pytest` 全量通过；更新 VISION.md Phase 4 状态、README"已支持能力" | 文档同步，Phase 4 状态从"部分完成"改为完成（或明确标注仍未做的 IC Heatmap/Risk Attribution 留给 Phase 5） |

---

## 七、风险与应对

| 风险 | 应对 |
|---|---|
| 手写 SVG 图表在极端数据下渲染错误（比如全部为 0 的收益序列导致坐标轴除零，或者 `sharpe_by_multiplier` 只有一个点） | `scale.ts` 的 `linearScale` 对 domain 退化成单点/零宽度的情况显式处理（返回中点而不是除零）；`ChartsPanel` 对每个图表区块的数据做最小长度校验，不足则跳过而不是渲染崩溃的图 |
| 相关性矩阵在 run 数量增多时是 O(n²) 次文件读取，Compare 选多个 run 时变慢 | v1 接受这个开销（`backtest_result.json` 是本地文件读取，不是网络请求，几十个 run 的量级可忽略）；如果 Day 7 测出明显延迟，加一个内存级 LRU 缓存而不是重新设计接口 |
| 前端新增图表组件没有测试基建（项目目前 `web/` 下没有看到前端单测框架） | 坐标换算这类纯函数逻辑在 Day 2 用最小可行的方式验证（如果引入 vitest 成本可接受就加，否则至少写清楚边界用例手工验证并记录在 commit message 里）；不因为"没有测试框架"就跳过验证，只是验证形式上更轻量 |
| `chart-dashboard` 是虚拟 artifact，容易和真实文件的 `ArtifactInfo` 类型产生混淆（比如被 `list_artifacts` 意外扫描到、或者被下载逻辑误处理） | 虚拟卡片完全在前端构造，不经过 `run_reader.list_artifacts`（后端不知道这个概念存在）；`ArtifactInspector` 的下载链接对 `chart-dashboard` kind 直接不渲染下载按钮 |
| Parquet 预览端点被用来读取 `runs/` 目录外的任意文件（路径穿越） | 复用 `get_artifact` 已有的 `if ".." in filename` 校验模式（[server.py:100](quantbench/api/server.py:100)），预览端点同样先做这个检查再拼路径 |

---

## 八、Phase 4 完成后的检查清单

- [x] 两条验收命令（单标的、截面）跑通后，Web 端打开 run 详情能看到"Interactive Charts"入口——单标的用真实 fork run（`run_20260702_084629_125d`）验证；截面场景用真实历史 run（`run_20260701_182710_0520`）验证（另发起一条新的截面验收命令 `run_20260702_094033_c2fb` 时，发现 Reviewer 的 benchmark 拉取无超时保护，网络卡顿导致该 run 挂起，已记录为独立的数据层健壮性问题，不阻塞 Phase 4 验收）
- [x] Equity Curve / Drawdown 交互折线图 hover 显示正确的日期和数值（浏览器实测：hover 显示 `2022-07-21 / 0.945`，和 `backtest_result.json` 对应点位一致）
- [x] 截面场景下 Decile Return Bar、Turnover、Rank IC、Decile Return Heatmap 正确渲染；单标的场景下这些区块正确地不渲染（不报错、不留空占位）。Symbol Concentration 未能用真实截面 review 数据端到端验证（卡在上面的网络问题上），但代码路径和已验证过的 Cost/Parameter/Regime/Beta finding 渲染逻辑完全一致，按代码走查确认
- [x] Cost Sensitivity / Parameter Perturbation / Regime Decomposition 图表数值和 `review_report.json` 对应 finding 的 `detail` 字段完全一致（浏览器实测：WEAK verdict run 的三张图数值与 research note 里的 verbatim finding 对齐；Regime 阈值线 ±70% 正确标注，Best-days share 44.6% 对应 finding 里的 45%）
- [x] 单标的场景下 Turnover 图表在新产生的 run 上可用（验证后端补丁生效），老 run 打开不报错（老 fork run 无 `turnover` 字段，ChartsPanel 正确跳过该区块，未报错）
- [x] `compare A B` 在 Web 端的 CompareView 显示 Returns Correlation 矩阵；用一对已知父子 fork run 验证——相关系数 0.58（正相关，符合预期：fork 把回看窗口从 3 改成 6，信号有实质变化，不是"几乎不变"，0.58 而非接近 1.0 是合理结果，不是 bug）
- [x] 打开 `.parquet` artifact（比如 `panel.parquet`）能预览前 200 行，而不是只有下载按钮（浏览器实测：`panel.parquet` 显示 "Showing first 200 of 7520 rows"）
- [x] `library/compare.py` 的 `compute_returns_correlation` 有单测（对齐、最小观测数门槛、无 backtest_result.json 场景）；`/api/runs/{id}/artifacts/{filename}/preview` 端点有测试（正常预览、404、非 parquet 拒绝、路径穿越拒绝）
- [x] `uv run pytest` 全量通过（54 passed），含 Phase 0/1/2/3/UI 已有测试（回归不破坏）；`tsc -b`、`vite build`、`oxlint` 全部干净
- [x] 浏览器控制台无报错、无失败网络请求（用 preview 工具跑真实 run 验证；过程中发现并修复一个真实 bug——Regime 图表两条阈值线共用 key 导致 React 重复 key 警告，已修复并重新验证确认无残留）
- [x] 回到 VISION.md 更新 Phase 4 状态；明确标注 Factor IC Heatmap（按标的）和多因子 Risk Attribution 仍然是已知缺口，留给 Phase 5（多资产与高级功能）在有了更丰富的数据源后再做，不是被遗忘

**验证过程中发现并修复的两个额外问题（不在原计划里，但阻塞了 Phase 4 的截面场景）：**
1. **文件名不一致**：截面回测结果曾经存成 `cross_sectional_backtest_result.json`，单标的路径存成 `backtest_result.json`——两个名字不统一，导致 ChartsPanel 和 `compute_returns_correlation` 对截面 run 完全读不到数据。已统一成 `backtest_result.json`（README 文档层面本来就只承诺一个名字），并在 `test_phase1_cross_sectional.py` 加了回归测试锁定文件名。
2. **Regime 图表阈值线 key 重复**：`BarChart`/`LineChart` 的 `thresholds` 渲染用 `threshold.label` 做 key，Regime Decomposition 传了两条都叫 `"warn"` 的阈值线（+70%/-70%），触发 React 重复 key 警告。已改成 `${label}-${index}-${value}` 复合 key，并把两条阈值线的显示文案改成 `+70.0%`/`-70.0%` 而不是都叫 `warn`。

---

*完成 Phase 4 后，回到 [VISION.md](VISION.md) 更新 Phase 5 计划。Phase 5 的多资产支持会为 Risk Attribution 提供真正的因子数据源（不同资产类别的共同风险因子），到时候可以回来把本 Phase 明确留白的"多因子风险归因"补上，而不是在数据基础不具备时勉强凑一个不可信的图。*

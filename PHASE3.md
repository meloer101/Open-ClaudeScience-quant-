# Phase 3 详细实施计划：实验管理（Experiment Library / 对比 / 谱系 / Fork）

> 对应 [VISION.md](VISION.md) 第七节 Phase 3、第 4.2 节对象模型、第 5.5–5.6 节（Experiment Library 与 Session Forking）
> 前置条件：[PHASE0.md](PHASE0.md)、[PHASE1.md](PHASE1.md)、[PHASE_UI.md](PHASE_UI.md)、[PHASE2.md](PHASE2.md) 已完成——每一次 run 都会落盘 `manifest.json`（含 `metrics` + `review.verdict` + `findings`）、`config.yaml`（含 `hypothesis`/`data_path`/`universe`）、`research_note.md`、`review_report.json`，Web 工作台能展示单次 run 的所有 artifact。
> 目标：现在系统能把**单次**实验做正确、做可信，但每个 run 都是一座孤岛——无法回答"我这些实验里哪一类因子最有希望""这个因子从第一版到现在改了什么、结果怎么变的""换个参数会怎样"。Phase 3 要把散落在 `runs/` 里的几十个目录变成一个**可检索、可对比、可追谱系、可分叉**的实验库，让 Phase 2 产出的 `verdict` 从"单次结论"变成"跨 run 的研究记忆"。

---

## 一、为什么现在做，以及和"模型写什么代码写什么"准则的关系

1. **Phase 2 的产出现在被浪费了。** 每个 run 都有一个确定性 `verdict`（STRONG/PROMISING/WEAK/REJECTED）和结构化 `findings`，但它们只躺在各自的 `review_report.json` 里。VISION 第 5.5 节明确要求"系统知道 momentum 类因子在 crypto 4h 上 IC 一般在 0.01–0.03"这种跨 run 知识——没有实验库，这个承诺无法兑现。
2. **VISION 第十一节的准则在 Phase 3 同样吃紧。** 实验库的核心——扫描、索引、筛选、对比、谱系拼接——必须是**确定性、可单测**的代码；模型（LLM）只在最后一步"基于这张已经算好的结构化表，用自然语言总结哪类因子有希望"时介入。绝不能让模型自己去"读一堆 markdown 然后凭印象总结"，那正是 Claude Science 和本项目都要消灭的不可信来源。对应到本 Phase：
   - **代码写（写死、有测试）**：`ExperimentIndex` 扫描 `manifest.json` 建索引、筛选/排序/对比逻辑、`parent_run` 谱系拼接、fork 时的配置继承与"只改信号"约束、对比表和聚合统计的计算。
   - **模型写**：只有两处——(a) fork 时新信号的 `compute()` 代码（和 Phase 0 一样，本来就是模型职责）；(b) 面向实验库的自然语言问答（"哪类因子最有希望"）的**措辞**，而且必须基于代码算好的聚合结果，不允许自己重新统计。
3. **延续 `run_reader` 已确立的架构哲学。** `run_reader.py` 顶部写着"No computation here - this only reads files Coordinator already wrote"——文件系统是唯一真相源。Phase 3 的索引层继续遵守这一点：索引是**从 `manifest.json` 派生、可随时重建**的，不引入需要和文件同步维护的第二真相源。

---

## 二、验收标准（先定终点）

VISION 第七节对 Phase 3 的验收原文：

> **验收标准：** 跑完 20 个因子后，能问"哪些类型的因子在 crypto 上最有希望"，系统基于实验历史给出有数据支撑的回答。

拆成本 Phase 必须跑通的四条能力线 + 一条问答闭环：

### 验收命令 / 场景

1. **实验库检索（CLI + API）**
   ```
   $ python -m quantbench library list --verdict PROMISING,STRONG --sort sharpe
   $ python -m quantbench library list --asset equity --min-sharpe 1.0
   ```
   返回结构化表：`run_id | hypothesis | asset | verdict | sharpe | oos_sharpe | warnings | created_at`，按指定字段排序、按 verdict/asset/sharpe 区间/日期筛选。**筛选和排序结果对同一批 runs 必须完全确定、可单测。**

2. **多 run 对比**
   ```
   $ python -m quantbench compare run_A run_B run_C
   ```
   输出并排对比表：同一组指标（sharpe/annual_return/max_dd/turnover/ic_mean）+ 每个 run 的 verdict + 每条 CRITICAL/WARNING finding 的差异。Web 端提供勾选多个 run → 并排对比视图。

3. **谱系追踪（parent/child）**
   一个 fork 出来的 run，其 `manifest.json` / `config.yaml` 带 `parent_run_id`；实验库能把一条 idea 的多次变体拼成一棵树，并对每一步"改了什么（信号 diff / 参数 diff）→ 指标怎么变、verdict 怎么变"给出确定性对比。

4. **Session Fork（实验分叉）**
   ```
   $ python -m quantbench fork run_A "把回看窗口从20日改成60日"
   ```
   从 `run_A` 分叉：**继承** `data_path` / `universe` / `date_range`（不重新拉数据、不重新构建 universe），**只让模型重写 `compute()`**；新 run 落盘时记录 `parent_run_id = run_A`。Web 端在任意 run 详情页有"Fork this run"入口。

5. **问答闭环（验收原句）**
   ```
   $ python -m quantbench "在我做过的所有实验里，哪一类因子在美股上最有希望？"
   ```
   系统必须：先用**代码**从实验库聚合出按 `factor_family × asset × verdict` 的统计表（数量、sharpe 分布、oos 衰减、cost 敏感占比），把这张表喂给模型，模型只做解读和排序措辞——回答里出现的每一个数字都必须能在聚合表里对上，不允许模型自行编造统计量。

### 两个具体正确性测试场景

- **谱系正确性**：`fork A → B`，`fork B → C`，实验库查询 C 的谱系必须返回 `A → B → C` 有序链，且 A→B、B→C 两段各自的信号 diff 非空、指标 delta 计算正确。
- **索引不漂移**：手动删掉一个 run 目录 / 新增一个 run 后，重建索引，`library list` 结果随之变化且与文件系统完全一致（索引是派生物，不是需要手工维护的真相源）。

---

## 三、数据模型：索引记录与谱系

### 3.1 `ExperimentRecord`（索引的原子行，纯从 manifest 派生）

```python
@dataclass(frozen=True)
class ExperimentRecord:
    run_id: str
    hypothesis: str            # config.hypothesis / manifest.user_request
    created_at: str            # manifest.created_at
    status: str                # completed | failed | running（复用 run_reader.get_status）
    asset_class: str           # "equity" | "crypto" | "unknown"（见 3.3 分类）
    factor_family: str         # "momentum" | "reversal" | "value" | ... | "unclassified"
    cross_sectional: bool
    # 指标（缺失即 None，绝不填 0）
    sharpe: float | None
    annual_return: float | None
    max_drawdown: float | None
    turnover_annual: float | None
    ic_mean: float | None
    oos_sharpe: float | None   # 从 review.findings[out_of_sample].detail.test_metrics.sharpe 提取
    # 审查
    verdict: str | None        # STRONG | PROMISING | WEAK | REJECTED | None(无review)
    critical_count: int
    warning_count: int
    # 谱系
    parent_run_id: str | None
```

**关键约束**：`ExperimentRecord` 只有一个来源——`read_manifest(run_id)`（外加 `config.yaml` 补 `data_path`/`universe`）。没有任何字段是"另外维护"的；索引整体 = `for run_id in list_run_ids(): build_record(run_id)`，随时可重建。

### 3.2 谱系拼接

`parent_run_id` 是唯一的谱系边。`ExperimentIndex.lineage(run_id)` 用它向上回溯到根、向下收集所有后代，输出一棵有序树。**不引入单独的 lineage 存储文件**——树完全由各 run manifest 里的 `parent_run_id` 反算出来（同样是派生物，删一个 run 只影响那条边）。

### 3.3 `asset_class` / `factor_family` 分类——诚实对待"判断力边界"

这是本 Phase 最容易违反第十一节准则的地方，必须谨慎：

- **`asset_class`**：**确定性代码**分类，不靠模型。规则和 Phase 1/2 的 provider 路由一致——按 symbol 形状：含 `/`（如 `BTC/USDT`）→ crypto；纯字母 ticker（`AAPL`/`SPY`）或 `universe.provider == "yfinance_equity"` → equity；都不匹配 → `unknown`。symbol 从 `config.data_path` 文件名 / `config.universe` 提取（已有稳定命名，见 `data_cache/yfinance_equity_AAPL_1d_*.parquet`）。
- **`factor_family`**：**不假装精确聚类。** v1 采用"显式优先、保守兜底"：
  1. 若 fork/run 时用户或 Coordinator 在 config 里写了 `factor_family`，直接采用；
  2. 否则用一个**关键词白名单**从 `hypothesis` 里做保守匹配（"动量/momentum"→momentum，"反转/reversal/RSI"→reversal，"价值/value"→value，"波动/vol"→volatility…），命中才归类；
  3. 都不命中 → `"unclassified"`，**绝不猜**。
  这条边界直接对应第十一节："因子怎么分类"里真正需要判断力的部分不硬塞给脆弱的关键词规则，宁可标 `unclassified` 也不给一个看起来精确其实拍脑袋的标签。（后续 Phase 可引入模型辅助打标，但要作为"模型写"的显式步骤、可复核，不混进确定性索引里。）

---

## 四、模块拆解

新增一个 `quantbench/library/` 包（与 `review/` 平级），职责单一、每个模块可单测：

| 文件 | 职责 | 属于"代码写" |
|---|---|---|
| `library/record.py` | `ExperimentRecord` + `build_record(run_id)`（从 manifest/config 派生，含指标与 oos_sharpe 提取） | ✅ |
| `library/index.py` | `ExperimentIndex`：`build()` 扫描全部 run、`filter(...)`、`sort(...)`、`get(run_id)`；纯内存、可重建 | ✅ |
| `library/compare.py` | `compare_runs([run_id...])` → 结构化对比表（指标并排 + verdict + finding 差异） | ✅ |
| `library/lineage.py` | `lineage(run_id)` 拼谱系树；`diff_signals(a,b)`（signal.py 文本 diff）；`diff_metrics(a,b)`（指标 delta） | ✅ |
| `library/aggregate.py` | `summarize(by=["factor_family","asset_class"])` → 每组的 count / verdict 分布 / sharpe 分布 / oos 衰减占比 / cost 敏感占比。**这是喂给问答的那张表** | ✅ |
| `library/fork.py` | `build_fork_config(parent_run_id)`：读父 run config，抽出可继承的 `data_path`/`universe`/`date_range`/`timeframe`，产出 fork 的 seed config | ✅ |

### 4.1 Coordinator / Fork 集成

- **`config.yaml` / `manifest.json` 新增 `parent_run_id` 字段**（默认 `None`）。在 `coordinator.py` 的 `config = {...}`（约 [coordinator.py:475](quantbench/agent/coordinator.py:475)）和 `run.finalize(...)`（约 [coordinator.py:517](quantbench/agent/coordinator.py:517)）各加一个可选参数透传。`artifact/store.py` 的 `finalize()` 增加 `parent_run_id` 参数写入 manifest。
- **Fork 执行路径**：新增 `Coordinator.run_fork(parent_run_id, modification_request)`：
  1. `build_fork_config(parent_run_id)` 拿到继承的数据/universe 配置；
  2. 构造一个特殊的 system/user prompt：告诉模型"这是从 run X 分叉，数据与 universe 已固定为 …，父信号代码如下 …，你只需要按以下修改重写 `compute()`"，**不给数据拉取和 universe 构建工具**（或让这些工具在 fork 模式下直接返回已固定的父配置结果），从机制上保证"只改信号"；
  3. 复用现有 backtest→review→finalize 主链路，落盘时带上 `parent_run_id`。
- **"只改信号"的保证方式**（技术决策见第六节）：fork 模式下 Coordinator 不重新执行 `fetch_ohlcv`/`build_universe`，而是直接把父 run 的 `data_path`/`panel.parquet` 作为既定输入注入 `ctx`，模型能调用的工具收敛到"写信号 + 跑回测"。

### 4.2 Research Note / 知识沉淀

- `skills/report.py`：research note 顶部若 `parent_run_id` 非空，新增一段"## 谱系"，写明父 run、相对父 run 的信号 diff 摘要和关键指标 delta（STRONG/…verdict 变化）。这部分文本由 `library/lineage.py` 的确定性 diff 生成，report 只做排版。
- **失败原因沉淀**：`status == "failed"` 的 run 也进索引（`verdict=None`，带 `error` 摘要），这样"这个因子试过、失败在哪"也是可检索的知识，而不是只留一个 `error.json` 在角落。

### 4.3 问答闭环（第二节场景 5）

- 在 `prompts.py` / Coordinator 增加一个"实验库问答"模式：当用户的问题是关于"历史实验/哪类因子/我做过的"这类跨 run 检索时，Coordinator 先调用 `aggregate.summarize(...)` 拿到确定性聚合表，作为工具结果注入，再让模型基于这张表作答。
- **强约束（写进 `prompts.py`，与 Phase 2 的 verdict 约束同级）**：面向实验库的回答，其中任何数字/排名都必须来自注入的聚合表，不得自行统计或估计；样本量过小的组（如某 family 只有 1 个 run）必须显式标注"样本不足，不足以下结论"，不许拿单个 run 冒充"一类因子的规律"。

---

## 五、API 与 Web 改动

### 5.1 API（`quantbench/api/`）

沿用 `server.py` 现有的 FastAPI 文件读取风格，新增只读检索端点 + 一个 fork 写入端点：

| 方法 & 路径 | 说明 |
|---|---|
| `GET /api/library` | 返回 `ExperimentRecord[]`，支持 query 参数 `verdict`/`asset`/`factor_family`/`min_sharpe`/`sort`（筛选排序在服务端 `ExperimentIndex` 完成，前端不做统计） |
| `GET /api/library/summary` | 返回 `aggregate.summarize()` 的分组统计表 |
| `GET /api/runs/{run_id}/lineage` | 返回该 run 的谱系树 + 每条边的信号 diff / 指标 delta |
| `GET /api/compare?run_ids=A,B,C` | 返回 `compare_runs` 的结构化对比表 |
| `POST /api/runs/{run_id}/fork` | body `{modification: str}`；走 `RunManager.fork(...)`（在 `run_manager.py` 增加 `fork()`，与现有 `submit()` 同样后台线程 + SSE 事件），返回新 `run_id` |

`schemas.py` 增加对应 Pydantic 模型（`ExperimentRecord`/`LineageNode`/`CompareTable`/`ForkRequest`）。

### 5.2 Web（`web/src/`）

- **Sidebar → Experiment Library 视图**：把现有 run 列表升级为可筛选/排序的实验库表（verdict 徽章、sharpe 列、asset/family 过滤器）。复用现有 `Sidebar.tsx` + `api/client.ts`。
- **多选对比**：run 列表支持勾选多个 → 打开并排 `CompareView`（新增组件），消费 `/api/compare`。
- **谱系视图**：run 详情页新增"Lineage"标签，渲染 `A → B → C` 树 + 每步 diff（消费 `/api/runs/{id}/lineage`）。
- **Fork 入口**：run 详情页加"Fork this run"按钮 → 输入修改意图 → `POST .../fork` → 新 run 沿用现有 `useRunEvents` / `LiveProgress` 展示实时进度（fork 出的 run 和普通 run 在进度展示上完全一致）。

**验收原则同 Phase UI**：这些是把已经算好的确定性结构展示出来，前端不承担任何统计/判定逻辑。

---

## 六、按日拆解（预计 9–10 个工作日）

| Day | 任务 | 产出 |
|---|---|---|
| **Day 1** | `library/record.py`：`ExperimentRecord` + `build_record`，含从 `review.findings` 提取 `oos_sharpe`、`asset_class` 确定性分类、`factor_family` 保守白名单分类 + 单测（用 `runs/` 里已有的真实 manifest 做 fixture，覆盖 crypto/equity/缺 review/failed 四种） | 单个 run 能被无歧义地映射成一行记录 |
| **Day 2** | `library/index.py`：`build()`/`filter()`/`sort()`，全部纯函数、可重建；单测覆盖"删除/新增 run 后重建索引结果随文件变化"（第二节的索引不漂移场景） | `library list` 的后端逻辑可用且确定 |
| **Day 3** | CLI：`python -m quantbench library list ...`（筛选/排序参数解析）；`__main__.py` / `cli.py` 增加 `library` 子命令 + 端到端 CLI 测试 | 验收命令 1 跑通 |
| **Day 4** | `library/compare.py` + CLI `compare A B C` + 单测（指标并排、verdict、finding 差异对齐） | 验收命令 2 跑通 |
| **Day 5** | `parent_run_id` 贯通：`artifact/store.py` finalize、`coordinator.py` config/finalize 透传；`library/lineage.py`（谱系拼接 + `diff_signals` + `diff_metrics`）+ 单测（手工构造 A→B→C manifest 验证有序链与 diff） | 谱系可查询，第二节谱系正确性场景通过 |
| **Day 6** | `library/fork.py`（`build_fork_config`）+ `Coordinator.run_fork` + fork 模式下"只给写信号+回测工具"的收敛机制 + 单测（fork 出的 run 数据/universe 与父一致、只有 signal 变化、`parent_run_id` 正确写入） | 验收命令 4（CLI fork）跑通 |
| **Day 7** | `library/aggregate.py`（`summarize`）+ 单测（每组 count/verdict 分布/sharpe 分布/oos 衰减占比计算正确；小样本组正确标记） | 问答所需的确定性聚合表可用 |
| **Day 8** | 问答闭环：`prompts.py` 增加实验库问答模式 + 强约束；Coordinator 在跨 run 问题上先注入 `summarize` 结果再作答 + 端到端测试（构造多个已知 verdict 的 run，问"哪类因子最有希望"，断言回答里的数字与聚合表一致、小样本组被标注） | 验收命令/场景 5 跑通 |
| **Day 9** | API：`/api/library`、`/api/library/summary`、`/api/runs/{id}/lineage`、`/api/compare`、`POST .../fork`（`run_manager.fork`）+ `schemas.py` 模型 + API 测试（复用现有 TestClient 风格） | 后端全部端点可用且有测试 |
| **Day 10** | Web：Sidebar 升级为实验库表 + 多选对比 `CompareView` + 谱系标签 + Fork 入口；`research_note.md` 谱系区块；`uv run pytest` 全量回归；更新 VISION.md Phase 3 状态、README "已支持能力" | 完整实验库 Web 体验；全量测试通过；文档更新 |

---

## 七、关键技术决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| 索引存哪里 | **不建独立数据库/索引文件，运行时从 `manifest.json` 扫描重建** | 延续 `run_reader` 的"文件是唯一真相源"哲学；避免索引与文件不同步的漂移 bug（这正是第十一节反复强调、最容易系统性出错的一类）。单用户几十到几百个 run，扫描成本可忽略；真到性能瓶颈再加缓存层，但缓存必须可从文件重建 |
| 是否复用 Phase 1 的 DuckDB | v1 **不用**，纯 Python 内存索引 | DuckDB warehouse 是给行情面板数据用的（大表、列式分析）；实验库是几百行元数据，用 DuckDB 反而增加"第二真相源 + 同步"负担。保持索引=派生物这一性质更重要 |
| `factor_family` 怎么定 | **显式优先 + 关键词白名单兜底，不命中标 `unclassified`** | 严守第十一节：真正需要判断力的分类不硬塞给脆弱规则，宁标"未分类"也不给假精确标签。避免实验库因为分类不可信而整体不可信（和 Phase 2 未来函数检测宁可漏报不可误报同一逻辑） |
| Fork 如何保证"只改信号" | **机制上收敛可用工具**：fork 模式下注入父 run 的 data/universe，不给数据拉取/universe 构建工具，模型只能写信号+跑回测 | 比"提示模型请不要重新拉数据"可靠得多——和 Phase 2"Reviewer 做成自动步骤而非可选工具"同一思路：不给模型跳过/偏离的机会 |
| 谱系怎么存 | **只存一条 `parent_run_id` 边，树反算得出** | 单向父指针足以重建整棵树；不冗余存 children 列表，避免删 run 后 children 指针悬空 |
| 失败 run 是否进库 | **进**，`verdict=None` + error 摘要 | "试过、失败在哪"本身是研究知识（VISION 5.5 明确要"失败原因记录和知识沉淀"）；否则实验库只剩幸存者，本身就是一种 survivorship bias |
| 问答的数字由谁算 | **代码算（`aggregate.summarize`），模型只解读** | 直接落实第十一节：跨 run 统计是"必须绝对正确"的基础设施，不能让模型自己数 run、自己算平均 sharpe |
| CLI vs Web 先后 | **CLI/API 先（Day 3–9），Web 最后（Day 10）** | 检索/对比/谱系/fork 的正确性靠 CLI + 单测锁定；Web 只是把已算好的结构展示出来，放最后不影响正确性验收 |

---

## 八、风险与应对

| 风险 | 应对 |
|---|---|
| `factor_family` 关键词分类误伤或漏归类，导致"哪类因子最有希望"的聚合表本身不可信 | 白名单只做高置信度匹配，不命中即 `unclassified`；聚合表对 `unclassified` 单列展示、不并入任何 family；问答强约束要求模型对小样本/未分类组显式声明"不足以下结论"。分类规则集中在 `record.py` 顶部具名常量，便于校准 |
| Fork 时模型仍试图重新拉数据或改动 universe，破坏"变量唯一"（除信号外一切不变）这个 fork 的意义 | 机制上收敛工具集，而非靠提示词约束；fork 落盘后加一道断言/检查：新 run 的 `data_hash` 必须等于父 run 的 `data_hash`，否则该 run 标记 warning "fork data drift"，不静默通过 |
| 老 run（Phase 2 之前产生的）`manifest.json` 没有 `review`/新字段，进索引时报错或被算成 0 | `build_record` 对所有字段做缺失即 `None` 处理（复用 `read_manifest` 已有的 backfill 思路，见 [run_reader.py:76](quantbench/api/run_reader.py:76)）；单测显式覆盖"无 review 的老 manifest"这一 fixture |
| 谱系链断裂：父 run 目录被删，child 的 `parent_run_id` 指向不存在的 run | `lineage()` 遇到悬空指针时截断并在结果里标记 `parent_missing`，不抛异常、不无限回溯；单测覆盖悬空父指针 |
| 对比/聚合把 `None` 指标当 0 参与排序或求均值，得出错误结论 | 所有排序/聚合显式区分"缺失"和"0"：缺失值不参与均值、排序时沉底并标注；这是从 VISION 数据诚实原则延伸的硬性要求，单测专门验证含 `None` 的输入 |
| Web 端把统计/判定逻辑写进前端（如前端自己算平均 sharpe），造成与后端不一致的第二真相源 | 前端只渲染 API 返回的结构；`/api/library` `/api/compare` `/api/library/summary` 就是唯一计算入口。code review 时专门检查前端有无自算统计量 |

---

## 九、Phase 3 完成后的检查清单

- [ ] `python -m quantbench library list`（含 `--verdict`/`--asset`/`--min-sharpe`/`--sort`）跑通，输出与文件系统一致、排序确定
- [ ] `python -m quantbench compare A B C` 输出并排指标 + verdict + finding 差异
- [ ] `python -m quantbench fork <run> "<修改>"` 产出新 run，`config.yaml`/`manifest.json` 带正确 `parent_run_id`，且新 run 的 `data_hash` 等于父 run（数据未漂移）
- [ ] `fork A→B→C` 后，谱系查询返回有序 `A→B→C`，每段信号 diff 非空、指标 delta 正确（第二节谱系正确性场景）
- [ ] 删除/新增一个 run 后重建索引，`library list` 结果随之改变且与文件系统一致（索引不漂移场景）
- [ ] 问"在我做过的实验里哪类因子在美股上最有希望"，回答中的每个数字都能在 `summarize` 聚合表里对上，小样本/未分类组被显式标注为"不足以下结论"
- [ ] 失败的 run 也出现在实验库里（`verdict=None` + error 摘要），不是只留 `error.json`
- [ ] `research_note.md` 对 fork 出的 run 新增"谱系"区块（父 run + 信号 diff 摘要 + 指标 delta）
- [ ] `library/` 下每个模块（record/index/compare/lineage/aggregate/fork）有独立单测；API 端点有测试
- [ ] Web：实验库表（筛选/排序/verdict 徽章）、多选对比视图、谱系标签、Fork 入口均可用，且前端不含任何自算统计逻辑
- [ ] `uv run pytest` 全量通过，含 Phase 0/1/2/UI 已有测试（回归不破坏）
- [ ] 回到 VISION.md 更新 Phase 3 状态；回顾 Phase 4/5（更丰富可视化、多资产、自定义 skill）是否需要因 `ExperimentIndex`/`ExperimentRecord` 的字段结构做调整

---

*完成 Phase 3 后，回到 [VISION.md](VISION.md) 更新 Phase 4+ 计划。Phase 3 交付的实验库是后续所有"研究记忆"能力的地基：Phase 4 的高级可视化（IC 热力图、风险归因）会作为 artifact 进入同一套索引；Phase 5 的自定义 skill 与多资产会扩展 `asset_class`/`factor_family` 的取值空间，但索引"从文件派生、确定性计算、模型只解读"的架构不变。*

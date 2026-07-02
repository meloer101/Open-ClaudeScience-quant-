# Phase 6 详细实施计划：因子库（Factor Library）——把验证过的因子沉淀成可复用起点

> 对应 [VISION.md](VISION.md) 第六节"用户自定义技能"里的**因子部分**（`@quantbench.skill("my_momentum_factor")` 那个示例），第 4.2 节对象模型里的 `Signal / Factor`
> 前置条件：[PHASE0.md](PHASE0.md)～[PHASE5.md](PHASE5.md) 已完成——每次 run 都会落盘 `signal.py`（含 `compute(df)`）、`review_report.json`（含 verdict）、`manifest.json`（含 metrics + config），并进入 Phase 3 的实验库索引。
> **重要范围澄清（来自和用户的讨论）：** 本项目里"因子库"和"Skills"是**两套独立的东西**，不是一套改名字。本文档只做**因子库**：把跑通、经 Reviewer 审查过的**因子代码**沉淀下来，允许存参数小变体，作为下次做类似因子的**参考起点**。而"Skills"（调查/写代码/排查的工作流规范，像 Claude Code / Codex 里的 Skills 那样靠 description 语义匹配、加载后注入指导性内容）是完全不同的机制，见 [PHASE7.md](PHASE7.md)，本文档不涉及。

---

## 一、先把"因子库"和"Skills"的区别钉死——这是不做错方向的前提

和用户反复澄清后确定的两条边界，写在最前面防止实现时混淆：

| | 因子库（本文档 Phase 6） | Skills（[PHASE7.md](PHASE7.md)） |
|---|---|---|
| **存什么** | 一段具体的、跑通且审查过的**因子代码** `compute(df)`，相对确定 | **工作流/业务规范**——怎么构建 crypto 截面 universe、Reviewer 给 WEAK 之后怎么排查、怎么写不带未来函数的因子 |
| **触发/使用方式** | 用户或模型**主动查询**因子库（按 factor_family / verdict / asset 检索），调出一份跑通的参考实现当起点去改 | 靠 description **语义匹配**当前研究意图，自动加载、往上下文注入**指导性内容**，模型看了自己写 |
| **本质** | 一份**带元数据的代码档案**（代码 + 参数 + 当时的 verdict/指标 + 已知局限） | 一份**指令/提示词文档**（怎么做这类工作，不含具体因子代码） |
| **可变性** | 允许存参数小变体（同一因子 `lookback=10/20/60` 各存一版），调出来还能继续改——不锁死成固定签名的可调用函数 | 天然是文本，随时改 |

**关键：不做成"注册成固定签名的可调用工具"。** 用户明确否定了 `@quantbench.skill` 那种把因子锁成 `compute_momentum(data, lookback=24)` 固定函数、注册进 `SkillRegistry` 让模型直接调用的做法——因为不同场景下这段代码还是要调试、改动，锁死反而限制灵活性。因子库存的是**可被检索、可被复制来改**的代码档案，不是 tool-calling 意义上的新工具。模型能调用的工具仍然只有现有那四个（`fetch_ohlcv`/`run_signal_backtest`/`build_universe`/`run_cross_sectional_backtest`）。

---

## 二、为什么现在做，以及和"模型写什么代码写什么"准则的关系

1. **实验库已经攒了一批验证过的因子，但它们只能被"看"，不能被"复用"。** Phase 3 的实验库能检索、对比、看谱系，但一个跑出 STRONG/PROMISING 的因子，下次想在别的资产/时间段上再试，只能靠人去翻 `runs/<id>/signal.py` 复制粘贴。VISION 第六节明确承诺"用户可以将任何 pipeline 保存为可复用技能，未来所有 session 自动可用"——因子库就是兑现这个承诺的因子那一半。
2. **VISION 第十一节准则在这里的落点很微妙，要讲清楚：** 因子逻辑本身是"模型写"的（研究创意），这没变。因子库做的是把某一次"模型写对了、且审查通过了"的产物**固化成档案**，让下一次不必从零重想——但调出来之后，改不改、怎么改，仍然是模型/用户的判断，因子库不替它做决定。所以因子库本身（存储、检索、参数提取）是"代码写"的确定性基础设施；被存的因子代码是"模型写"的创意产物。两者不矛盾。
3. **"能不能收藏"要挂钩 Reviewer verdict，不是只看 Sharpe。** 这是整个项目最核心的立场——"可信"而不是"看起来赚钱"。一个 Sharpe 很高但被 Reviewer 打成 REJECTED 的因子（比如未来函数没剔干净）绝不该进因子库。收藏的默认门槛设为 verdict 不是 REJECTED（即 STRONG/PROMISING/WEAK 可收藏，REJECTED 默认拦截），WEAK 允许收藏但打标警示，理由见第六节技术决策。

---

## 三、验收标准（先定终点）

**验收命令（复用已有的 CLI 子命令模式，Phase 3 已经建立了 `library list`/`compare` 这种风格）：**

```
# 1. 从一个跑通的 run 收藏因子（自动提取参数、记录 verdict/指标）
$ python -m quantbench factor save <run_id> --name momentum_20d

# 2. 列出因子库（可按 family/asset/verdict 筛选，和实验库检索一致）
$ python -m quantbench factor list --family momentum --min-verdict PROMISING

# 3. 调出一个因子的完整档案（代码 + 参数 + 当时的 verdict/指标 + 已知局限）
$ python -m quantbench factor show momentum_20d

# 4. 从因子库里已有因子起一个新 run（继承代码当起点，可改参数）
$ python -m quantbench factor use momentum_20d --param lookback=60 --on "在AAPL上测试，2020-2024"
```

系统必须：
1. `factor save` 从 `runs/<run_id>/` 读 `signal.py` + `review_report.json` + `manifest.json`，提取因子代码、Reviewer verdict、关键指标、可扰动的数值参数（复用 [review/parameter_stability.py](quantbench/review/parameter_stability.py) 已有的 `find_perturbable_literals`），存成一个因子库条目；REJECTED 的 run 默认拒绝收藏并说明原因（可 `--force` 覆盖但会打标）
2. `factor list` 输出结构化表：`name | family | asset | source_verdict | source_sharpe | param_summary | saved_at`
3. `factor show` 输出完整档案，包括 VISION 承诺的"已知局限"——直接复用 source run 的 Reviewer findings（比如"参数敏感"、"regime 集中在 2023"），这些是最有价值的复用信息
4. `factor use` 从因子库条目的代码起一个新 run：把因子代码作为起点注入，`--param` 覆盖对应的数值字面量（复用 `parameter_stability.py` 的 `perturb_code` 同类 AST 替换逻辑），然后走正常的 backtest→review→实验库归档流程；新 run 的 config 记录 `derived_from_factor: momentum_20d`（谱系可追溯，和 Phase 3 的 `parent_run_id` 一个思路）

### 正确性测试场景

- **verdict 门槛确定性**：一个 REJECTED 的 run，`factor save` 默认必须拒绝（返回清晰错误），`--force` 才能存且条目上带 `saved_from_rejected: true` 标记——不能让不可信的因子悄悄进库。
- **参数提取与覆盖往返**：`factor save` 一个含 `pct_change(20)` 的因子，提取出参数 `20`；`factor use --param <that>=60` 起的新 run，其 `signal.py` 里必须是 `pct_change(60)`，且这个新 run 能独立跑通。
- **不污染实验库检索**：因子库是独立的存储（`factors/` 目录 + JSON 索引），`library list`（Phase 3）的行为不受影响——因子库消费实验库的数据，但不反向改写它。

---

## 四、数据模型：`FactorEntry`

```python
@dataclass(frozen=True)
class FactorEntry:
    name: str                      # 用户指定的唯一名字，如 "momentum_20d"
    family: str                    # 复用 record.py 的 factor_family 分类
    asset_class: str               # 复用 record.py 的 asset_class
    code: str                      # signal.py 里的 compute(df) 源码
    parameters: list[dict]         # [{"value": 20.0, "lineno": 3}, ...] 来自 find_perturbable_literals
    # 溯源（收藏时刻的快照，不随 source run 变化）
    source_run_id: str
    source_verdict: str | None     # 收藏时 source run 的 verdict
    source_metrics: dict           # sharpe / oos_sharpe / ic_mean 等
    source_findings: list[dict]    # Reviewer 的 CRITICAL/WARNING findings —— 这就是"已知局限"
    saved_from_rejected: bool      # --force 收藏 REJECTED 时为 True
    saved_at: str
    notes: str = ""                # 用户可选的自由文字备注
```

**为什么快照而不是引用 source run**：source run 的目录以后可能被删、可能被 fork 出别的东西，但因子库条目要能独立存在、独立复现。存收藏那一刻的 verdict/findings 快照，和 Phase 3 fork 时 `build_fork_config` 快照父配置是同一个设计原则（见 PHASE3.md）。

**存储**：`factors/<name>.json`，外加 `factors/INDEX.json`（一行一条的轻量索引，加载快、可从 `factors/*.json` 重建）——延续 Phase 3 实验库"文件是唯一真相源、索引是可重建派生物"的哲学（见 PHASE3.md 技术决策）。

---

## 五、模块拆解

新增 `quantbench/factors/` 包（与 `library/` 平级）：

| 文件 | 职责 | "代码写"？ |
|---|---|---|
| `factors/entry.py` | `FactorEntry` dataclass + `build_entry_from_run(run_id, name)`（从 `signal.py`/`review_report.json`/`manifest.json` 提取，含 verdict 门槛检查） | ✅ |
| `factors/store.py` | `save_factor(entry)` / `load_factor(name)` / `list_factors(filters)` / `delete_factor(name)`；`factors/` 目录读写 + INDEX.json 维护 | ✅ |
| `factors/parametrize.py` | 复用 `review/parameter_stability.py` 的 `find_perturbable_literals`/`perturb_code`，封装成"提取因子参数"和"按 name=value 覆盖参数生成新代码"两个函数 | ✅ |

### 5.1 CLI 集成（`quantbench/cli.py`）

沿用 Phase 3 已经建立的子命令解析风格（`library list`/`compare` 那套 `args[:2] == (...)` 分发，见 cli.py），新增 `factor save/list/show/use` 四个子命令。`factor use` 内部调用一个新的 Coordinator 入口。

### 5.2 Coordinator 集成：`run_from_factor`

新增 `Coordinator.run_from_factor(factor_name, param_overrides, request)`：
- `load_factor(factor_name)` 拿到因子代码，`parametrize.apply_overrides(code, param_overrides)` 应用参数改动
- 构造一个 seed prompt：告诉模型"这是从因子库 `<name>` 起的 run，参考代码如下（已应用你指定的参数改动），source run 当时的 verdict 是 X、已知局限是 Y、Z，请在用户新要求的数据/场景上把它跑起来，必要时可微调代码"
- **关键：仍然走正常的 tool-calling 循环**（模型可以进一步改代码、选数据、跑 backtest），不是"锁死参数直接执行"——这正是用户强调的"不要定得太死，还要能调试改动"
- 新 run 的 config 记 `derived_from_factor: <name>`，实验库里可检索"哪些 run 是从这个因子衍生的"

### 5.3 实验库联动（可选，低优先）

`library/record.py` 的 `build_record` 可顺带读 config 里的 `derived_from_factor`，让 Phase 3 的实验库能显示"这个 run 源自哪个因子库条目"。这是锦上添花，不阻塞主线。

---

## 六、关键技术决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| 因子库 vs 固定可调用工具 | **代码档案，不注册成 tool** | 用户明确要求：因子要能调出来继续改，不锁死成固定签名函数；模型能调的工具仍是现有四个 |
| 收藏门槛 | **默认拒绝 REJECTED，WEAK 可存但打标，`--force` 可覆盖** | 落实"可信而非好看"的核心立场；但不做成硬性只准 STRONG——研究中 WEAK 的因子也有参考价值（知道此路不太通也是知识），只是要如实标注 |
| 参数怎么提取 | **复用 `find_perturbable_literals`（绝对值≥2 的数值字面量）** | 不重新发明轮子；Reviewer 的参数稳定性检查已经用这套逻辑扰动过参数，因子库用同一套保证"能扰动的"和"能覆盖的"是同一批参数，语义一致 |
| 已知局限从哪来 | **直接快照 source run 的 Reviewer findings** | 这是因子库最有价值的部分——不只存"这因子怎么写"，还存"它有什么坑"（参数敏感、regime 集中等），下次复用时一眼看到，避免重复踩坑 |
| 溯源用快照还是引用 | **快照** | source run 可能被删/被 fork；因子库条目要能独立复现，和 Phase 3 fork 快照父配置同一原则 |
| 存储形式 | **`factors/*.json` + 可重建的 INDEX.json** | 延续 Phase 3 "文件是唯一真相源、索引是派生物"，不引入数据库 |
| `factor use` 是否锁死执行 | **不锁死，仍走完整 tool-calling 循环** | 用户强调"因子还要能调试改动"；`factor use` 是"给模型一个跑通的起点"，不是"照参数执行一个固定函数" |

---

## 七、明确不做的事

| 不做 | 原因 |
|---|---|
| 把因子注册成 `SkillRegistry` 里可被模型直接调用的新 tool | 用户明确否定；因子库是可检索、可复制来改的档案，不是新增 function-calling 工具 |
| 工作流/业务规范类的 Skills | 那是 [PHASE7.md](PHASE7.md) 的事，两套独立机制，不在本文档 |
| 因子组合 / 多因子合成 | 属于 VISION Phase 5 的"组合优化"，是独立能力，不塞进因子库 |
| 自动判断"这个因子值不值得收藏" | 收藏是用户主动动作（`factor save`）；系统只做 verdict 门槛这种确定性拦截，不替用户判断因子好坏 |
| 因子库条目的版本管理 / diff | v1 一个 name 一个条目，重名默认报错（`--overwrite` 可覆盖）；不做 git 式的版本历史，避免过度设计 |

---

## 八、按日拆解（预计 5-6 个工作日）

| Day | 任务 | 产出 |
|---|---|---|
| **Day 1** | `factors/entry.py`：`FactorEntry` + `build_entry_from_run`（提取代码/verdict/metrics/findings/参数，含 verdict 门槛）+ 单测（STRONG 可存、REJECTED 默认拒绝、`--force` 打标、参数提取正确） | 单个 run 能被无歧义地映射成因子条目 |
| **Day 2** | `factors/store.py`：save/load/list/delete + INDEX.json 维护 + 单测（含索引可从 `*.json` 重建） | 因子库存储层可用 |
| **Day 3** | `factors/parametrize.py`：封装 `find_perturbable_literals`/`perturb_code` 成"提取参数"/"按 name=value 覆盖" + 单测（`pct_change(20)`→提取 20→覆盖成 60 往返正确） | 参数提取/覆盖可信 |
| **Day 4** | CLI `factor save/list/show` 三个只读+收藏子命令 + 端到端 CLI 测试 | 验收命令 1/2/3 跑通 |
| **Day 5** | `Coordinator.run_from_factor` + CLI `factor use`（应用参数覆盖、注入参考代码+已知局限、走完整 tool 循环、记 `derived_from_factor`）+ 端到端测试（mock LLM 验证参数被正确应用、新 run 能跑通并归档） | 验收命令 4 跑通 |
| **Day 6**（缓冲） | 实验库联动（`build_record` 读 `derived_from_factor`）；用真实的历史 run（Phase 5 跑出的动量因子）实际收藏一次、再 `factor use` 起个新 run 验证端到端；更新 VISION.md 第六节状态、README | 真实数据下端到端可用，文档同步 |

---

## 九、风险与应对

| 风险 | 应对 |
|---|---|
| 用户 `--force` 收藏了 REJECTED 因子，以后忘了它不可信，`factor use` 时又踩一遍坑 | 条目上 `saved_from_rejected: true` 永久保留；`factor show`/`factor use` 时把这个标记和当时的 CRITICAL findings 醒目地打出来，不让它悄悄混进"看起来正常"的因子里 |
| `find_perturbable_literals` 只认绝对值≥2 的数值字面量，漏掉字符串/布尔参数（如 `vol_filter=True`），或参数是运算得出 | 这是 Reviewer 参数稳定性检查已经接受的 v1 局限（见 PHASE2.md），因子库沿用同一局限、保持语义一致；`factor show` 显式说明"可覆盖参数仅限被提取到的数值字面量"，不假装能覆盖全部 |
| `factor use` 改了参数后新 run 语义错乱（比如把百分比换算的 100 当参数改了） | 复用 `parameter_stability.py` 已经踩过这个坑的经验（它扰动后跑失败会标记跳过）；`factor use` 应用覆盖后先跑一次 sanity 检查，明显不合理就报清晰错误而不是静默产出坏结果——延续 Phase 5 那次"分组数不够静默产出 0.0 Sharpe"教训里确立的"宁可清晰报错不要静默错"原则 |
| 因子库和实验库两套存储职责混淆 | 因子库**只读消费**实验库/runs 的数据，绝不反向改写；`factors/` 和 `runs/` 完全隔离，删因子库不影响任何 run |
| 重名因子覆盖丢失旧条目 | `factor save` 遇到重名默认报错，`--overwrite` 才覆盖；不静默替换 |

---

## 十、Phase 6 完成后的检查清单

- [ ] `factor save <run_id> --name X` 能从跑通的 run 收藏因子，REJECTED 默认拒绝、`--force` 打标
- [ ] `factor list` 输出结构化表，可按 family/asset/verdict 筛选
- [ ] `factor show X` 显示完整档案，含从 source run 快照来的"已知局限"（Reviewer findings）
- [ ] `factor use X --param lookback=60 --on "..."` 能应用参数覆盖、起一个新 run、跑通并归档进实验库，config 带 `derived_from_factor`
- [ ] verdict 门槛正确性测试通过（REJECTED 默认拦截、`--force` 打标）
- [ ] 参数提取/覆盖往返测试通过（`pct_change(20)`→提取→覆盖成 60→新 run 的 signal.py 确实是 60）
- [ ] `factors/` 每个模块（entry/store/parametrize）有独立单测；INDEX.json 可从 `*.json` 重建
- [ ] 因子库不污染 Phase 3 实验库检索（`library list` 行为不变）
- [ ] `uv run pytest` 全量通过，含 Phase 0-5 已有测试（回归不破坏）
- [ ] 回到 VISION.md 更新第六节"用户自定义技能"里因子部分的状态；明确 Skills（工作流规范）仍是 [PHASE7.md](PHASE7.md) 的独立工作

---

*完成 Phase 6 后，进入 [PHASE7.md](PHASE7.md)：Skills（工作流/业务规范），一套和 Claude Code / Codex 里 Skills 同机制的、靠 description 语义匹配触发、注入指导性内容的基础设施——和本文档的因子库是完全独立的两件事。*

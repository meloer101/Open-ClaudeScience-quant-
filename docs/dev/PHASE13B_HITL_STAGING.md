# PHASE13B · 1.4 详细实施计划：执行前审查台（HITL / plan-confirm 的正确形态）

> 对应 [PHASE13B.md](PHASE13B.md) §1.3+§1.4 与 [GAP_ANALYSIS.md](GAP_ANALYSIS.md) 第四章 4.2。取代原 §1.4「计划确认」的笼统描述——经讨论后重新定型。
>
> **实现状态（2026-07-04）**：核心后端、API 与 Web 审查台已落地。新增 [quantbench/agent/staging.py](quantbench/agent/staging.py)、[tests/test_phase13b_staging.py](tests/test_phase13b_staging.py)，并接入单资产/截面路径、manifest `staging`、`awaiting_confirmation` 与 `/api/runs/{id}/staging/confirm`。B 类中途取消、C 类执行后自动 fork、完整版本化 artifact 浏览器仍按第六节推后。
>
> 前置（均已在 `main`）：
> - **1.0 沙箱**：`run_signal_code` / `run_signal_code_panel`——validation report 靠它跑「一次 compute」而不触发整条回测流水线。
> - **fork + lineage**：[build_fork_config](quantbench/library/fork.py)、实验库、compare——「结果后迭代」走这条,不进本门。
> - **静态 lookahead 扫描**：[detect_lookahead(code)](quantbench/review/lookahead.py) 纯静态、执行前可用。

---

## 〇、核心判断（为什么不是「加几个确认弹窗」）

**HITL 的本质是 artifact review,不是 confirmation。** 量化研究里绝大多数错误不是回测跑完才显现,而是在**定义因子、选 universe、写 `compute()`、设成本、设区间**时就埋进去了——等结果出来再解释,往往是在解释一个错误实验。所以门要放在「关键产物进入昂贵执行**之前**」,让用户**看见、能改、能存版本**。

三条经讨论确立的设计原则:

1. **三类干预必须拆开,别塞进一个「人工确认」。**
   - **A 提交前编辑(staging)**：计划/配置/因子代码在进入昂贵回测前,可看、可改。← **本计划只做这类。**
   - **B 边界处协作取消**：`screen_factors` 跑到一半停在候选边界。← 明确推后(第六节)。
   - **C 回合间分支**：看到结果后「用 10bps 重跑」。← 这不是打断,是 fork/session,走既有 lineage。

2. **门的时序分两层,因为最有用的风险信号算得晚。**
   - **静态门(便宜,执行前)**：AST 未来函数扫描、输入列、`shift` 检测、factor panel 的 NaN/覆盖/对齐——**不需要跑回测**,可真正挡在昂贵回测之前。
   - **执行后信号(贵,回测后)**：IC 爆炸、turnover 离谱、OOS 衰减——挡不住已跑完的 run,只能**导向以此 fork 重来**。← 本计划只做静态门;执行后→fork 的自动路由留 hook。

3. **门策略是个函数,不是全局开关:`gate = f(静态风险分 × 下一步成本)`。** 简单因子 + 静态全绿 + 小回测 → 默认放行(report 可展开);扫到 lookahead 嫌疑 / 复杂多步 compute / 大规模 screen → 默认停。避免 confirmation fatigue。

---

## 一、核心对象：staging artifact（哪些新造、哪些复用）

门要展示的不是裸代码,而是一个**可执行研究假设**的三层视图 + 一份便宜的检查报告。

**`factor_spec`（新造,约一个 dataclass + 序列化）**——三层,降低认知负担:
- **第 1 层 自然语言因子定义**：从用户 hypothesis + 模型意图提取(模型在写 code 时一并产出一句话定义)。
- **第 2 层 公式/伪代码**：模型对 `compute()` 的结构化描述(如「20 日动量 = close/close.shift(20) - 1,shift 一期避免未来函数」)。
- **第 3 层 实际 `compute()` 代码**：模型写的原代码,用户可直接编辑。

**`validation_report`（新造,但内容几乎全是复用,见第三节）**——旁边一张小表,让用户审的是「因子定义↔代码↔检查结果」三者是否一致,而不是「审代码」。

**已复用(不新造)**：`plan/config`(cost_bps/execution/neutralize/universe/date_range 已是工具入参)、manifest、lineage、fork、metrics、research note。真正新增的只有 `factor_spec` 与 `validation_report` 两个 artifact。

---

## 二、门的位置：插在「便宜准备」与「昂贵回测」之间

门不是 Coordinator 的一个独立前置阶段(那样只能审计划参数、审不到代码——而代码此刻还没生成)。门是**昂贵回测工具内部的一个让步点**:模型调用回测工具时,代码已在入参里,此刻 config 和 code **都在手**,正好一起审。

**两条路径各插一处**(两处结构对称):
- **截面**：[coordinator.py:236](quantbench/agent/coordinator.py) `factor_values = run_signal_code_panel(code, panel)`(便宜) → **【门】** → [coordinator.py:237](quantbench/agent/coordinator.py) `run_cross_sectional_backtest(...)`(昂贵:敏感性/CPCV/bootstrap/critic)。
- **单资产**：[backtest_single.py:31](quantbench/agent/tools/backtest_single.py) `signal = run_signal_code(code, ...)`(便宜) → **【门】** → [backtest_single.py:33](quantbench/agent/tools/backtest_single.py) `run_vectorized_backtest(...)`(昂贵)。

**门的四步**(抽象成 `StagingGate`,两条路径共用):
1. 便宜准备:跑一次 compute(已有的 `run_signal_code_panel` / `run_signal_code`)+ 静态扫描,组装 `factor_spec` + `validation_report`。
2. 查门策略 `f(风险×成本)`:决定「默认放行」还是「停下等人」。
3. 若停:把 staging artifact 交给用户 → 等待编辑后的 `overrides`(config 覆盖 和/或 改后的 code)。
4. 应用 overrides → 继续昂贵回测。code 被改则**重跑一次便宜 compute** 刷新 panel(仍不触发昂贵流水线),config 被改则透传给回测。

---

## 三、validation_report：为什么它便宜（本代码库已有大半）

这是「每次都让用户审」能不能默认开的关键——成本 = **一次静态扫描 + 一次沙箱 compute**,**在整条 review 流水线之前就停**。

组装项(全部执行前可得):
- **未来函数**：[detect_lookahead(code)](quantbench/review/lookahead.py) 纯静态,直接复用。
- **`shift`/对齐**：AST 层看有没有 `shift`,以及输出 index 是否按 (timestamp,symbol) 对齐(panel 路径产出的三列 DataFrame 天然能查)。
- **输入列**：compute 实际读了 panel 的哪些列(已可从 sandbox 侧捕获或静态提取)。
- **NaN 比例 / 覆盖率 / 首尾样例**：对 `run_signal_code_panel` 产出的 factor panel 直接算——**这一步本来就要跑**(回测要用它),等于零额外成本。
- **数据侧**：复用 [DataQualityReport](quantbench/skills/data_quality.py)(`symbols_missing_entirely` / `suspicious_price_jumps`),`ctx.data_quality` 已在 run 早期算好。

**明确不在 report 里**:IC、turnover、Sharpe、OOS——这些要跑昂贵回测才有,属第二层信号,不进执行前的门。

---

## 四、门策略：`gate = f(静态风险分 × 下一步成本)`

写成纯函数 `should_stage(risk_score, cost_estimate, policy) -> bool`,可单测,不是全局 on/off。

- **静态风险分**:lookahead 命中(高权重)、compute 语句数/复杂度、NaN 比例超阈值、输入列异常。
- **下一步成本**:单资产 vs 截面 vs `screen_factors`(候选数 × universe × 区间的粗估)。
- **默认策略**:
  - 简单因子 + 静态全绿 + 小回测 → **放行**,`factor_spec`/`report` 记入 artifact 但不打断(用户事后能展开看)。
  - 扫到 lookahead 嫌疑 / 多步复杂 compute / 大规模 screen → **停**在审查台。
- 用户可用开关强制:`--plan`(CLI,opt-in 全停)/ `auto_confirm`(全放行,CI 用)。**默认行为 = 策略函数决定**,既非「永远问」也非「永远不问」。

---

## 五、两阶段控制流与审计

**控制流**(run 已在后台线程执行,天然可阻塞等待):
- **CLI(交互)**:门停下时 = 一个阻塞式 prompt,展示 `factor_spec` 三层 + `report`,接受 `y` / 改参数 / 改代码 / `n`。非交互(`auto_confirm`)直接放行——既有脚本/CI 零回归。
- **API/Web**:run 进入 `awaiting_confirmation` 态,持久化 staging artifact;新增 `POST /api/runs/{id}/staging/confirm`(body 携带 overrides)。执行线程阻塞在一个 `threading.Event`/queue 上等 confirm(与既有 `cancel_event` 同构)。Web 侧是一张「实验提交前审查台」卡片(三层视图 + report + 可编辑),不是弹窗。

**审计**(承接「审计链不可断裂」):
- manifest 新增 `staging` 段:`{factor_spec, validation_report, gate_decision: "auto_pass"|"stopped", overrides, staged_diff}`。
- `staged_diff` = 模型原始产物 vs 用户改后(config 差异 + code diff)——审计「模型要做什么 vs 人改成了什么」。
- 照抄 `delegations`/`sandbox_usage`/`mcp_calls` 的 manifest 加法:[store.py](quantbench/artifact/store.py) 加参数,4 处 `write_manifest` 传 `ctx.staging`。
- **不动 verdict**:staging 是形态层,不新增统计检查、不碰 `determine_verdict` 阈值。

---

## 六、边界：本计划只做 A 类，B/C 明确推后（但留 hook）

- **不做 B(中途取消 + 队列编辑)**：`screen_factors` 的「当前候选跑完后停/跳过当前 family/暂停编辑候选集/保留已完成结果再 fork 新队列」——这需要把停止语义和「停下后用户拿回什么」设计清楚,是独立一块。本计划只保证 [agent/loop.py](quantbench/agent/loop.py) 既有的 `cancel_event` 协作取消不被破坏。
- **不做 C 自动化(执行后风险→自动回 staging/fork)**：IC 爆炸/turnover 离谱触发时自动导向 fork——留 hook(门策略函数预留「执行后信号」入参位),但本计划不实装自动路由;用户仍可手动 fork。
- **不做完整 artifact 版本化 UI**:`factor_spec`/`validation_report` 先作为 manifest 内的段落 + 一张 Web 卡片落地,不做独立的版本化对象浏览器。
- **不改 #5 数据阶段为阻塞**:数据阶段维持「可见 + 可中断」——run 早期展示 data manifest(资产数/区间/频率/源/是否 PIT/缺失率),用户可 stop,但默认不拦。

---

## 七、测试（`tests/test_phase13b_staging.py`）

- **门策略纯函数**:静态全绿 + 小回测 → 放行;lookahead 命中 → 停;大规模 screen → 停。
- **validation_report 组装纯函数**:给定 code + factor panel,产出 lookahead/shift/输入列/NaN/首尾,且**不触发** `run_cross_sectional_backtest`(用 spy 断言昂贵路径未被调用)。
- **门放行路径**:`auto_confirm` 下 run 行为与合并前逐字节一致(既有 golden runs 零回归)。
- **门停下路径(FakeLLM + 注入 confirm)**:模型写一个 code → 门停 → 注入「把 cost_bps 改成 10 + 改 compute」的 overrides → run 用改后值执行;manifest `staging` 段含 `factor_spec`/`report`/`staged_diff`,diff 反映用户改动。
- **API `awaiting_confirmation`**:`POST /staging/confirm` 能推进被阻塞的 run;超时/取消不崩。
- **零回归**:不开 staging(默认策略在简单因子上放行)时全量 `uv run pytest -q` 与当前一致。

---

## 八、验收标准

1. 一个复杂/含 lookahead 嫌疑的因子:回测启动**之前**停在审查台,展示三层 `factor_spec` + `validation_report`;用户改 config 或改 code 后确认,run 按改后执行。
2. 一个简单干净因子:默认放行、不打断,但 `factor_spec`/`report` 仍入 manifest(事后可查)。
3. `validation_report` 的产出**不触发**昂贵回测流水线(成本 = 一次静态扫描 + 一次沙箱 compute)。
4. manifest `staging` 段完整,`staged_diff` 如实反映「模型原始产物 vs 人改后」。
5. `auto_confirm` / 非交互模式行为与合并前逐字节一致;数据阶段维持可见不阻塞。

---

## 九、落地顺序（单人直接在 main 上推进）

1. **`factor_spec` + `validation_report` 两个 dataclass + 组装纯函数 + 单测**(无 IO、无 UI,最快闭环;复用 `detect_lookahead` 和 panel)。
2. **`should_stage` 门策略纯函数 + 单测**。
3. **`StagingGate` 抽象**,先接**截面路径**(coordinator.py:236↔237 之间),CLI 阻塞式 prompt 打通。
4. **manifest `staging` 段 + `staged_diff`**,接 4 处 `write_manifest`。
5. **单资产路径**接同一 `StagingGate`(backtest_single.py:31↔33)。
6. **API `awaiting_confirmation` + `/staging/confirm`**,执行线程阻塞/恢复。
7. **Web 审查台卡片**(三层视图 + report + 可编辑),嵌入现有 run 流。
8. 端到端 + 全量零回归。

每步小步提交到 `main`。第 3 步(门 + CLI 打通)是核心闭环,先把「停→改→继续」在 CLI 跑通,再铺 API/Web。

---

## 十、与既有阶段的接口

- **1.5 多轮 session** 承接本门:审查台卡片自然嵌入对话流;「结果后迭代」在 session 里走 fork(C 类),与本门(A 类)互补不重叠。
- **执行后风险→fork** 的 hook 为后续「智能门」预埋:把某些 Reviewer finding 从事后报告提升为 fork 建议。
- **门策略 `f(风险×成本)`** 复用的是既有 findings 探测器的重排时机,不新造风险引擎——承接「不重复造基础设施」准则。

---

*落地后回填 [PHASE13B.md](PHASE13B.md) §1.3/§1.4 与 [GAP_ANALYSIS.md](GAP_ANALYSIS.md) 4.2,并在本文件标注完成。*

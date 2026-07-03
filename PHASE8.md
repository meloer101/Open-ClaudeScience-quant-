# Phase 8 详细实施计划：多 Agent 协作——独立 Critic Agent + 批量因子筛选流水线

> 对应 [VISION.md](VISION.md) 第七节 Phase 5 未完成项"多 agent 协作（研究 agent + 审查 agent 并行）"。
> 前置条件：[PHASE0.md](PHASE0.md)～[PHASE7.md](PHASE7.md) 均已完成并合并到 `main`；Reviewer Agent（[PHASE2.md](PHASE2.md)）、Experiment Library/Fork（[PHASE3.md](PHASE3.md)）、Web UI（[PHASE_UI.md](PHASE_UI.md)、[PHASE4.md](PHASE4.md)）、crypto 截面（[PHASE5.md](PHASE5.md)）都已落地。
> 目标：VISION 把"多 agent 协作"定义成"研究 agent + 审查 agent 并行"，但这句话字面意思在当前架构下站不住——本计划先把这件事重新论证清楚，再给出实际要做的两步工作。

---

## 一、为什么"研究 agent + 审查 agent 并行"字面意思不成立，重新定义范围经历了几轮

**第一轮理解**：以为"审查 agent"指现有 Reviewer，"并行"指 Reviewer 和 Coordinator 同时跑。查证后发现不成立——Reviewer 是纯确定性 Python（[quantbench/review/report.py](quantbench/review/report.py)），不调用 LLM，且被刻意设计成不可跳过的强制挂钩在 backtest 成功路径上（[PHASE2.md:89](PHASE2.md)），本身就必须等 backtest 产出收益序列才能跑，LLM 也在同一个工具调用里等结果返回，没有"并行"的空间，也不该为了凑"并行"字面意思而把审查逻辑改成模型可选调用的工具——这条设计决策要保留。

**第二轮理解**：转向"批量因子流水线"——VISION 5.1 节唯一给出的具体场景是"一次测 Alpha 101 里 15-20 个 price-volume 因子"，这确实是真正的并行点：N 个候选因子各自的回测+审查（本来就是纯确定性计算）可以用线程池并发跑，而不是排队串行跑 N 次。这个方向是对的，但只解决了"吞吐"问题。

**第三轮理解（用户追问后）**：批量流水线没有回答一个更根本的问题——**整个系统里"这个结果到底靠不靠谱"这个判断，从头到尾都是同一个 LLM 上下文（写因子的 Coordinator）自己给自己下结论**，Reviewer 的确定性检查项本身没有"判断力"（未来函数检测、参数扰动阈值都是写死的数学），但"这些检查项加起来意味着什么、该不该继续深挖"这类更高层的判断，现在只有 Coordinator 一个视角，没有独立复核。

查了 Claude Science 的实际架构（Anthropic 官方博客 + 多篇报道，见文末来源）确认：它的 Reviewer **是**一个真正独立的 LLM agent，工作是核对论文引用/数字是否与底层代码和数据一致，而不是重新做一遍确定性计算——这恰好印证"语义/一致性判断该用 LLM，数学该用代码"这条项目自己的准则（[VISION.md](VISION.md) 第十一节），而不是推翻它。QuantBench 现在缺的正是这一层：一个不受"我刚写了这段代码"心理包袱影响的独立复核视角。

**结论：这份计划分两步**，先做直接回应"判断力缺失"、也真正对应 VISION"研究 agent + 审查 agent"字面意思的 **Critic Agent**；批量因子筛选流水线作为第二步解决吞吐问题，两者独立、互不阻塞。

---

## 二、第一步：独立 Critic Agent

### 2.1 设计要点

新增一个真正独立的**第二次 LLM 调用**，只在每次 `execute()`/`execute_fork()` 的 tool-use 循环**结束时**（拿到 `summary` 之后、`finalize()` 之前）跑一次——不是挂在每次 `run_signal_backtest`/`run_cross_sectional_backtest` 调用上。理由：

- Critic 的职责是复核"Coordinator 即将告诉用户的最终结论"，不是陪跑模型中途每一次调参迭代——这才是 Claude Science reviewer 的实际语义（复核最终产出，不是复核每一步草稿），也避免了模型在 MAX_STEPS 循环里多次调用 backtest 工具时把 LLM 调用成本乘以 N 倍。
- Critic 的 prompt 只包含**已经算好的确定性证据**：`review_report.to_dict()`（8 项检查的 severity/message/detail）、backtest metrics、以及 Coordinator 即将展示给用户的 `summary` 原文——**不包含**对话历史、不知道模型是怎么一步步写出这段代码的。这是"独立"的关键：给它的输入和给用户看的输入是同一份证据，但推理过程完全隔离。
- Critic 同时做两件事（一次 LLM 调用，一份结构化 JSON 输出）：
  1. **叙述一致性核查**（对应 Claude Science reviewer 的"核对数字/引用"）：`summary` 里说的数字/结论是否和 `metrics`/`review_report` 对得上，有没有夸大或遗漏 CRITICAL/WARNING。
  2. **独立二次判断**（回应"判断力缺失"问题）：不重算任何数字，但对现有证据给出自己的 verdict，并明确是否认同确定性 verdict 的聚合规则（≥3 warning → WEAK 这类阈值本来就是 [PHASE2.md](PHASE2.md) 标注的"待校准估计值"，独立视角在这里最有价值）。

### 2.2 具体改动

**新增 `quantbench/review/critic.py`**（新模块，和 `report.py` 平级，`review/__init__.py` 一并导出）：

```python
@dataclass(frozen=True)
class CriticReport:
    status: str  # "ok" | "unavailable"
    verdict: str | None            # 独立 STRONG/PROMISING/WEAK/REJECTED，status=unavailable 时为 None
    agrees_with_deterministic_verdict: bool | None
    critique: str
    narrative_consistency_issues: list[str]
    recommended_next_steps: list[str]

    def to_dict(self) -> dict: ...
    def to_markdown(self) -> str: ...

def run_critic(llm, *, code: str, review_report: ReviewReport, metrics: dict,
                summary: str, context: dict) -> CriticReport:
    ...
```

`run_critic` 内部：拼一段系统提示（明确"你没写这段代码，不需要为它辩护，只看给定证据"），把 `code`/`metrics`/`review_report.to_dict()`/`summary`/`context`（asset_class、symbol 或 universe、cost_bps）序列化成 user message，调 `llm.chat(..., tools=[])`，解析返回的 JSON。**整个函数体包一层 try/except**（网络错误、超时、JSON 解析失败、任何异常）——任何失败都返回 `CriticReport(status="unavailable", ...)`，不抛出。

这不只是防御性编程：现有测试大量用 `monkeypatch.setattr("quantbench.agent.coordinator.LLMClient", lambda model: fake)` 这种"无视 model 参数、永远返回同一个 fake"的写法（[tests/test_api.py](tests/test_api.py)、[tests/test_cli_e2e.py](tests/test_cli_e2e.py)），这意味着 `self.llm` 和新增的 `self.critic_llm` 会共享同一个 `FakeLLMClient` 实例和同一条 `.script` 队列——如果 Critic 调用没有对应的脚本项，`FakeLLMClient.chat()` 会 `pop from empty list` 报错。让 `run_critic` 吞掉这类异常并优雅降级，**现有测试不需要逐个改脚本**，只需要为少数几个专门验证 Critic 行为的新测试显式提供两个独立 fake（`llm=fake1, critic_llm=fake2`）。

**`quantbench/agent/coordinator.py` 改动**：
- `Coordinator.__init__` 新增 `critic_llm: LLMClient | None = None` 参数，`self.critic_llm = critic_llm or LLMClient(CRITIC_MODEL)`。
- `execute()`：在现有 `metrics = ctx.last_metrics or {}`（finalize 之前）插入：若 `ctx.review_report is not None`，调用 `run_critic(self.critic_llm, code=ctx.signal_code, review_report=ctx.review_report, metrics=metrics, summary=summary, context={...})`，结果存 `ctx.critic_report`，`run.save_json("critic_report.json", critic_report.to_dict())`；若 `critic_report.status == "ok" and not critic_report.agrees_with_deterministic_verdict`，追加一条到 `ctx.warnings`（例如 `f"Critic Agent 独立复核认为应为 {critic_report.verdict}，与确定性 verdict（{ctx.review_report.verdict}）不一致：{critic_report.critique[:200]}"`）。若 `ctx.review_report is None`（模型从未跑成功一次回测），跳过，不调用 Critic。
- `execute_fork()` 做同样的插入。
- `run.finalize(...)` 调用处新增 `critic=ctx.critic_report.to_dict() if ctx.critic_report else None`。

**`quantbench/artifact/store.py`**：`Run.finalize()` 新增 `critic: dict | None = None` 参数，写入 `manifest["critic"] = critic`。

**`quantbench/skills/report.py`**：`build_research_note`/`build_cross_sectional_research_note` 新增一个可选参数接收 `critic_report.to_markdown()`（`status="unavailable"` 时该方法返回一行"Critic Agent 本次不可用"，不是空白），在 research_note.md 里另起一个 `## Critic Agent 独立复核` 段落，和 `## Reviewer 审查报告` 并列但分开——保持"确定性检查"和"独立 LLM 复核"在文档结构上就是两个不同性质的东西。

**`quantbench/config.py`**：新增 `CRITIC_MODEL = os.environ.get("QUANTBENCH_CRITIC_MODEL", DEFAULT_MODEL)`——默认和主模型一致（不强制要求配置第二个 API key），但留一个环境变量口子，呼应 VISION 第十节"DeepSeek V3 (MVP) → Claude/GPT（审查场景）"的原始设想，以后想让 Critic 用更强的模型只需设环境变量，不用改代码。

**`quantbench/agent/prompts.py`**：`SYSTEM_PROMPT` 结尾补一句，告诉模型工具结果里最终会附带一个独立 Critic 的复核（模型看不到这个过程，但要知道自己的最终陈述会被核对，不能夸大）。这是可选的措辞调整，不是新工具，不需要改"你有 N 个工具"的编号。

### 2.3 前端改动（最小化）

- [web/src/types.ts](web/src/types.ts)：`ExperimentRecord`/run detail 类型新增 `critic_verdict: string | null`、`critic_agrees: boolean | null`（镜像现有 `verdict`/`critical_count` 字段的加法方式）。
- [web/src/components/Sidebar.tsx](web/src/components/Sidebar.tsx) 的 `VerdictBadge` 邻近位置：当 `critic_agrees === false` 时追加一个小的不一致提示（复用现有 badge 配色模式，不新建组件体系）。
- 不改 `LiveProgress.tsx`——Critic 不是一个工具调用，不会出现在 tool_start/tool_end 事件流里，SSE 时序上它发生在 `emit({"type":"final"})` 之后、`finalize()` 之内，前端会在下一次基于磁盘状态的刷新里自然拿到。**已知的小时延**：`final` 事件触发时 `manifest.json` 还没写完，Critic 这次调用会让这个已存在的间隙从几十毫秒变成几秒——本地单用户工具可以接受，不做额外的 SSE 事件改造，如果实际用起来觉得烦可以后续单独提。

### 2.4 测试

新增 `tests/test_phase8_critic_agent.py`：
1. Critic 认同确定性 verdict 的 happy path——`critic_report.json` 正确落盘，`manifest.json["critic"]` 有值，research_note.md 含独立复核段落。
2. Critic **不认同**确定性 verdict——`ctx.warnings` 里出现不一致提示，且不一致提示不会覆盖或软化原有确定性 verdict（沿用现有对 `_review_warning_messages` 的断言风格）。
3. Critic LLM 调用失败（给 critic_llm 一个会抛异常/返回非法 JSON 的 fake）——run 依然正常 finalize，`critic_report.json["status"] == "unavailable"`，不影响其余流程。
4. fork 路径（`execute_fork`）同样触发 Critic。
5. 跑一次现有回归测试确认"同一个 fake 被 llm 和 critic_llm 共用导致脚本耗尽"时不会让任何现有测试失败（这是验证优雅降级设计生效，而不是新增断言）。

---

## 三、第二步：批量因子筛选流水线

在 `_build_registry(ctx, run, run_store)` 里新增 `screen_factors` 工具，范围限定截面场景：

1. 校验 `ctx.universe is not None` 且候选数在 `1..SCREEN_MAX_CANDIDATES`（新增配置常量，连同 `SCREEN_MAX_WORKERS = 4`）。
2. `fetch_universe_ohlcv` 只拉一次面板数据，所有候选共享只读 `panel`（已确认 [engine/cross_sectional_backtest.py:60](quantbench/engine/cross_sectional_backtest.py:60) 的 `sort_values()` 不带 `inplace=True`，线程间共享读取安全）。
3. 每个候选起一个新的子 run（`run_store.create_run(...)`），完整复刻 `_run_cross_sectional_backtest` 的回测+审查+落盘+`finalize(parent_run_id=run.run_id)` 逻辑——**子 run 同样会触发第一步做好的 Critic Agent**（复用同一段 tail 逻辑，不重复实现）。任何候选异常只影响自己，写 `error.json`，标记 `failed`。
4. `ThreadPoolExecutor(max_workers=min(len(candidates), SCREEN_MAX_WORKERS))` 并发跑步骤 3。
5. 按 verdict 优先级+Sharpe 排序，写父 run 的 `factor_screen_summary.json`，工具返回值带每个候选的 `run_id`/verdict/critic 是否认同/sharpe/status。

不需要改 RunManager/API：子 run 是完全正常的 `Run` 对象，现有 `/api/runs`、`/api/runs/{id}/lineage`、Compare 视图（`compareRunIds` + `CompareView`，对任意 run_id 列表通用）不用改就能用。唯一前端改动是 `LiveProgress.tsx` 的 `TOOL_LABEL` 加一行 `screen_factors: "批量筛选因子"`。`SYSTEM_PROMPT` 新增第 5 个工具说明。

新增 `tests/test_phase8_factor_screening.py`：并发产出独立子 run 且 `parent_run_id` 正确、单个候选异常隔离、排序正确、`ctx.universe is None` 报错、候选数超限报错。

---

## 四、验证

1. `uv run pytest tests/test_phase8_critic_agent.py tests/test_phase8_factor_screening.py -q`，再跑全量 `uv run pytest -q` 确认零回归（当前 88 个测试全绿，重点验证第一步的优雅降级设计没有让任何现有脚本化测试因为"critic 多消耗一次 fake 脚本"而失败）。
2. 手动跑一条会产出 PROMISING/WEAK 的因子请求，检查 `critic_report.json` 是否合理、`research_note.md` 里两个段落（Reviewer 确定性 + Critic 独立复核）都存在且内容不同、manifest.json 里 `critic` 字段有值。
3. 手动跑批量筛选命令，验证子 run 均触发了 Critic、`factor_screen_summary.json` 排序正确、并发有实质加速。
4. 前端：`preview_start` 起 web，跑一次请求，检查 Sidebar 的 verdict badge 区域在 critic 不一致时有额外提示，确认没有因为 SSE 时序间隙导致页面卡死或报错（只是短暂显示旧状态，几秒后自然刷新）。

---

## 五、来源

Claude Science 架构描述参考 [Anthropic 官方发布博客](https://www.anthropic.com/news/claude-science-ai-workbench) 及相关报道——Coordinator agent 通过 Claude Agent SDK 的 subagent 机制调度 60+ 个 specialist 子 agent；Reviewer agent 是独立 LLM agent，核对引用准确性、数字与图表/代码是否一致，而非重新执行确定性计算。

# Phase 7 详细实施计划：Skills 系统——工作流/业务规范的按需注入

> 对应 [VISION.md](VISION.md) 第二节"协调 Agent + 量化研究技能"、第五节协调能力
> 前置条件：[PHASE0.md](PHASE0.md)～[PHASE6.md](PHASE6.md) 已完成——[PHASE6.md](PHASE6.md) 的**因子库**是一套独立的东西（存因子代码），本文档的 **Skills** 和它**完全不是一回事**。
> **核心定义（来自和用户的反复澄清）：** 这里的 Skills 就是**和 Claude Code / Codex 里的 Skills 一模一样的机制，发挥一样的作用、以一样的方式工作**——存的是**工作流/业务规范**（怎么做调查、怎么写代码、遇到某类情况怎么排查），每个 Skill 是一份带 `description` 的文档，靠**语义匹配当前研究意图**触发，加载后往模型上下文**注入指导性内容**，模型看了以后自己现场写代码/做决定。**不是**可被调用的固定函数，**不是**因子代码。

---

## 一、先钉死：Skills 是什么、不是什么

用户对这一点非常明确，实现前必须对齐，否则极易做成 Phase 6 因子库的翻版：

**Skills 是**（照搬 Claude Code / Codex 的 Skill 心智模型）：
- 一份 Markdown 文档（`SKILL.md` 风格），frontmatter 带 `name` + `description`
- `description` 用于**语义匹配**——当用户的研究请求在语义上命中某个 Skill 的适用场景时，这个 Skill 被选中
- 命中后，Skill 的正文（一段工作流规范/操作指南）被**注入到模型的上下文**里
- 模型读了这份指南后，**仍然自己写代码、自己做判断**——Skill 提供的是"这类工作该怎么做"的规范，不是替它执行

**Skills 不是**：
- ❌ 可被 tool-calling 调用、返回确定值的函数（那是现有的 `fetch_ohlcv` 等四个工具）
- ❌ 一段具体的因子代码 `compute(df)`（那是 [PHASE6.md](PHASE6.md) 的因子库）
- ❌ 锁死参数的可复用 pipeline

**举几个 QuantBench 里真实该有的 Skill 例子**（内容是"工作流规范"，不是因子）：
- `crypto-cross-sectional-workflow`：怎么构建一个 crypto 截面 universe 并跑完整套流程——先 build_universe、注意 top-N-by-current-volume 在历史窗口上会因为新币没数据而导致有效标的锐减、所以 n_groups 要相应调小、benchmark 会自动用 BTC/USDT、记得 funding rate 成本未建模要在结论里说明。（这正好把 Phase 5 踩过的坑沉淀成规范）
- `reviewer-weak-triage`：Reviewer 给出 WEAK verdict 之后该怎么排查——先看是哪几条 warning、参数敏感就试参数稳定性区间、regime 集中就按年份切分看是不是单一行情驱动、cost 敏感就看换手率是不是过高，然后决定是调整因子还是换场景。
- `causal-factor-authoring`：怎么写一个不带未来函数的 `compute(df)`——只用当前及之前的行、绝不 `shift(-1)`、返回原始指标值而不是预先阈值化的仓位、注意 pct_change 的 NaN 处理。

这三个都是"怎么做这类工作"的规范，模型读了之后自己写具体代码——这就是 Skills 和因子库的根本区别。

---

## 二、为什么现在做，以及和"模型写什么代码写什么"准则的关系

1. **QuantBench 目前把所有工作流规范硬编码在一个巨大的 system prompt 里。** 看 [prompts.py](quantbench/agent/prompts.py) 的 `SYSTEM_PROMPT`——单标的走哪条路、截面走哪条路、crypto 怎么建 universe、结论里必须原样带出 warning……全都塞在一段固定提示词里，每次 run 无论相不相关都全量注入。这有两个问题：(a) 提示词越堆越长、越来越难维护；(b) 无法按当前请求**只注入相关的规范**。Skills 机制正是解决这个的标准做法——把工作流规范拆成一个个可独立维护、按需匹配注入的文档。
2. **这完全符合 VISION 第十一节准则，而且是它的自然延伸。** Skills 注入的是"指导模型怎么做判断"的内容——它增强的恰恰是"模型负责判断力和创意"的那一侧，不碰"必须绝对正确"的代码侧。Skill 里不会有回测数学、不会有 Sharpe 换算，那些仍然是写死的工具函数；Skill 只讲"面对这类研究请求，推荐的工作流是什么"。
3. **和 Claude Code / Codex 保持机制一致，是用户的明确要求。** 用户说"作用一样、方式一样"——所以我们不发明新范式，直接对齐成熟的 Skill 模型：`SKILL.md` + frontmatter description + 语义匹配 + 上下文注入。

---

## 三、验收标准（先定终点）

**验收命令：**

```
# 1. 列出已有 Skills
$ python -m quantbench skill list

# 2. 查看一个 Skill 的内容
$ python -m quantbench skill show crypto-cross-sectional-workflow

# 3. 正常跑一个 run —— 匹配到的 Skill 被自动注入，无需用户显式指定
$ python -m quantbench "构建 top 30 USDT 永续合约的截面 universe，测试动量因子"
#   → 系统应自动匹配并注入 crypto-cross-sectional-workflow，Coordinator 的行为
#     体现出该 Skill 的规范（比如主动提示 n_groups 要配合有效标的数）

# 4.（可选）用户显式指定要用哪个 Skill
$ python -m quantbench --skill reviewer-weak-triage "我上一个因子被打成 WEAK，帮我看看下一步"
```

系统必须：
1. 有一个 `skills/`（文档）目录，存放若干 `SKILL.md`（每份带 `name` + `description` frontmatter + 工作流正文）
2. **Skill 发现机制**：run 开始时，根据用户请求匹配出相关的 Skill（v1 用确定性的关键词/描述匹配，见第六节——先不上向量语义匹配，保持可测试、可解释）
3. **Skill 注入机制**：匹配到的 Skill 正文被拼进 system prompt（或作为一条额外的 system/context message），和现有 `SYSTEM_PROMPT` 组合，而不是替换
4. `skill list`/`skill show` 只读命令可用
5. `--skill <name>` 可显式强制注入某个 Skill（绕过自动匹配）
6. **哪些 Skill 被注入了，必须可见**：run 的 manifest 里记录 `injected_skills: [...]`，让研究可复现、可审计（这是 VISION 反复强调的溯源要求——不能有"看不见的上下文"影响了结果）

### 正确性测试场景

- **匹配确定性**：给定一个"crypto 截面"请求，`crypto-cross-sectional-workflow` 必须被匹配；给定一个纯 equity 单标的请求，它必须**不**被匹配（不能什么请求都注入所有 Skill，那等于没拆）。用固定请求文本断言匹配结果，不依赖 LLM。
- **注入可审计**：任何 run 的 `manifest.json` 里 `injected_skills` 字段如实反映这次注入了哪些 Skill；`--skill X` 显式指定时该字段包含 X。
- **不破坏无匹配路径**：一个不命中任何 Skill 的请求，run 照常跑通（只用基础 `SYSTEM_PROMPT`），`injected_skills` 为空。

---

## 四、数据模型：`SkillDoc`

```python
@dataclass(frozen=True)
class SkillDoc:
    name: str                # kebab-case 唯一名，如 "crypto-cross-sectional-workflow"
    description: str         # 一句话，用于匹配当前请求是否适用
    triggers: list[str]      # 匹配用的关键词/短语（中英混合，如 ["crypto", "截面", "永续", "USDT perpetual"]）
    body: str                # 工作流规范正文（注入到模型上下文的内容）
    path: str                # 源文件路径
```

**存储**：`quantbench/skills_docs/<name>.md`（用 `skills_docs/` 而不是 `skills/`——`quantbench/skills/` 已经是现有工具函数目录 `registry.py`/`plot.py` 等，名字冲突会误导）。每份 `.md` 用 YAML frontmatter 存 `name`/`description`/`triggers`，`---` 之后是正文 body。这和 Claude Code 的 `SKILL.md` 格式一致。

---

## 五、模块拆解

新增 `quantbench/skilldocs/` 包（Python 包，管理 Skill 文档；注意和现有 `quantbench/skills/` 工具函数包区分，命名上刻意不同）：

| 文件 | 职责 | "代码写"？ |
|---|---|---|
| `skilldocs/doc.py` | `SkillDoc` dataclass + `parse_skill_md(path)`（解析 frontmatter + body） | ✅ |
| `skilldocs/registry.py` | `load_all()` 扫描 `skills_docs/*.md`；`match(request_text) -> list[SkillDoc]`（确定性关键词匹配）；`get(name)` | ✅ |
| `skilldocs/inject.py` | `build_augmented_system_prompt(base_prompt, matched_skills)` → 把匹配到的 Skill body 拼进 system prompt，带清晰的分隔标记 | ✅ |

外加内容目录 `skills_docs/`（放实际的 `.md` 文档，不是 Python），v1 至少写三份种子 Skill：`crypto-cross-sectional-workflow.md`、`reviewer-weak-triage.md`、`causal-factor-authoring.md`（内容见第一节的描述）。

### 5.1 Coordinator 集成

`coordinator.py` 的 `execute`/`execute_cross_sectional` 等入口，在构造 messages（[coordinator.py:509](quantbench/agent/coordinator.py:509) 那种 `{"role": "system", "content": SYSTEM_PROMPT}`）之前：
1. `matched = skilldocs.registry.match(user_request)`（或 `--skill` 显式指定）
2. `system_content = inject.build_augmented_system_prompt(SYSTEM_PROMPT, matched)`
3. 用增强后的 system prompt 构造 messages
4. `ctx.injected_skills = [s.name for s in matched]`，在 `finalize`/manifest 里落盘

**关键：注入是"追加"不是"替换"。** 基础 `SYSTEM_PROMPT`（那些必须绝对遵守的约束，比如"不能省略 warning"）永远在；Skill 是针对当前请求补充的额外规范。

### 5.2 CLI 集成

`cli.py` 加 `skill list`/`skill show` 子命令（Phase 3 的子命令解析风格），主命令加 `--skill <name>` 选项（透传给 Coordinator 作为强制注入）。

---

## 六、关键技术决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| Skill 机制照搬谁 | **Claude Code / Codex 的 Skill 模型**（SKILL.md + description + 匹配 + 注入） | 用户明确要求"作用一样、方式一样"；不发明新范式 |
| 匹配用什么 | **v1 确定性关键词/触发词匹配，不上向量语义匹配** | 关键词匹配可单测、可解释、无外部依赖；语义向量匹配需要 embedding 模型+相似度阈值，是"可能匹配错但不好复现"的黑盒，违背项目对"可审计"的坚持。先把机制跑通，语义匹配作为后续增强（第七节） |
| 注入是替换还是追加 | **追加到基础 SYSTEM_PROMPT** | 基础约束（不省略 warning 等）必须永远生效；Skill 是场景补充，不能覆盖掉底线规范 |
| 存哪 | **`skills_docs/*.md` + YAML frontmatter**，命名刻意区别于现有 `quantbench/skills/`（工具函数） | Skill 文档和工具函数是两回事，目录名混淆会误导；`.md`+frontmatter 和 Claude Code 的 SKILL.md 格式对齐 |
| 注入了什么要不要记录 | **必须记进 manifest（`injected_skills`）** | VISION 反复强调溯源——影响了 run 结果的上下文不能是"看不见的"；否则无法复现"为什么这次模型这么做" |
| Skill 内容能不能含因子代码 | **不能——那是因子库（Phase 6）的事** | 两套机制严格分开；Skill 只讲"怎么做这类工作"的规范，不含具体 compute() 代码 |
| 自动匹配 vs 用户指定 | **两者都支持，自动为主、`--skill` 可强制** | 对齐 Claude Code（既能自动触发，也能 `/skill` 显式调用） |

---

## 七、明确不做的事

| 不做 | 原因 |
|---|---|
| 因子代码的存储/复用 | 那是 [PHASE6.md](PHASE6.md) 因子库；Skills 只存工作流规范 |
| 向量语义匹配 / embedding | v1 用确定性关键词匹配保证可测试、可解释；语义匹配作为后续增强，需要单独评估 embedding 依赖和阈值调参 |
| 让模型自己生成/修改 Skill 文档 | v1 Skill 由人编写（就像 Claude Code 的 SKILL.md 是人写的）；"让成功的 run 自动沉淀成 Skill"是很吸引人但很容易生成低质量规范的方向，留到机制成熟后再评估 |
| Skill 之间的依赖/组合关系 | v1 每个 Skill 独立匹配、独立注入；不做 Skill 编排 |
| 把 Skill 做成 tool-calling 工具 | Skill 的本质是注入上下文，不是被调用返回值——做成工具就变味了，和因子库那个被否定的方向一样错 |

---

## 八、按日拆解（预计 5-6 个工作日）

| Day | 任务 | 产出 |
|---|---|---|
| **Day 1** | `skilldocs/doc.py`：`SkillDoc` + `parse_skill_md`（frontmatter + body 解析）+ 单测（含 frontmatter 缺字段、body 为空等边界） | Skill 文档能被无歧义解析 |
| **Day 2** | `skilldocs/registry.py`：`load_all`/`match`/`get` + 单测（crypto 请求命中 crypto skill、equity 单标的不命中、无匹配返回空——全部确定性断言） | 匹配机制可信、可测 |
| **Day 3** | `skilldocs/inject.py`：`build_augmented_system_prompt`（追加而非替换，带清晰分隔标记）+ 单测（基础约束仍在、Skill body 被正确拼入） | 注入机制正确 |
| **Day 4** | 写三份种子 Skill 文档（crypto-cross-sectional-workflow / reviewer-weak-triage / causal-factor-authoring），内容对齐第一节描述，把 Phase 5 踩过的坑真正沉淀进去 | 有真实可用的 Skill 内容 |
| **Day 5** | Coordinator 集成（匹配→注入→记 `injected_skills` 进 manifest）+ CLI `skill list`/`skill show` + `--skill` 选项 + 端到端测试（含 manifest 里 injected_skills 可审计） | 验收命令全部跑通 |
| **Day 6**（缓冲） | 用真实请求验证：跑一个 crypto 截面请求，确认 crypto skill 被自动匹配注入、manifest 记录正确、Coordinator 行为体现该 skill 的规范；更新 VISION.md、README | 真实端到端可用，文档同步 |

---

## 九、风险与应对

| 风险 | 应对 |
|---|---|
| 关键词匹配太宽，什么请求都注入一堆 Skill，等于没拆、还把 prompt 撑爆 | 每个 Skill 的 `triggers` 要求高特异性（如 crypto skill 要同时命中"crypto/永续/USDT perpetual"这类词，而不是单个泛词）；匹配结果有数量上限；`skill list` 能看到每个 Skill 的 triggers 便于人工校准 |
| 关键词匹配太窄，该注入的没注入，用户体验不到 Skill 的价值 | 提供 `--skill` 显式强制注入兜底；匹配逻辑集中在 `registry.match` 一处、可单测可迭代；v1 先保证"明确命中的场景不漏"，宽度调优靠真实使用反馈 |
| 注入的 Skill body 和基础 SYSTEM_PROMPT 冲突/矛盾 | 注入用清晰分隔标记（如"以下是针对本次请求的额外工作流参考"），措辞上明确 Skill 是"参考建议"而基础约束是"必须遵守"；写 Skill 内容时避免和底线约束打架 |
| 注入的上下文影响了结果却不可见，破坏可复现性 | `injected_skills` 强制记进 manifest；这是硬性要求，不是可选——任何影响 run 的上下文都必须可审计 |
| Skill 文档和现有 `quantbench/skills/` 工具函数目录混淆 | 目录命名刻意区分：工具函数在 `quantbench/skills/`，Skill 文档管理在 `quantbench/skilldocs/`，Skill 内容在项目根 `skills_docs/`；文档和代码里都明确注明两者区别 |

---

## 十、Phase 7 完成后的检查清单

- [ ] `skill list` / `skill show <name>` 可用，能看到 Skill 的 description/triggers/正文
- [ ] 至少三份真实可用的种子 Skill（crypto 截面工作流 / Reviewer WEAK 排查 / 因果因子写法）
- [ ] crypto 截面请求能**自动匹配并注入** crypto-cross-sectional-workflow；纯 equity 单标的请求**不**注入它（匹配确定性测试通过）
- [ ] `--skill <name>` 能显式强制注入指定 Skill
- [ ] 任何 run 的 `manifest.json` 里 `injected_skills` 如实记录本次注入了哪些 Skill（可审计）
- [ ] 无匹配的请求照常跑通，`injected_skills` 为空，行为等同于只有基础 SYSTEM_PROMPT
- [ ] 注入是追加而非替换——基础约束（不省略 warning 等）在有 Skill 注入时仍然生效
- [ ] `skilldocs/` 每个模块（doc/registry/inject）有独立单测；匹配逻辑全部确定性、不依赖 LLM
- [ ] `uv run pytest` 全量通过，含 Phase 0-6 已有测试（回归不破坏）
- [ ] 回到 VISION.md 更新 Skills 相关状态；明确因子库（Phase 6）和 Skills（Phase 7）是两套独立机制

---

*完成 Phase 7 后，QuantBench 就同时具备了 VISION 承诺的两种"沉淀"能力：因子库（把验证过的因子代码存成可复用起点，[PHASE6.md](PHASE6.md)）和 Skills（把工作流规范存成按需注入的指导，本文档）。两者机制不同、用途不同，共同构成"研究记忆"的完整拼图。后续可评估：Skill 的确定性匹配是否需要升级成语义匹配、成功的 run 能否辅助人工沉淀新 Skill。*

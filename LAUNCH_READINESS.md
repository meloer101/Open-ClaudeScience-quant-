# QuantBench 首发就绪度考察（代码 / 量化 / 产品）

> 考察日期：2026-07-04 | 方法：通读 GAP_ANALYSIS / PROJECT_STATUS / README，全量测试实跑（325 passed / 1 skipped，约 3.5 分钟），前端 `npm run build` 实跑（成功），抽查核心量化代码（截面回测引擎、DSR 实现）、API 安全面与配置/打包层。
>
> 与 [GAP_ANALYSIS.md](docs/dev/GAP_ANALYSIS.md) 的关系：GAP 回答"研究平台还缺什么能力"，本文回答"首次推出给陌生用户之前还缺什么"。两者交集很小——GAP 六章的主体完成度经代码逐项核对是可信的。
>
> 2026-07-04 更新：合并第二轮独立审查（Codex）的发现，三个阻断项均已逐条对照代码核实，见「〇之二」。其中 funding 低估 bug 推翻了本文初版"crypto 为主打"建议的前提。
>
> 2026-07-04 复查（第三轮）：B1–B4 阻断项已全部落地并逐条核实修复正确（非仅 commit message）；测试 325→**346 passed / 1 skipped**（+21 新测试）；产品 onboarding（`quantbench serve` 一键启动、`quantbench examples seed` 种子数据、CHANGELOG/RELEASE）、内部文档归档至 `docs/dev/`、API token+CORS allowlist 均已就位。**阻断项已清零，具备公开首发条件。** 逐条核实见「〇之三」。
>
> 2026-07-04 V0 发布复查：补齐直接命中 B1 原始输入形状的 funding 聚合回归测试（同一持仓期 3 条 8h funding rows 必须求和，临时改回取单条时测试失败）；`pyproject.toml` / `CHANGELOG.md` 已对齐到 `0.1.0`；本地 release checklist 已实跑通过：后端 **350 passed / 1 skipped**、前端 lint/Vitest/build/Playwright、wheel smoke、LLM eval、clean `QUANTBENCH_HOME` examples seed + serve。

---

## 〇、总体判断

**研究正确性内核已达到甚至超过首发标准——真正欠缺的是"别人能用起来"的那一层。**

- 统计护栏与回测现实性两层是同类开源工具里最常缺、这里最完整的部分；抽查的 DSR 实现是教科书级的 Bailey & López de Prado 公式（含 trial_sharpes 去年化、期望最大 Sharpe 的 Gumbel 近似）。
- 测试、CI、golden runs、manifest 审计链、注释质量（解释"为什么"而非"是什么"）远超同类项目。
- 瓶颈不在研究正确性，在**可到达性**：安装分发、首次运行体验、平台声明、产品叙事与实际可信度的对齐。

---

## 〇之二、第二轮审查（Codex）交叉验证的首发阻断项

三条均已独立复核代码确认属实，优先级高于下文所有项。

### B1. Crypto funding 成本系统性低估（首发第一阻断项）🔴

两个独立 bug 叠加，最小复现确认应扣 0.06 只扣 0.02（恰为 1/3 比例）：

- **无分页**：[ccxt_perpetual.py:70](quantbench/data/providers/ccxt_perpetual.py) 单次 `fetch_funding_rate_history(limit=1000)`。Binance 8h funding 一天 3 条，1000 条 ≈ 333 天——两年回测的后半段 funding 完全缺失。
- **对齐丢失 2/3**：[cross_sectional_backtest.py:335](quantbench/engine/cross_sectional_backtest.py) 的 `_funding_cost` 按原始 timestamp pivot 后对 `weights.index`（日线 00:00 UTC）精确 reindex，08:00/16:00 两条被丢弃。已核实上游链路（`fetch_universe_funding_rates` → coordinator → 引擎）无任何按日聚合步骤。

**影响**：所有 crypto 多空 run 的 Sharpe 系统性偏乐观——恰好命中本文初版"crypto 为主打"建议的前提。**修复前该建议不成立。**

**修法**（采纳 Codex 的 FundingSeries 深模块方案）：把拉取分页、缓存、"按持仓期聚合对齐到 rebalance periods"的不变量收进一个模块，Interface 直接输出已对齐的 carry series；一处修复，所有 crypto run 受益。修复后需重跑受影响的历史 run 或标注失效。

### B2. CORS 全开 + literature ingest 可读任意本地文件 🔴

攻击链完整：任意网页 POST [`/api/literature/ingest`](quantbench/api/server.py)（[ingest.py:69](quantbench/literature/ingest.py) 接受任意本地路径并 `read_bytes`）→ GET `/api/literature/{id}` 读回提取全文；`allow_origins=["*"]` 让跨源响应可读 = **浏览器 drive-by 窃取本机任意 PDF 内容**。

注意：本文初版建议的"默认绑 localhost"对此**无效**——攻击从用户自己的浏览器发起。正确修法（两者都要）：

- 本地 token 或 origin allowlist；
- Web 端导入改为文件上传/显式文件选择，API 不再接受裸本地路径。

### B3. 默认执行假设 close_t 不保守 🟡

[execution.py:10](quantbench/engine/execution.py) 默认 `fill_price="close_t"`（信号在 close_t 计算、同一价格即时成交），[constants.py](quantbench/agent/constants.py) 的 schema 也告诉模型默认 close_t。Reviewer 的 execution sensitivity 检查有缓解，故严重度低于 B1/B2，但首发默认值应保守：**默认改 open_t+1，close_t 降级为显式乐观口径并在 report 强警告**。

⚠️ 改默认会漂移历史 run 可比性与 golden runs 期望 verdict——需同步更新 golden run registry 并在 CHANGELOG 注明口径变更。

### B4. 交叉验证确认的应补项

- **过期 funding 警告（自相矛盾，单独强调）**：[constants.py:284](quantbench/agent/constants.py) 的 `CRYPTO_PERPETUAL_FUNDING_WARNING` 仍说"不建模 funding"，且 [coordinator.py:359](quantbench/agent/coordinator.py) 对所有 crypto universe **无条件**追加——系统同时"扣了 funding"和"警告说没扣"。对卖点是"可审计诚实"的产品，自相矛盾的警告比缺失的警告伤害更大。应改为条件化：funding 缺失或覆盖不全时才警告（正好覆盖 B1 修复后"分页拉不全"的场景）。
- **审查台字段太窄**：[StagingReviewPanel.tsx:34](web/src/components/StagingReviewPanel.tsx) 只能编辑 code 和 cost_bps；首发前至少要能审/改 execution、universe、date range、liquidity、borrow、neutralize、n_groups。与 Codex 的 ExecutionAssumption/StagingConfig typed-Interface 方案是同一件事。
- **文案承诺漂移**：[ChatInput.tsx:39](web/src/components/ChatInput.tsx) placeholder 暗示 @/#//⌘K 可用但无对应交互；旧版 PROJECT_STATUS 现状盘点（已删除，内容并入本文档）曾说 4.3 文献接入未做，但 CLI/API/Web 已实现三个 Phase——本文档已是当前唯一的现状来源。
- **CI 只跑 Python**：与本文「一、4」重合——前端 build/lint/Vitest/Playwright 均未进 CI。

### 架构建议（非阻断）

- **FundingSeries 模块**：即 B1 修复本身，随修复落地。
- **ExecutionAssumption/StagingConfig 模块**：与审查台补字段合并做。
- **RunFinalizer 模块**（coordinator 的 finalize/report/manifest 写入拆出）：纯重构，可延后到首发后。

---

## 〇之三、第三轮复查：阻断项修复核实（2026-07-04）

逐条读修复后的代码确认，非依赖 commit message。

| 项 | 状态 | 核实依据 |
|---|---|---|
| **B1 funding 分页** | ✅ 修复 | [ccxt_perpetual.py:72](quantbench/data/providers/ccxt_perpetual.py) `while since < end_ms` 循环分页，不再单次 limit=1000 |
| **B1 funding 对齐** | ✅ 修复 | 新建深模块 [engine/funding.py](quantbench/engine/funding.py) `funding_cost_by_period`：按持仓区间 `[start, next)` 分窗、`aggfunc="sum"` 累加窗口内所有 funding 行（8h/16h/00h 全吃到），并输出 `coverage_ratio` 指标。正是 Codex 建议的 FundingSeries 深模块 |
| **B2 CORS+token** | ✅ 修复 | [api/security.py](quantbench/api/security.py) `DEFAULT_ALLOWED_ORIGINS` 限定 localhost + [server.py:62](quantbench/api/server.py) 全局 `Depends(require_api_token)` |
| **B2 literature 导入** | ✅ 修复 | 旧端点拒绝本地路径（"Local PDFs must be imported with the upload endpoint"，仅留 arXiv），新增 `/api/literature/ingest/upload` 用 `UploadFile`——drive-by 读取本机 PDF 的攻击链闭合 |
| **B3 执行默认口径** | ✅ 修复 | [execution.py:11](quantbench/engine/execution.py) 默认 `fill_price="open_t+1"`；CHANGELOG 注明 close_t 降级为显式乐观口径并触发 Reviewer 警告 |
| **B4 funding 警告条件化** | ✅ 修复 | [research_notes_support.py:49](quantbench/agent/helpers/research_notes_support.py) 改为 `coverage_ratio>=0.98 且无缺失/失败` 才不警告，文案改为量化的 coverage 报告——消除了"扣了 funding 却警告没扣"的自相矛盾 |
| 附带 PerpetualData schema | ✅ | 新增 [data/perpetual_schema.py](quantbench/data/perpetual_schema.py)，顺手还了 GAP 1.5 的 schema 债 |

**结论修订**：Codex 与本文初版"先受信任 alpha、修复后再公开首发"的前置条件已满足——阻断项清零、测试全绿、产品 onboarding 就位。下方「一~三」章中被上述修复覆盖的条目视为已关闭，剩余为可延后增强项。

### V0 release checklist 复查（2026-07-04）

| 项 | 状态 | 核实依据 |
|---|---|---|
| B1 原始 bug 模式回归测试 | ✅ 新增 | [test_engine_funding.py](tests/test_engine_funding.py) 覆盖同一日内 00:00/08:00/16:00 三条 funding row 求和；临时把 `aggfunc="sum"` 改为取单条时关键测试失败 |
| funding coverage 指标 | ✅ 新增 | 同一测试文件覆盖 `coverage_ratio < 1.0` 与 `missing_period_symbol_pairs > 0` |
| funding warning 条件化 | ✅ 复核 | 同一测试文件验证 coverage 数字进入 warning 文案，完整 coverage 时不警告 |
| 版本 / CHANGELOG | ✅ 对齐 | [pyproject.toml](pyproject.toml) `0.1.0` 与 [CHANGELOG.md](CHANGELOG.md) 最新 `0.1.0 - 2026-07-04` 一致，无空 `Unreleased` |
| 本地 release checklist | ✅ 通过 | `uv run pytest -q`、前端 lint/unit/build/e2e、wheel smoke、LLM eval、clean-home seed+serve 均已实跑 |

---

## 一、代码角度

### 做得好的

- 15k 行 Python + 3.8k 行前端；325 个测试全绿且有 CI；golden runs 回归集。
- manifest 审计段完整（delegations / sandbox_usage / mcp_calls / staging / memory_events / llm_usage）。

### 缺口（按严重度排序）

1. **只能以 git clone 方式运行，无法作为包分发。** [config.py:8](quantbench/config.py) 把 `PROJECT_ROOT` 锚定在包文件位置的上级目录——`pip install` 成 wheel 后，`data_cache/`、`runs/`、`.env` 会全部写进 site-packages 旁边。两条路二选一：
   - 明确"首发形态就是 clone + uv sync"，README 声明；
   - 或把数据目录改为 `~/.quantbench/` / 环境变量可配。

   另外 [pyproject.toml](pyproject.toml) 里 `version = "0.1.0"`、description 仍写着 "Phase 0 CLI prototype"，已陈旧。

2. **平台支持没有声明，Windows 会直接崩。** 沙箱依赖 `resource.setrlimit`（Unix-only），Windows 上 import 即失败。首发至少在 README 写明"仅支持 macOS/Linux"，或加显式启动期检测和可读报错。

3. **API 是零信任面。** [server.py](quantbench/api/server.py) `allow_origins=["*"]`、无鉴权；路径穿越只靠 `".." in filename` 子串检查。本地单人使用可接受，但任何能访问该端口的人都能烧 LLM API 额度并触发代码执行（沙箱是 builtins 黑名单式，不是真隔离）。首发前建议：默认只绑 `127.0.0.1` + README 安全姿态声明（"不要暴露到公网"）。

4. 小项：
   - 前端单 bundle 759KB（gzip 229KB），无代码分割；
   - CI 只跑 pytest，无 lint / typecheck / 前端测试。

---

## 二、量化角度

### 做得好的

- 统计护栏（DSR / PBO / CPCV / walk-forward / bootstrap / Newey-West IC）与回测现实性（执行价口径、流动性成本、容量曲线、borrow、三维中性化、funding）完整且数学正确。
- 截面引擎对 n_groups vs universe 规模不匹配等静默退化路径有显式防护，报错可操作。

### 缺口

1. **Equity 截面结论的方向性风险仍未解除。** yfinance 不覆盖退市股，幸存者偏差在数据进回测之前就发生——GAP 文档自己说得很清楚："动量/反转类因子的截面结果连方向都可能是错的，Reviewer 再严格也审不出来"。verdict 封顶是诚实的缓解，但首发需要一个**产品决策**：
   - 要么接入付费源（Polygon 机制位已留好）；
   - 要么在产品叙事上把美股截面降级为"演示/教学能力"、把 crypto 作为主打。⚠️ **此路径以修复 B1（funding 低估）为前提**——修复前 crypto 侧数据链路并不自洽。

   现状是 README 把两者并列宣传，与实际可信度不对称。

2. **Crypto PIT 对新用户是空的。** 快照从首次运行 `snapshot-crypto` 才开始积累；每个新用户从零开始，意味着首发后几个月内所有新用户的 crypto PIT 都不可用。**建议随发行版附带一份已积累的快照种子数据**——低成本高价值。

3. **golden runs 只覆盖确定性 Reviewer，LLM 侧无评测。** 6 个 case 全部不调 LLM（CI 无密钥可跑，刻意设计）。这意味着 Coordinator 的 prompt、DeepSeek 换版本、Critic 的判断质量没有任何回归保障——GAP 5.1 最初担心的"prompt 改一版 verdict 整体漂移"只解决了一半。首发前至少要有一个手动触发、烧真实 API 的小型 LLM eval（例如 5 个自然语言请求 → 期望的 factor_spec 结构断言）。

4. 已知未还的债（可以带着上线但要声明）：
   - 数据分片保留策略缺失 → `rerun` 的 bit-level 复现承诺会随缓存淘汰**静默失效**；
   - `open_interest` / `PerpetualData` schema 未落地；
   - 单资产因子无信号导出（`factor export` v1 仅覆盖截面）。

---

## 三、产品角度（离首发最远的一层）

1. **首次运行体验没有被设计过。** 新用户需要：uv + Python、npm、DeepSeek API key、分别启动 uvicorn 和 vite 两个进程，然后面对空的实验库和空的因子库。首发前建议三件事：
   - 一条命令同时起前后端（`quantbench serve` 之类）；
   - 内置 1–2 个预跑好的示例 run——Reviewer 报告是产品的核心卖点，现在新用户要自己烧钱跑一次才能看到；
   - README 增加 from-zero walkthrough：去哪申请 DeepSeek key、一次 run 大约花多少钱、第一个 5 分钟看什么。

2. **仓库形态是"给自己看的"，不是"给用户看的"。** 根目录堆着 12 个 PHASE\*.md / GAP / MEMORY 内部规划文档，与 README、LICENSE 混在一起。首发前挪进 `docs/dev/`（或单独分支），根目录只留用户视角的内容。

3. **成本透明度只做了一半。** `llm_usage` 事后记账和 `screen_factors` 的预估都有了，但主路径（单次 run）没有执行前成本预估。对"每次交互都花真钱"的产品，这是新用户信任的关键一环。

4. **风险声明要延伸到交互面。** README 末尾的声明很好，但 `factor export` 的 JSON 和 Web UI 是研究→真金白银的交接面，那里的免责声明比 README 里的更重要。

5. **缺发布纪律。** 没有 CHANGELOG、没有 tag/release 流程、版本号从未动过。首发本身就是第一个 release。

---

## 四、首发前建议清单（按投入产出排序）

| 优先级 | 事项 | 量级 |
|---|---|---|
| 必须（第一） | B1：funding 分页 + 按持仓期对齐（FundingSeries 模块）+ 重跑/标注受影响 run | 2–3 天 |
| 必须 | B2：API 本地 token/origin allowlist + literature 导入改文件上传 | 1 天 |
| 必须 | B3：默认执行口径改 open_t+1 + golden runs/CHANGELOG 同步 | 1 天 |
| 必须 | B4：条件化 funding 警告（消除自相矛盾） | 半天 |
| 必须 | 平台声明（Windows 不支持）+ API 安全姿态声明 + 默认绑 localhost | 半天 |
| 必须 | 首次运行体验：一键启动、示例 run 种子数据、from-zero walkthrough | 2–3 天 |
| 必须 | 产品叙事校准：crypto 为主打、美股截面标注幸存者偏差限制 | 半天 |
| 必须 | 仓库整理：内部文档归档、pyproject 元数据更新、首个 tagged release | 1 天 |
| 强烈建议 | 附带 crypto universe 快照种子数据 | 1 天 |
| 强烈建议 | 最小 LLM 侧 eval（手动触发） | 1–2 天 |
| 强烈建议 | 审查台补齐关键假设字段（ExecutionAssumption/StagingConfig typed Interface） | 2 天 |
| 强烈建议 | 前端 build/lint/Vitest/Playwright 进 CI + 文案漂移清理（ChatInput placeholder、PROJECT_STATUS） | 1 天 |
| 可延后 | 数据分片保留策略、单次 run 成本预估、bundle 分割、Polygon 接入 | 各 1–3 天 |

---

## 五、一句话总结

~~量化内核可以直接见人；代码层有两三个半天级的硬伤要补；产品层需要大约一周的"面向陌生人"打磨——瓶颈不在研究正确性，在可到达性。~~

**（2026-07-04 修订）第二轮审查发现 funding 低估 bug 后，结论收紧为：不建议现在公开首发，可做受信任用户的本地 alpha。B1–B3 修复（约一周）后，剩余瓶颈回到可到达性，再叠加原清单的产品打磨（约一周）即可公开首发。**

---

*本文件为首发前的一次性就绪度快照；各项落地后建议在此勾选或移入对应 PHASE 文档。*

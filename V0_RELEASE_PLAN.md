# QuantBench V0 发布计划

> 制定日期：2026-07-04 | 依据：[LAUNCH_READINESS.md](LAUNCH_READINESS.md) 全部阻断项（B1–B4）已核实修复，CI 三个 job 全绿。本文件是从"具备首发条件"到"正式喊出 V0"之间最后一段路的执行清单。
>
> 判断：**代码和产品层面已经具备首发条件，不需要再拖。** 唯一名不副实的是发布机制本身——版本号、CHANGELOG、git tag 三者没有对齐，且有一个具体的测试盲点值得在打包前堵上。本文件只覆盖这段"最后一公里"，不重复 LAUNCH_READINESS 已经说清楚的内容。

---

## 任务一：补一个直接命中 B1 原始 bug 模式的单测

**为什么优先做这个**：现有 funding 相关测试（`test_cross_sectional_backtest_subtracts_funding_by_position_direction`、`test_ccxt_funding_rate_history_paginates_until_end`）分别验证了"按方向扣费"和"分页能翻页"，但都只喂了**每个持仓周期一条 funding rate**。B1 的原始 bug 恰恰是"一个持仓周期内有多条 funding rows（比如 00:00/08:00/16:00 三条 8h rate）时只吃到一条，丢了 2/3"——现有测试的输入形状不会暴露这个问题，也就没有测试真正锁定这个修复。

**要做的事**：
- [ ] 新建 `tests/test_engine_funding.py`，直接测 `quantbench/engine/funding.py` 的 `funding_cost_by_period`。
- [ ] 核心 case：日线 rebalance（`weights.index` 间隔 1 天），`funding_rates` 在同一天内塞 3 条 8h rate（如 0.01/0.01/0.01），断言该期 `cost` 等于三条之和乘以权重，而不是只等于一条。
- [ ] 补一个 `coverage` 字段的 case：故意让某个 symbol 在某期完全没有 funding row，断言 `coverage_ratio < 1.0` 且 `missing_period_symbol_pairs > 0`，验证 B4 依赖的 coverage 指标本身是准的。
- [ ] 跑通后确认 [research_notes_support.py](quantbench/agent/helpers/research_notes_support.py) 的条件化警告逻辑在这个新单测覆盖的 coverage 数字下行为正确（可选，若已被现有测试间接覆盖则跳过）。

**验收标准**：`uv run pytest tests/test_engine_funding.py -v` 全绿；且如果手动把 `funding_cost_by_period` 里的 `aggfunc="sum"` 改回按位置取值（复现原始 bug），这个新测试必须失败。

**量级**：30–45 分钟。

---

## 任务二：把 CHANGELOG 的 `Unreleased` 收进正式版本号

**现状问题**：`pyproject.toml` 写 `version = "0.1.0"`，`CHANGELOG.md` 最新一条**已发布**记录却是 `0.1.0-alpha`，而 B1–B4 那几条真正让系统可信的修复还挂在没有日期、没有版本号的 `Unreleased` 段——三者互相不对齐，没法回答"你们现在发的是哪个版本"。

**要做的事**：
- [ ] 决定版本号：建议直接用 `0.1.0`（不带 `-alpha`）。理由：B1–B4 修完之前的状态才是真正的"alpha 质感"（数据会骗人、API 敞着口子）；修完之后已经是"可以给受信任用户用"的水平，`-alpha` 后缀反而低估了当前状态。
- [ ] 编辑 `pyproject.toml`：`version = "0.1.0"`（如果决定保留 `-alpha` 后缀，改成 `version = "0.1.0a1"` 之类的 PEP 440 合法写法，不要用裸 `-alpha`）。
- [ ] 编辑 `CHANGELOG.md`：把 `## Unreleased` 段的三条 B1–B4 修复合并进一个新的 `## 0.1.0 - <发布日期>` 段（或者如果版本号不变，直接把日期从 `0.1.0-alpha` 那条挪过来、注明这是修复后的正式 V0）。清楚区分"首次实现"（旧 `0.1.0-alpha` 内容）和"首发前修复"（B1–B4）两层内容，不要合并成一条流水账——未来回看时能分清哪些是"从无到有"哪些是"从错到对"。

**验收标准**：`pyproject.toml` 的 version 字段与 `CHANGELOG.md` 最新一条版本号完全一致；`CHANGELOG.md` 里不再有空的或包含真实修复内容的 `Unreleased` 段。

**量级**：15 分钟。

---

## 任务三：走一遍 `docs/RELEASE.md` 清单

现有清单（[docs/RELEASE.md](docs/RELEASE.md)）已经写好，V0 是它第一次被真正执行。逐条跑：

- [ ] `uv run pytest -q`（预期：347 passed 含任务一新增的测试，1 skipped）
- [ ] `cd web && npm run lint && npm test && npm run build`
- [ ] `cd web && npm run test:e2e`
- [ ] `uv run python -m build && uv pip install --force-reinstall dist/*.whl && uv run quantbench --help`（wheel smoke；这一步已经在 CI 的 `pytest` job 里跑，本地重复一遍是为了在打 tag 前有本地信心，不依赖 CI 环境差异）
- [ ] 手动跑一次 LLM eval（`quantbench/evals/llm_eval.py`，需要真实 API key；这是唯一没法在 CI 里自动跑的一步，因为要花真钱）
- [ ] 在干净目录里验证 `QUANTBENCH_HOME` + `quantbench examples seed` + `quantbench serve` 的完整首次运行路径（不复用本地已有的 `data_cache/`/`runs/`，模拟真实新用户）
- [ ] 复核 `LAUNCH_READINESS.md`，把已解决的 launch gap 标注掉（本文件任务一/二完成后，`LAUNCH_READINESS.md` 清单里"强烈建议"那一档应该基本清空，只剩"可延后"档）

**验收标准**：清单 7 条全部跑完且无红灯（LLM eval 允许因为没有 API key 而人工跳过，但要在 PR/发布记录里注明"跳过原因：无密钥环境"而不是静默不跑）。

**量级**：1–2 小时（含等待 CI/e2e）。

---

## 任务四：打 tag、发布

- [ ] 确认任务一/二/三全部完成且工作树干净（`git status` 无未提交改动）。
- [ ] `git tag -a v0.1.0 -m "QuantBench v0.1.0 - first trusted-user release"`（tag message 里简述 B1–B4 已修复、适用范围是受信任本地用户，不是公开无门槛发布）。
- [ ] `git push origin v0.1.0`。
- [ ] 在 GitHub 上基于该 tag 创建 Release，Release notes 至少包含：
  - 支持平台（macOS/Linux，Python 3.11+）
  - 安全姿态（本地 token + CORS allowlist，不要暴露到公网）
  - 数据局限（crypto PIT 快照仍在积累、equity 不覆盖退市标的、美股截面 verdict 因此封顶）
  - 风险声明（研究产物不是投资建议）
  - 链接回 `LAUNCH_READINESS.md` 作为完整审计记录

**验收标准**：`git tag -l` 能看到 `v0.1.0`；GitHub Releases 页面有对应条目；Release notes 四类信息齐全，不是简单复制 CHANGELOG。

**量级**：30 分钟。

---

## 不在本次范围内（刻意排除）

以下项目在 [LAUNCH_READINESS.md](LAUNCH_READINESS.md) 中已标注为"可延后"或"非阻断"，本计划不重复：

- StagingReviewPanel 补齐 universe/date range/liquidity/borrow/size+sector 中性化字段（现有 fill_price/n_groups/cost_bps/beta 已覆盖最容易出错的部分）
- 数据分片保留策略、单次 run 前置成本预估、前端 bundle 分割
- Polygon 等付费数据源接入
- Docker 级沙箱隔离
- 文献接入之外的其他 SubAgent 角色扩展

这些留给 V0 发布之后的下一轮迭代。

---

## 总时间预算

| 任务 | 量级 |
|---|---|
| 一：funding 聚合单测 | 30–45 分钟 |
| 二：版本号/CHANGELOG 对齐 | 15 分钟 |
| 三：走完 RELEASE 清单 | 1–2 小时 |
| 四：打 tag、发布 | 30 分钟 |
| **合计** | **半天以内** |

一句话：**这不是一个需要重新规划工期的大任务，是一个下午就能走完的收尾清单。**

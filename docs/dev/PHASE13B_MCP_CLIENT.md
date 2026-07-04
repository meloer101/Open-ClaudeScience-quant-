# PHASE13B · 1.1 详细实施计划：MCP client（接入只读外部数据工具）

> 对应 [PHASE13B.md](PHASE13B.md) §1.1 与 [GAP_ANALYSIS.md](GAP_ANALYSIS.md) 第四章 4.4 / 第七章 7.2。
>
> 前置（均已在 `main`）：
> - **1.0 沙箱**（含截面/monitor 路径收口）：`skills/sandbox.py` 的 `run_in_sandbox`，执行类能力的门槛。
> - **SubAgent 抽象** + `delegations` / `sandbox_usage` 两个 manifest 留痕段——本计划的 `mcp_calls` 照抄同一模式。
>
> 一句话目标：让 QuantBench 作为 **MCP client**，把用户配置的外部 MCP server 的**只读数据工具**动态注册进现有 [SkillRegistry](quantbench/skills/registry.py:14)，Coordinator 像调内置工具一样调用它们，且每次调用留痕、用了外部数据的 run 被 Reviewer 打上来源标签。

> 完成记录（2026-07-04）：已落地只读 stdio MCP client、白名单注册、副作用拒绝、`mcp_calls` manifest 留痕、`external_data_unverified` Reviewer 信息标签、mock stdio server 与 FakeLLM 端到端测试。验证：`uv run pytest -q tests/test_phase13b_mcp.py`、相关回归、全量 `uv run pytest -q` 均通过。

---

## 〇、范围与不做

**本阶段只做只读数据类 MCP tool。** 执行类 / 有副作用的 tool 一律**拒绝注册**——它们需要「必须经 1.0 沙箱」的门槛，而把一个外部 MCP tool 塞进沙箱是另一套设计（沙箱目前只包 `compute()`，不是任意 RPC），留待后续。

**明确不做**：
- 不做「QuantBench 作为 MCP server」（只作 client）。
- 不做执行类 / 写类 MCP tool 放开（本阶段拒绝注册，给出清晰错误）。
- 不做 MCP tool 返回数据的质量校验接入内置 [data_quality](quantbench/skills/data_quality.py)（外部数据**不享受**内置 provider 的信任等级——这正是 `external_data_unverified` 标签的意义）。
- 不做 OAuth / 远程 HTTP MCP server 的鉴权流（v1 只做本地 **stdio** transport；HTTP/SSE transport 留接口位但不实装）。
- 不引入 async 框架到 Coordinator 主循环（见第三节的 async→sync 桥接决策）。

---

## 一、依赖

- [x] 新增唯一依赖：官方 `mcp` Python SDK（[PHASE13.md](PHASE13.md) 已批准）。加进 [pyproject.toml](pyproject.toml) 的 `dependencies`，**pin 一个下限版本**（如 `mcp>=1.0`）。
- [x] `mcp` 是 async-first 的（`asyncio` + `anyio`）。这是本阶段唯一真正的工程难点，见第三节。不引入 `litellm` 之外的其他运行时依赖。

---

## 二、配置：信任边界就是这个文件

- [x] 配置文件 `PROJECT_ROOT/mcp_servers.json`（走 [config.py](quantbench/config.py:8) 的 `PROJECT_ROOT` 惯例，与 `.env` 同级）。**缺文件 = 零 MCP server**，功能对既有 run 完全透明、零回归。
- [x] Schema（v1 只认 stdio）：
  ```json
  {
    "servers": [
      {
        "name": "my_data",
        "transport": {"type": "stdio", "command": "python", "args": ["-m", "my_mcp_server"], "env": {}},
        "enabled_tools": ["get_ohlcv", "get_fundamentals"],
        "allow_write": false
      }
    ]
  }
  ```
- [x] `enabled_tools` 是**显式白名单**：缺省 `[]` / 缺字段 = **一个都不注册**（不是"全部"）。白名单外的 tool 即使 server 暴露了也不注册、不可调用。
- [x] `allow_write` 缺省 `false`。`true` 在本阶段直接导致该 server 的**全部 tool 拒绝注册**并 warning（放开路径留到执行类沙箱就绪）。
- [x] `name` 唯一；注册进 registry 的工具名统一为 `mcp_{server}_{tool}`——命名空间隔离，杜绝与内置工具（`fetch_ohlcv` 等）或跨 server 撞名。
- [x] config 解析写成纯函数 `load_mcp_config(path) -> list[MCPServerConfig]`（dataclass），schema 非法时**跳过该 server 并 warning**，不让一个坏配置炸掉整个 Coordinator 启动。

---

## 三、MCPSkillAdapter：async→sync 桥接（本阶段核心）

**问题**：`mcp` SDK 全是 async（`ClientSession`、`stdio_client` 都是 async context manager，`list_tools()` / `call_tool()` 是协程）；而 [SkillRegistry.execute](quantbench/skills/registry.py:34) 和 [agent/loop.py](quantbench/agent/loop.py) 的循环是**纯同步**的。且 stdio session 是一个**跨多次调用存活的子进程连接**——不能每次调用 `asyncio.run()`（那样每次都新建/销毁事件循环与连接）。

**决策（方案 A：后台事件循环线程）**：
- [x] 新增 `skills/mcp_adapter.py`，核心是一个 `MCPClientManager`：
  - 启动时开一个**守护线程**跑一个持久 `asyncio` 事件循环（`loop.run_forever()`）。
  - 在该循环里为每个 server 打开 `stdio_client` + `ClientSession` 并**保持存活**（`initialize()` 一次），session 句柄存起来。
  - 每次 `registry.execute` 命中 MCP 工具时，同步侧用 `asyncio.run_coroutine_threadsafe(session.call_tool(...), loop).result(timeout=...)` 把协程投进后台循环并**阻塞等结果**——对 Coordinator 完全同步、无感知。
  - `close()`：取消各 session、停 loop、join 线程；注册 `atexit` 兜底，避免留下僵尸子进程。
- [x] 为什么不是「每次调用 `asyncio.run()`」：stdio 连接必须跨调用存活，且反复起停子进程既慢又会丢 server 端状态。后台循环是持久连接的标准做法。
- [x] **调用超时**：`call_tool` 加 wall-clock 超时（config 可调，默认如 30s），超时→结构化错误，不吊死 agent loop。server 崩溃 / 管道断开→捕获成结构化错误，不崩 run。

**工具注册**：
- [x] `MCPClientManager.build_skills() -> list[Skill]`：对每个 server `list_tools()`，过滤 `enabled_tools` 白名单，把每个 MCP tool 翻译成一个 [Skill](quantbench/skills/registry.py:6)：
  - `name = f"mcp_{server}_{tool}"`
  - `description = tool.description`（可前缀 `[external:{server}]` 让模型知道这是外部来源）
  - `parameters = tool.inputSchema`（MCP 的 `inputSchema` 本就是 JSON Schema，与 [SkillRegistry.schemas](quantbench/skills/registry.py:21) 期望的 `function.parameters` 同构，直接透传）
  - `fn = 一个闭包`，调用时走后台循环 + 记审计（见第四节）。
- [x] **结果归一化**：MCP `call_tool` 返回 content blocks（text / image / embedded resource）。v1 只处理 text block：拼接文本，尝试 `json.loads`，失败则原样返回字符串。非 text block（图像等）→ 结构化「不支持的返回类型」错误（数据类工具不该返回图像）。
- [x] **执行类拒绝**：MCP 的 tool 定义没有标准「只读」标志位。v1 策略：`allow_write=false`（默认）时，**只放行白名单内的 tool**，并对 tool 名/描述含明显副作用信号（`create` / `delete` / `write` / `order` / `send` / `execute` 等词根）的**额外拒绝并 warning**——宁可误拒，用户可改 `enabled_tools` 显式确认。放行判定写成纯函数 `is_readonly_tool(tool) -> bool`，可单测。

---

## 四、审计两条红线（承接「审计链不可断裂」）

**红线一：每次 MCP 调用留痕。**
- [x] [run_context.py](quantbench/agent/run_context.py:60) 新增 `self.mcp_calls: list[dict] = []`（紧挨 `sandbox_usage`）。
- [x] 工具闭包每次调用后 append：`{"server", "tool", "args", "result_sha256", "duration_s", "error"?}`。`result_sha256` 对归一化后结果的 JSON 串做 sha256——**记指纹不记全量**（结果可能很大，且 manifest 要可读）。
- [x] [store.py](quantbench/artifact/store.py:82) 的 `write_manifest` 新增 `mcp_calls` 参数（照抄 `delegations` / `sandbox_usage` 的加法），manifest 新增 `mcp_calls` 段。
- [x] 4 个 `write_manifest` 调用点全部传入 `ctx.mcp_calls`：[coordinator.py:830](quantbench/agent/coordinator.py)（single）、coordinator fork 路径、[screening.py:318](quantbench/agent/tools/screening.py)、以及 portfolio 路径（与现有 `sandbox_usage` 传入点一一对应，逐一核对不漏）。

**红线二：用了外部数据的 run 打来源标签。**
- [x] [report.py](quantbench/review/report.py) 新增 `_external_data_finding`：severity=`info`，message 列出用到的 server/tool 列表。**它是来源可信度标签，不是质量缺陷——不封顶 verdict**（照抄 [_funding_cost_finding](quantbench/review/report.py) 那类 optional-detail finding 的结构，`determine_verdict` 对 info 无影响，阈值一律不动）。
- [x] [run_review](quantbench/review/report.py:97) 新增可选参数 `mcp_calls: list[dict] | None = None`；非空时 `findings.append(_external_data_finding(mcp_calls))`。
- [x] **4 个 run_review 调用点全部接线**：[coordinator.py:313](quantbench/agent/coordinator.py)、[backtest_single.py:57](quantbench/agent/tools/backtest_single.py)、[backtest_single.py:104](quantbench/agent/tools/backtest_single.py)、[screening.py:156](quantbench/agent/tools/screening.py)——传 `mcp_calls=ctx.mcp_calls`。漏一个就意味着某条研究路径用了外部数据却不打标签，逐一核对。

---

## 五、生命周期与装配

- [x] `MCPClientManager` 在 [Coordinator](quantbench/agent/coordinator.py) 构造时**惰性初始化一次**（读 `mcp_servers.json`；无文件→manager 为空、`build_skills()` 返回 `[]`，[_build_registry](quantbench/agent/coordinator.py:566) 那行等于 no-op）。
- [x] [_build_registry](quantbench/agent/coordinator.py:566) 在注册完内置工具后，追加 `for skill in mcp_manager.build_skills(): registry.register(skill)`。Coordinator 其余部分、[agent/loop.py](quantbench/agent/loop.py) **不改一行**——工具形状与内置完全一致。
- [x] manager 的存活范围：随 Coordinator 实例（FastAPI 下是进程级长存；CLI 下是单次 run）。`atexit` 关闭兜底。**连接失败不阻塞 run**：某 server 起不来→warning + 跳过它的工具，其余照常。

---

## 六、测试（`tests/test_phase13b_mcp.py`）

- [x] **config 解析纯函数**：合法 JSON → dataclass 列表；缺 `enabled_tools` → 空白名单；`allow_write=true` → 该 server 工具全拒；坏 JSON / 缺字段 → 跳过 + warning，不抛。
- [x] **只读判定纯函数**：`get_ohlcv` 放行；`create_order` / `delete_x` / `send_y` 拒绝。
- [x] **mock stdio server**：用 `mcp` SDK 写一个最小 stdio server（暴露一个返回固定 OHLCV JSON 的 `get_ohlcv` tool），测试内以子进程 stdio 起它：
  - adapter 连上后 `build_skills()` 产出名为 `mcp_mock_get_ohlcv` 的 Skill，schema = server 的 inputSchema。
  - 经 `registry.execute("mcp_mock_get_ohlcv", {...})` 能拿到解析后的 JSON。
  - 白名单外的 tool 不出现在 `build_skills()` 结果里；直接 execute 未注册名→`{"error": "unknown tool"}`（现有 registry 行为）。
  - 调用后 `ctx.mcp_calls` 有一条含 `result_sha256`。
- [x] **端到端（FakeLLM 驱动）**：一个 script 让模型调用 `mcp_mock_get_ohlcv` 再走既有回测，跑完后 manifest 有 `mcp_calls` 段、review findings 含 `external_data_unverified`（info、不改 verdict）。
- [x] **async 桥接鲁棒性**：server 端 tool 抛错 → 结构化错误、run 不崩；调用超时 → 结构化超时错误。
- [x] **零回归**：无 `mcp_servers.json` 时全量 `uv run pytest -q` 与当前一致（新参数全部可选、缺省不改行为）。

---

## 七、验收标准

1. 配置接入一个 mock stdio MCP server 后，Coordinator 能像调内置工具一样调用其白名单内的只读 tool，模型无需任何特殊处理。
2. 该 run 的 manifest 出现 `mcp_calls`（含 server/tool/args/result 指纹），且 Reviewer findings 含 `external_data_unverified`（info 级、不封顶 verdict）。
3. 白名单外的 tool 无法被调用；`allow_write=true` 的 server 工具全部拒绝注册并有清晰 warning。
4. 含明显副作用词根的 tool 即使在白名单内也被拒绝（除非用户显式放宽——本阶段无放宽路径，直接拒）。
5. 无 `mcp_servers.json` 时行为与合并前逐字节一致；server 起不来时该 server 被跳过、其余 run 正常。

---

## 八、落地顺序（单人直接在 main 上推进）

1. **config 解析 + 只读判定纯函数 + 单测**（无 IO，最快闭环）。
2. **MCPClientManager 后台循环 + mock server 连通性测试**（打通 async 桥接，是全篇风险点，先验证）。
3. **build_skills + 结果归一化 + registry 装配**（接进 `_build_registry`）。
4. **审计红线一（`mcp_calls` → ctx → 4 处 manifest）**。
5. **审计红线二（`external_data_unverified` → report.py → 4 处 run_review）**。
6. **端到端 FakeLLM 测试 + 零回归全量跑**。

每步小步提交到 `main`。第 2 步（async 桥接）若验证不通再评估是否退到「每调用一次 `asyncio.run` + 无持久连接」的降级方案（更慢但更简单）——但先按持久连接做。

---

*落地后回填 [PHASE13B.md](PHASE13B.md) §1.1 勾选项与 [GAP_ANALYSIS.md](GAP_ANALYSIS.md) 4.4 / 7.2，并在本文件标注完成。*

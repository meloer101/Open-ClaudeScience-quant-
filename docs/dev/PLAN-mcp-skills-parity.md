# MCP & Skills 使用体验对齐 Claude Code / Codex

> 目标：让用户在 QuantBench 里**添加、启用、管理 MCP 与 Skills 的体验，尽量和 Claude Code / Codex 一模一样**——
> 能直接复制粘贴现成的 MCP 配置、能像插件一样开关 Skill、既能在 UI 里点（Sidebar「New」下方新增的 **Customize** 入口），也能在 CLI 里敲。

本文是实施蓝图，落地时按阶段推进。所有文件路径均相对仓库根目录。

> **2026-07-05 状态更新**：Phase 0–3（配置格式对齐、REST API、Customize 面板、CLI 对齐）已实现并随 `0.2.0` 发布，见 [CHANGELOG.md](../CHANGELOG.md)。Phase 4 仅完成 transport 分发（sse/http），OAuth 授权流程未做。Phase 5（工具级授权）未开始。剩余工作见文末 M3/M4 里程碑。

---

## 1. 指导原则

1. **配置格式即接口。** Claude Code / Claude Desktop / Cursor / Codex 都用同一套 `mcpServers` JSON 结构。只要我们采用同一格式，用户就能把官方文档、别人分享的 gist、Claude Desktop 的配置**原样粘进来**——这是「体验一样」最关键的一环，远比 UI 长得像重要。
2. **UI 是配置的镜像，不是唯一入口。** Claude Code 里 `claude mcp add` 与手改 `.mcp.json` 双向等价。我们的 Customize 面板、CLI、配置文件三者读写同一份状态。
3. **作用域分层。** 和 Claude Code 一样区分 **user（全局）** 与 **project（项目）** 两级作用域，project 覆盖 user。
4. **可开关、可热更。** 每个 MCP server / 每个 Skill 都能独立启用/禁用，改动**下一次 run 立即生效，无需重启进程**。
5. **安全默认不倒退。** 现有「只读工具默认放行、写工具需显式授权」的门禁（[`mcp_adapter.py`](../quantbench/skills/mcp_adapter.py) 的 `is_readonly_tool` / `allow_write`）保留并 UI 化，对齐 Claude Code 的工具授权模型。

---

## 2. 现状 vs. Claude Code / Codex 差距分析

| 能力 | Claude Code / Codex | QuantBench 现状 | 差距 |
| --- | --- | --- | --- |
| MCP 配置格式 | `{"mcpServers": {"<name>": {"command","args","env"}}}`（对象、按名索引） | 自定义 `{"servers": [{"name","transport":{...}}]}`（数组、嵌套 transport） | **格式不通用**，无法复制粘贴现成配置 |
| MCP 作用域 | user（`~/.claude.json`）+ project（`.mcp.json`）+ local | 单文件 `PROJECT_ROOT/mcp_servers.json` | 无 user 级、无分层 |
| MCP transport | stdio + SSE + HTTP（远程 + OAuth） | 仅 stdio | 无远程 server |
| MCP 生命周期管理 | `claude mcp add/list/get/remove`、`/mcp` | 只能手改文件 + 重启 | **无 API、无 UI、无 CLI、无热更** |
| MCP 工具授权 | 交互式批准 / 权限规则 | 只读放行、写操作硬禁用 | 门禁在，但不可配置、无 UI |
| MCP 启停开关 | `enabledMcpjsonServers` / 禁用列表 | 无 | 无法临时禁用某个 server |
| Skills 来源 | `~/.claude/skills/`（个人）+ `.claude/skills/`（项目）+ 插件市场 | 仅 `PROJECT_ROOT/skills_docs/` | 无 user 级、无导入 |
| Skills 触发 | 模型按 `description` 自动调用 | 关键词 `triggers` 匹配（[`registry.py`](../quantbench/skilldocs/registry.py) `match`） | 机制可用，但需与 description 兜底 |
| Skills 开关 | 可启用/禁用 | 无——放进目录即永久激活 | **无开关** |
| Skills 管理 UI/CLI | `/plugin`、settings | `quantbench skill list/show`（只读） | 无增删、无开关、无 UI |
| 入口 | `/mcp`、`/plugin`、settings 面板 | 无 | Sidebar 需新增 **Customize** 入口 |

结论：**MCP 和 Skills 的「管理层」在 QuantBench 里基本不存在**——底层加载能力都在，但缺少配置格式对齐、持久化开关、以及 API/UI/CLI 三个管理入口。下面分阶段补齐。

---

## 3. 统一配置模型（核心决策）

### 3.1 MCP：采用 Claude Code 的 `mcpServers` 格式

**新增两层配置文件：**

- User 级：`~/.quantbench/mcp.json`（跟随 `QUANTBENCH_HOME`）
- Project 级：`PROJECT_ROOT/.mcp.json`（可提交进 git，团队共享）

**统一格式（与 Claude Code / Claude Desktop 完全一致，可直接复制粘贴）：**

```jsonc
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/data"],
      "env": { "FOO": "bar" }
    },
    "some-remote": {
      "type": "http",              // stdio | sse | http，缺省 stdio
      "url": "https://mcp.example.com/sse"
    }
  }
}
```

**QuantBench 私有扩展**（放在与官方字段并列的可选键，不破坏粘贴兼容性）：

```jsonc
"filesystem": {
  "command": "npx", "args": [...],
  "quantbench": {                  // 仅本项目读，其他工具忽略
    "enabledTools": ["read_file", "list_directory"],  // 空=全部只读工具
    "allowWrite": false
  }
}
```

启用/禁用状态**不写进 `.mcp.json`**（保持它可粘贴、可共享），而是写进独立的 settings 文件（见 3.3），对齐 Claude Code 的 `enabledMcpjsonServers` 设计。

**向后兼容：** `load_mcp_config` 保留对旧 `{"servers":[...]}` 的解析（[`mcp_adapter.py:60`](../quantbench/skills/mcp_adapter.py)），新增对 `{"mcpServers":{...}}` 的解析并合并；提供一次性迁移 `quantbench mcp migrate` 把旧文件转成新格式。

### 3.2 Skills：user 级目录 + 保持 `SKILL.md`

- 新增 user 级目录 `~/.quantbench/skills/`，与项目 `skills_docs/` 合并加载（[`config.py:19`](../quantbench/config.py) 增加 `USER_SKILL_DOCS_DIR`）。
- 目录结构保持 Claude Code 风格：`<skill-name>/SKILL.md` + 附件。
- `SKILL.md` frontmatter：`name` / `description` 必填（对齐 Claude Code），`triggers` **降级为可选**——无 `triggers` 时用 `description` 分词做兜底匹配（改造 [`doc.py:26`](../quantbench/skilldocs/doc.py) 的必填校验与 [`registry.py:47`](../quantbench/skilldocs/registry.py) 的 `match`）。这样从 Claude Code 拷来的 Skill 无需改写即可用。

### 3.3 统一 settings 文件（开关状态的家）

`~/.quantbench/settings.json`（user 级）+ `PROJECT_ROOT/.quantbench/settings.json`（project 级，project 覆盖 user）：

```jsonc
{
  "mcp": {
    "disabledServers": ["some-remote"]      // 未列出的即启用
  },
  "skills": {
    "disabledSkills": ["reviewer-weak-triage"]
  }
}
```

设计要点：**默认全开、显式禁用**（disable list 而非 enable list），这样新粘进来的 server / 新拷进来的 skill 默认可用，符合直觉，也与 Claude Code 一致。

---

## 4. 分阶段实施

### Phase 0 — 配置格式对齐（后端，无 UI 依赖）

> 目标：能读 `mcpServers` 格式、能读两级作用域、能读 settings 开关、Skills 支持 user 目录 + 可选 triggers。这是后续一切的地基。

- [x] `config.py`：新增 `USER_MCP_CONFIG = QUANTBENCH_HOME / "mcp.json"`、`PROJECT_MCP_CONFIG = PROJECT_ROOT / ".mcp.json"`、`USER_SKILL_DOCS_DIR = QUANTBENCH_HOME / "skills"`、`SETTINGS_FILES = [...]`。保留旧 `MCP_SERVERS_CONFIG` 做兼容。
- [x] `mcp_adapter.py`：
  - `load_mcp_config` 支持 `mcpServers` 对象格式；解析 `type`（stdio/sse/http）；解析 `quantbench.enabledTools/allowWrite`。
  - 新增 `load_merged_mcp_config()`：合并 user + project + 旧文件，project 覆盖 user，去重。
  - 应用 settings 的 `disabledServers` 过滤。
- [x] `skilldocs`：`SkillRegistryDocs` 支持多目录（user + project）；`match` 在无 triggers 时用 description 兜底；应用 `disabledSkills` 过滤。
- [x] 新增 `quantbench/settings.py`：读写合并 `settings.json`，提供 `is_server_enabled(name)` / `is_skill_enabled(name)` / `set_*_enabled(...)`。
- [x] `coordinator.py`：把 `self._mcp_configs = load_mcp_config(...)`（[:709](../quantbench/agent/coordinator.py)）改为**每次 `execute` 时重新读取合并配置**，实现开关热更；`_select_skill_docs`（[:1278](../quantbench/agent/coordinator.py)）读多目录 + 过滤禁用。
- [x] 测试：扩展 [`test_phase13b_mcp.py`](../tests/test_phase13b_mcp.py) 覆盖新格式解析、作用域合并、disable 过滤；新增 skills 多目录 + 禁用测试。

**验收：** 把一段 Claude Desktop 的 `mcpServers` 配置粘进 `~/.quantbench/mcp.json`，`quantbench mcp list` 能列出；在 settings 里 disable 一个，run 时不再加载。

### Phase 1 — 后端 config 服务（API）

> 目标：把 Phase 0 的读写能力暴露成 REST，供 UI 与 CLI 复用。全部挂在现有 [`api/server.py`](../quantbench/api/server.py)，沿用 `require_api_token` 鉴权。

新增端点（`quantbench/api/config_routes.py`，`schemas.py` 加对应模型）：

```
GET    /api/config/mcp-servers        列出所有 server（含来源 scope、enabled、连接状态、已发现工具）
POST   /api/config/mcp-servers        新增/更新一个 server（body 含 name + 标准字段 + scope）
POST   /api/config/mcp-servers/import 粘贴整段 mcpServers JSON 批量导入
DELETE /api/config/mcp-servers/{name} 删除
PATCH  /api/config/mcp-servers/{name} 启用/禁用（写 settings.disabledServers）
POST   /api/config/mcp-servers/{name}/test  即时连一次，返回工具清单 / 错误（对齐 claude mcp get 的连通性反馈）

GET    /api/config/skills             列出所有 skill（name/description/来源 scope/enabled/triggers）
PATCH  /api/config/skills/{name}      启用/禁用
POST   /api/config/skills/import      导入一个 skill 目录（zip 或粘贴 SKILL.md 文本）
DELETE /api/config/skills/{name}      删除（仅限 user 级目录，project/内置只读）
```

- [x] server 写入时做与 CLI 相同的校验（command 非空、args 为字符串数组等，复用 `_parse_server_config`）。
- [x] `test` 端点复用 `MCPClientManager._connect_async` 单跑一次，超时返回结构化错误，不阻塞。
- [x] 测试：扩展 [`test_api.py`](../tests/test_api.py) 覆盖增删改查 + import + 开关。

### Phase 2 — 前端 Customize 面板（UI）

> 目标：Sidebar「New」按钮下新增 **Customize** 入口，点开一个和 `ApiKeyModal` 同风格的面板，两个 Tab：**Skills** / **MCP (Connectors)**，长得像截图里的 Claude Desktop 能力设置页。

- [x] `Sidebar.tsx`：在 [「New」按钮（:219）](../web/src/components/Sidebar.tsx) 下方加一个 **Customize** 按钮（同样式，图标用齿轮/滑块），`onCustomize` 回调透传到 `App.tsx`。
- [x] `App.tsx`：新增 `showCustomize` 状态，挂载 `<CustomizePanel/>`（参考 [`ApiKeyModal` 挂载:323](../web/src/App.tsx)）。
- [x] 新增组件 `web/src/components/CustomizePanel.tsx`：
  - 顶部 Tab 切换 **Skills / MCP**。
  - **Skills 列表**：每行 name + description + 右侧开关（对齐截图的 toggle 列）；顶部「+ Add skill」（粘贴 `SKILL.md` 或上传 zip）。
  - **MCP 列表**：每行 server name + transport 徽标 + 连接状态点 + 已发现工具数 + 开关 + 删除；顶部两个入口：
    - **「+ Add server」表单**（name / command / args / env / transport / enabledTools）——对应 `claude mcp add`。
    - **「Paste JSON」**——直接粘贴 `mcpServers` 片段，对应用户最常见的复制粘贴动作。
  - 每个 server 有「Test connection」按钮，调 `/test` 端点显示工具清单或报错。
- [x] `web/src/api/client.ts`：新增 `listMcpServers/saveMcpServer/importMcpServers/deleteMcpServer/toggleMcpServer/testMcpServer` 与 `listSkills/toggleSkill/importSkill/deleteSkill`（参考现有 [`getConfigStatus`/`setLlmConfig`:262](../web/src/api/client.ts)）。
- [x] 组件测试：仿 [`ApiKeyModal.test.tsx`](../web/src/components/ApiKeyModal.test.tsx) 写 `CustomizePanel.test.tsx`。
- [x] i18n：沿用现有中英混排风格（面板标题「自定义 / Customize」）。

**验收：** 点 Customize → MCP → Paste JSON 粘一段配置 → 保存 → 列表出现 → Test 显示工具 → 关掉开关 → 下次 run 不加载。整个过程不碰文件、不重启。

### Phase 3 — CLI 对齐（`claude mcp` 风格）

> 目标：命令行子命令与 `claude mcp` 命名一致，肌肉记忆无缝迁移。扩展 [`cli.py`](../quantbench/cli.py) 现有 dispatch。

```
quantbench mcp add <name> <command> [args...] [--env K=V] [--scope user|project] [--transport stdio|sse|http] [--url ...]
quantbench mcp add-json <name> '<json>'
quantbench mcp import <path-or-clipboard>      # 粘贴 mcpServers 片段
quantbench mcp list
quantbench mcp get <name>                       # 含连通性测试
quantbench mcp remove <name>
quantbench mcp enable|disable <name>
quantbench mcp migrate                          # 旧 servers[] -> mcpServers{}

quantbench skill list                           # 现有，增加 enabled 列
quantbench skill show <name>                    # 现有
quantbench skill enable|disable <name>          # 新增
quantbench skill add <path>                     # 新增，导入到 user 目录
```

- [x] 全部复用 Phase 0 的 `settings.py` / `mcp_adapter` / `skilldocs`，与 API 走同一逻辑。
- [x] 测试：CLI e2e 覆盖 add→list→disable→remove。

### Phase 4 — 远程 transport + OAuth（补齐 SSE/HTTP）

> 目标：支持远程 MCP server，对齐 Claude Code 的 `--transport sse/http` 与 OAuth。

- [x] `mcp_adapter.py`：`_connect_async` 按 `type` 分派到 `sse_client` / `streamablehttp_client`（mcp SDK 已提供）。
- [x] **未授权时在 UI/CLI 明确提示「需要授权」而非静默失败**：`authorization_required_hint` 识别 401/403/WWW-Authenticate/OAuth 挑战；`probe_mcp_server` 返回 `needs-authorization` 状态，Customize 面板的 Test 与 `quantbench mcp test` 都会区分展示（见 [CHANGELOG 0.2.0](../../CHANGELOG.md)）。
- [ ] OAuth：远程 server 需要授权时，走浏览器授权码流程（本地单用户工具，回调打到 API 的临时端口）。**未做**——目前只能提示用户自行提供凭据/令牌。
- [ ] 注意：当前环境说明里就有一批「需要 OAuth 授权」的 connector——UI 要复刻这种「已配置但待授权」的状态展示（Test 按钮已能显示 `needs-authorization`，但列表默认态尚未主动探测）。

### Phase 5 — 工具级授权（对齐权限模型）

> 目标：把现有硬编码的「只读放行 / 写禁用」变成可配置的工具授权，接近 Claude Code 的 allow/deny 规则。

- [ ] settings 增加 `mcp.toolPermissions`：按 `server/tool` 记 `allow|ask|deny`。
- [ ] `build_skills`（[`mcp_adapter.py:123`](../quantbench/skills/mcp_adapter.py)）不再对写工具一律 `warn+skip`，改为按权限：`allow` 直接暴露，`ask` 运行时回调确认，`deny` 跳过。
- [ ] UI：server 展开后逐工具列出，可勾选授权（对齐截图里「每个能力一行开关」的粒度）。
- [ ] 保持默认安全：未配置的写工具默认 `deny`（不倒退现有行为）。

---

## 5. 涉及文件清单（速查）

**后端新增/改动**
- `quantbench/config.py` — 新增路径常量
- `quantbench/settings.py` — **新增**，开关状态读写
- `quantbench/skills/mcp_adapter.py` — 新格式解析、作用域合并、多 transport、权限
- `quantbench/skilldocs/{doc,registry}.py` — 多目录、可选 triggers、禁用过滤
- `quantbench/agent/coordinator.py` — 每次 run 重读配置（热更）
- `quantbench/api/config_routes.py` — **新增** REST 端点
- `quantbench/api/schemas.py` — 对应 pydantic 模型
- `quantbench/cli.py` — `mcp` 子命令、`skill` 增强

**前端新增/改动**
- `web/src/components/Sidebar.tsx` — Customize 入口
- `web/src/App.tsx` — 挂载面板
- `web/src/components/CustomizePanel.tsx` — **新增**
- `web/src/api/client.ts` — 新增 API 封装
- `web/src/components/CustomizePanel.test.tsx` — **新增**

**配置文件（用户侧）**
- `~/.quantbench/mcp.json`、`PROJECT_ROOT/.mcp.json`
- `~/.quantbench/settings.json`、`PROJECT_ROOT/.quantbench/settings.json`
- `~/.quantbench/skills/<name>/SKILL.md`

---

## 6. 里程碑与优先级

| 里程碑 | 内容 | 用户可感知的「和 Claude Code 一样」 |
| --- | --- | --- |
| **M1（最小可用）** | Phase 0 + Phase 1 + Phase 2 的 MCP 部分 | **能在 UI 里粘贴 mcpServers 配置并开关 MCP**——覆盖 90% 的日常诉求 |
| **M2** | Phase 2 的 Skills 部分 + Phase 3 CLI | Skills 开关 + 命令行对齐 |
| **M3** | Phase 4 远程 + OAuth | 能接远程 MCP server |
| **M4** | Phase 5 工具授权 | 细粒度权限 |

建议先打通 **M1**：它直接命中截图里的场景（列表 + 开关 + Add），且「粘贴现成配置即可用」是和 Claude Code 体验一致性的最强信号。

---

## 7. 关键风险与决策

1. **格式迁移的兼容窗口。** 上线新 `mcpServers` 格式时，旧 `mcp_servers.json` 必须继续可用一段时间 + 提供 `migrate`，避免现有用户配置失效。
2. **热更 vs. 连接开销。** 每次 run 重连 MCP 有启动成本。若某 server 冷启动慢，考虑进程级连接池缓存 + 配置指纹失效（配置没变就复用连接）。
3. **写工具安全。** Phase 5 放开写工具前，默认必须仍是「未授权即拒绝」，不能因为对齐体验而降低现有安全基线。
4. **Skills 匹配质量。** 去掉 `triggers` 必填后，description 兜底匹配可能变吵。保留 `triggers` 作为高优先信号，description 仅兜底。
```

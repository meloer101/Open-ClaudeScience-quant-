# Phase UI 详细实施计划：Web 工作台

> 对应 [VISION.md](VISION.md) 第七节原 Phase 4（可视化与 UI），提前执行——原 Phase 2（Reviewer Agent）顺延
> 前置条件：[PHASE0.md](PHASE0.md)、[PHASE1.md](PHASE1.md) 已完成，Coordinator 能跑单标的和截面两种研究请求，产出完整 artifact
> 目标：把现在只能在终端看文字、在文件夹里翻文件的体验，变成一个真正的、Claude Science 那种质感的 Web 工作台

---

## 一、参照物：截图里到底有什么

用户提供的 Claude Science 截图里，可以拆解出这些具体元素：

| 区域 | 元素 | 说明 |
|---|---|---|
| 顶部 | 多 session 标签页 | 像浏览器标签一样，同时开着几个研究会话（"scRNA-seq..."、"CRISPR Kinase..."） |
| 左侧栏 | 会话历史列表 | 按日期分组（"Today"），点击可切换到历史会话 |
| 左侧栏 | New / Customize / Files | 顶部导航 |
| 中间主区 | 对话流 | 用户请求 + 模型回复（回复里有内嵌的、可点击的文件名链接） |
| 中间主区 | Artifact 画廊 | 每轮回复下方一排缩略图卡片（"GENERATED · 16"，展示 5 个 + "+11 more"） |
| 中间主区 | 输入框 | 提示文字 "@ for artifacts, # for sessions, / for skills, ⌘K to search"，还有模型选择下拉、语音输入图标 |
| 右侧栏 | Artifact 查看器 | 独立面板，自己也有标签页（同时开着 3 个 artifact），点开显示大图/表格，带全屏、下载、关闭按钮 |

**这次 Phase 的范围（已和用户确认）：** 先做**核心三件套**——左侧会话列表、中间对话流+画廊、右侧单标签 artifact 查看器。多 session 顶部标签页、右侧多 artifact 标签页、实时流式工具调用展示，作为后续快速迭代项，不放进第一版。

---

## 二、验收标准（先定终点）

打开浏览器，能完整走一遍：

1. 左侧栏显示历史 run 列表（按日期分组），默认展示最近一次
2. 中间对话流渲染出：用户的原始请求 + 模型的最终自然语言总结（含 markdown 渲染）+ 下方一排 artifact 缩略图卡片（图片显示缩略图，csv/md 显示通用文件图标）
3. 点击任意一个 artifact 卡片，右侧面板显示对应内容：
   - `.png` → 直接显示大图，可下载
   - `.csv` → 渲染成表格
   - `.md`（research_note.md）→ 渲染成排版好的 markdown
4. 在输入框里输入新的研究请求，点击发送，前端调用后端 API 触发一次新的 `Coordinator.run()`，跑完后自动出现在对话流里、左侧列表也新增一条
5. 警告（synthetic data / 离谱指标 / 生存者偏差等）在对话流里必须**和终端里一样醒目**——黄色高亮或明显的警告区块，不能被样式"优化"到不起眼

**Definition of Done：** 不用打开终端、不用手动翻 `runs/` 文件夹，就能完整体验一次"提出研究问题 → 看到过程 → 看到图表和数据 → 看到警告"的闭环。

---

## 三、明确不做的事（这次 Phase 的边界）

| 不做 | 留到哪里 |
|---|---|
| 顶部多 session 标签页（同时开多个会话标签） | 下一轮迭代 |
| 右侧 artifact 查看器同时开多个标签 | 下一轮迭代 |
| 实时流式展示工具调用过程（现在是提交后等待，完成后一次性展示） | 下一轮迭代（需要 SSE/WebSocket + Coordinator 加事件回调） |
| 真正的多轮追问对话（现在一次 run = 一次请求 + 一个最终回答，不支持在同一个 run 里继续追问） | 更后面，需要改 Coordinator 的对话状态管理 |
| `@ / # ⌘K` 这些输入框高级交互、语音输入、模型选择下拉 | 纯视觉细节，先做静态占位，交互留到后面 |
| 移动端适配 | 本地工具，先只做桌面浏览器 |
| 用户账号/多用户 | 本地单用户工具，不需要 |
| 部署上线 | 本地 `npm run dev` + 本地 API 跑起来即可 |

**红线不变：任何功能想加进来，先问"验收标准需要它吗"。**

---

## 四、架构设计

### 4.1 整体架构

```
┌─────────────────────────────────────────┐
│  浏览器 (React + Vite + TypeScript)        │
│  ┌──────────┬──────────────┬───────────┐ │
│  │ Sidebar  │   ChatPane   │ Inspector │ │
│  │ 会话列表  │  对话流+画廊  │ artifact  │ │
│  └──────────┴──────────────┴───────────┘ │
└──────────────────┬──────────────────────┘
                   │ HTTP (REST, 先不做 WebSocket)
┌──────────────────▼──────────────────────┐
│  FastAPI 后端 (quantbench/api/)           │
│  - 包装现有 Coordinator，不改动其核心逻辑   │
│  - 读 runs/ 目录的 manifest 做列表/详情     │
│  - 直接把 artifact 文件当静态资源 serve    │
└──────────────────┬──────────────────────┘
                   │ 直接调用 Python 对象
┌──────────────────▼──────────────────────┐
│  quantbench.agent.coordinator.Coordinator │
│  （Phase 0/1 已完成，不动）                │
└───────────────────────────────────────────┘
```

**关键设计原则：** 后端 API 层只是 Coordinator 的一层**只读+触发**包装，不重新实现任何回测/数据逻辑——这和之前定的"模型写创意逻辑、代码写基础设施"是同一条准则的延伸："前端/API 只负责展示和触发，核心研究逻辑完全在 Coordinator 里，不允许在 API 层或前端里出现任何"重新算一遍指标"之类的逻辑。

### 4.2 后端 API（`quantbench/api/`）

```
quantbench/api/
├── __init__.py
├── server.py          # FastAPI app, 路由定义
├── run_manager.py      # 管理"触发一次 run"的后台执行 + 状态跟踪
└── schemas.py          # Pydantic 响应模型
```

**路由设计：**

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/runs` | 列出所有历史 run（读 `runs/*/manifest.json`，按时间倒序） |
| `GET` | `/api/runs/{run_id}` | 单个 run 详情：user_request、summary、metrics、warnings、artifact 文件列表 |
| `GET` | `/api/runs/{run_id}/artifacts/{filename}` | 直接返回文件内容（图片用 `FileResponse`，csv/md 用文本读取后返回） |
| `POST` | `/api/runs` | 提交新研究请求 `{request: str}`，触发一次 `Coordinator.run()`，返回 `{run_id, status: "running"}` |
| `GET` | `/api/runs/{run_id}/status` | 查询运行状态（`running` / `completed` / `failed`），前端轮询用 |

**触发新 run 的执行方式（`run_manager.py`）：**

```python
class RunManager:
    """Phase UI v1: 用一个内存字典追踪正在跑的 run，用线程池跑 Coordinator，
    前端轮询 /status 直到完成。不做 WebSocket/SSE 实时推送——那是下一轮迭代。"""

    def __init__(self):
        self._executor = ThreadPoolExecutor(max_workers=2)
        self._status: dict[str, str] = {}  # run_id -> "running"|"completed"|"failed"

    def submit(self, user_request: str) -> str:
        run_id_holder = {}
        def _task():
            result = Coordinator().run(user_request)
            self._status[result.run_id] = "completed"
        future = self._executor.submit(_task)
        ...
```

**设计取舍：** 不引入 Celery/Redis 这类任务队列——本地单用户工具，`ThreadPoolExecutor` 足够，符合"不要为不存在的需求预先设计"的原则。

### 4.3 前端技术栈

| 组件 | 选型 | 理由 |
|---|---|---|
| 框架 | React + Vite + TypeScript | 本地工具不需要 Next.js 的 SSR/路由能力，Vite 开发体验最快 |
| 样式 | Tailwind CSS | 截图那种简洁工作台风格用 utility class 搭最快，不需要设计系统 |
| 数据请求 | TanStack Query | run 列表/详情的请求缓存、轮询（`refetchInterval`）都现成 |
| 本地 UI 状态 | React 内置 state（`useState`/`useReducer`） | 状态不复杂，不需要 Zustand/Redux |
| Markdown 渲染 | `react-markdown` | 渲染 research_note.md 和模型回复 |
| CSV 渲染 | `papaparse` 解析 + 原生 `<table>` | MVP 不需要虚拟滚动的重量级表格库 |
| 图片渲染 | 原生 `<img>` | 静态 PNG，不需要交互式图表库（截图里的 UMAP 图也是静态图片） |

### 4.4 前端组件结构

```
web/
├── src/
│   ├── App.tsx
│   ├── api/
│   │   └── client.ts           # 封装对后端 API 的调用
│   ├── components/
│   │   ├── Sidebar.tsx          # 会话列表（按日期分组）+ New 按钮
│   │   ├── ChatPane.tsx         # 对话流主体
│   │   ├── ChatMessage.tsx      # 单条消息（用户/模型），模型消息含 markdown 渲染
│   │   ├── ArtifactGallery.tsx  # 一排缩略图卡片，支持 "+N more" 折叠
│   │   ├── ArtifactCard.tsx     # 单个缩略图卡片
│   │   ├── ArtifactInspector.tsx # 右侧查看器面板
│   │   ├── WarningBanner.tsx    # 警告展示——必须比正常内容更显眼
│   │   └── ChatInput.tsx        # 输入框（先做静态样式，交互先只做发送）
│   └── types.ts                 # 和后端 schemas 对应的 TS 类型
```

### 4.5 关键组件：`WarningBanner`

这是唯一一个"必须比截图更突出"的地方——Claude Science 的截图里没有这种警告横幅，但我们的产品灵魂就是"诚实暴露局限性"，所以这个组件的视觉优先级要故意做得比 Claude Science 原版更强：

```tsx
function WarningBanner({ warnings }: { warnings: string[] }) {
  if (!warnings.length) return null;
  return (
    <div className="border-2 border-yellow-500 bg-yellow-50 rounded-md p-3 my-2">
      <div className="font-bold text-yellow-800">⚠️ 使用前必读</div>
      <ul className="list-disc pl-5 text-sm text-yellow-900">
        {warnings.map((w, i) => <li key={i}>{w}</li>)}
      </ul>
    </div>
  );
}
```

不允许把警告做成可折叠、可关闭、灰色小字——这是本阶段唯一一条"设计上强行加限制"的规则。

---

## 五、按日拆解（预计 8-10 个工作日）

| Day | 任务 | 产出 |
|---|---|---|
| **Day 1** | FastAPI 骨架：`/api/runs`（列表）、`/api/runs/{id}`（详情）、`/api/runs/{id}/artifacts/{filename}`（静态文件） | 用 curl 能拿到已有 run 的完整数据 |
| **Day 2** | `POST /api/runs` + `RunManager`（线程池触发 + 状态轮询） | curl 能提交新请求并轮询到完成 |
| **Day 3** | 前端骨架：Vite + React + Tailwind，三栏布局（Sidebar / ChatPane / Inspector 空壳） | 页面能跑起来，三个区域占位 |
| **Day 4** | `Sidebar`：拉取 `/api/runs` 列表，按日期分组展示，点击切换 | 左侧栏能看到真实历史 run |
| **Day 5** | `ChatPane` + `ChatMessage`：渲染用户请求 + 模型总结（markdown） | 中间能看到一次 run 的完整对话内容 |
| **Day 6** | `ArtifactGallery` + `ArtifactCard`：缩略图画廊，图片显示缩略图，其他文件类型显示图标 | "GENERATED · N" 那一排效果出来 |
| **Day 7** | `ArtifactInspector`：点击卡片，右侧显示大图/csv 表格/markdown | 核心三件套的最后一块拼上 |
| **Day 8** | `WarningBanner` + `ChatInput` 提交新请求 + 轮询显示进度 | 完整闭环：提交请求 → 等待 → 出现在对话流里 |
| **Day 9** | 端到端联调：真实 LLM 跑一次单标的、一次截面请求，检查所有 artifact 类型渲染正常 | 验收标准里的完整流程跑通 |
| **Day 10** | 打磨：加载态、错误态（run 失败时怎么展示）、空状态（还没有任何 run 时的引导） | 收尾 |

---

## 六、关键技术决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| 后端框架 | FastAPI | 和 VISION.md 里定的技术选型一致，Python 生态天然对接 Coordinator |
| 前端框架 | React + Vite（不用 Next.js） | 本地单用户工具不需要 SSR/服务端路由，Vite 启动快、配置简单 |
| 不用 Streamlit | 已和用户确认 | 三栏可点击交互面板 Streamlit 做起来别扭，直接上 React 更贴近最终形态，避免"做一遍再重做" |
| 新 run 的执行方式 | 线程池 + 前端轮询 | 本地单用户场景，不需要 WebSocket 的复杂度；轮询间隔 1-2 秒足够，实时流式是下一轮迭代 |
| 图表渲染 | 静态 PNG 直接展示，不做交互式图表库 | 截图参照物本身也是静态图（UMAP 散点图），MVP 不需要 Plotly/Recharts 这类重量级依赖 |
| 会话/多轮对话 | v1 里一个 run = 一次请求 + 一个最终回答，不支持在同一个"会话"里追问 | Coordinator 目前的 `run()` 设计就是单次请求-响应，支持真正多轮追问需要改 Coordinator 的状态管理，这是更大的改动，明确排除在这次 UI 工作之外 |
| 警告展示优先级 | 比 Claude Science 原版更显眼（截图里没有对应的警告横幅设计） | 产品灵魂是"诚实暴露局限性"，这个优先级不能因为要模仿截图的简洁感而被牺牲 |

---

## 七、风险与应对

| 风险 | 应对 |
|---|---|
| 前端从 0 搭建，React 组件设计走查耗时可能超预期 | 严格按"核心三件套"范围执行，多标签页/实时流式等明确推到下一轮，不要中途扩大范围 |
| `Coordinator.run()` 是同步阻塞调用，跑截面回测（几百个标的）可能耗时几分钟，纯轮询体验会显得"卡住" | Day 8 就要加一个简单的"运行中"loading 态和已知阶段提示（哪怕只是"正在运行，请稍候"），不需要做到逐步骤展示 |
| CSV 文件（比如 `panel.parquet` 对应的数据）可能很大，直接渲染成 HTML 表格会卡 | 只渲染体积较小的 CSV（如 `backtest_result.json` 摘要、`data_quality_report.json`），大文件（panel.parquet）在 Inspector 里只提供"下载"而不做表格渲染 |
| 警告横幅设计上容易被"做简洁"的美学冲动带偏 | Day 10 打磨阶段专门做一次"警告显眼度"检查，作为验收的一部分，不只是功能测试 |

---

## 八、Phase UI 完成后的检查清单

- [ ] 验收标准里的 5 步完整走通（列表 → 对话流 → 画廊 → Inspector → 提交新请求）
- [ ] 单标的 run 和截面 run 两种 artifact 类型都能在 Inspector 里正确渲染
- [ ] 警告横幅在浏览器里和在终端里同样醒目，没有被样式弱化
- [ ] 提交新请求后，不用刷新页面就能看到结果出现
- [ ] 空状态（没有任何历史 run）和失败状态（run 出错）都有合理提示，不是白屏或报错堆栈
- [ ] 回顾 VISION.md，确认下一轮迭代（多 session 标签页 / 多 artifact 标签页 / 实时流式）的优先级，以及被顺延的 Reviewer Agent 什么时候补上

---

*完成本阶段后，回到 [VISION.md](VISION.md) 更新迭代计划：Reviewer Agent（原 Phase 2）顺延执行，UI 的下一轮迭代（多标签页、实时流式、真正多轮对话）视情况排期。*

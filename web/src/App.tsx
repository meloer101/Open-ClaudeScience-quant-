import { lazy, Suspense, useEffect, useState } from "react";
import { useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  listRuns,
  getRun,
  listLibrary,
  listPapers,
  ingestPaper,
  cancelRun,
  confirmStaging,
  createSession,
  createSessionTurn,
  getSession,
  getConfigStatus,
  setLlmConfig,
} from "./api/client";
import { useRunEvents } from "./hooks/useRunEvents";
import { Sidebar, SidebarToggleIcon } from "./components/Sidebar";
import { SessionTabBar, type SessionTab } from "./components/SessionTabBar";
import { ChatPane } from "./components/ChatPane";
import { LiteratureViewer } from "./components/LiteratureViewer";
import type { OpenArtifactTab } from "./components/ArtifactInspector";
import { ResizeHandle } from "./components/ResizeHandle";
import { ApiKeyModal } from "./components/ApiKeyModal";
import { HomePage } from "./HomePage";

const ArtifactInspector = lazy(() =>
  import("./components/ArtifactInspector").then((module) => ({ default: module.ArtifactInspector })),
);

const DRAFT_ID = "draft";
const PAPER_PREFIX = "paper:";

const SIDEBAR_MIN = 180;
const SIDEBAR_MAX = 480;
const SIDEBAR_DEFAULT = 256;
const INSPECTOR_MIN = 280;
const INSPECTOR_MAX = 720;
const INSPECTOR_DEFAULT = 384;
const CHAT_MIN = 320;

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function artifactKey(runId: string, filename: string): string {
  return `${runId}::${filename}`;
}

function isSessionId(id: string | null): boolean {
  return Boolean(id?.startsWith("session_"));
}

function isPaperTab(id: string | null): boolean {
  return Boolean(id?.startsWith(PAPER_PREFIX));
}

// The Interactive Charts tab isn't backed by a real file (see types.ts
// ArtifactKind), so it needs a fixed synthetic filename/key rather than one
// derived from run_reader.list_artifacts.
const CHARTS_FILENAME = "__charts__";

function WorkbenchApp() {
  const queryClient = useQueryClient();
  const [openTabs, setOpenTabs] = useState<string[]>([]);
  const [activeTabId, setActiveTabId] = useState<string | null>(null);
  const [openArtifactTabs, setOpenArtifactTabs] = useState<OpenArtifactTab[]>([]);
  const [activeArtifactKey, setActiveArtifactKey] = useState<string | null>(null);
  const [sidebarWidth, setSidebarWidth] = useState(SIDEBAR_DEFAULT);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [inspectorWidth, setInspectorWidth] = useState(INSPECTOR_DEFAULT);
  const [inspectorCollapsed, setInspectorCollapsed] = useState(false);
  const [compareRunIds, setCompareRunIds] = useState<string[]>([]);
  const [libraryFilters, setLibraryFilters] = useState({ verdict: "", asset: "", sort: "created_at" });

  const handleSidebarResize = (deltaX: number) => {
    setSidebarWidth((prev) => {
      const next = clamp(prev + deltaX, SIDEBAR_MIN, SIDEBAR_MAX);
      const available = window.innerWidth - next - inspectorWidth;
      return available < CHAT_MIN ? prev : next;
    });
  };

  const handleInspectorResize = (deltaX: number) => {
    setInspectorWidth((prev) => {
      const next = clamp(prev - deltaX, INSPECTOR_MIN, INSPECTOR_MAX);
      const available = window.innerWidth - sidebarWidth - next;
      return available < CHAT_MIN ? prev : next;
    });
  };

  const { data: runs = [], isLoading: isRunsLoading } = useQuery({
    queryKey: ["runs"],
    queryFn: listRuns,
    refetchInterval: 3000,
  });

  const { data: libraryRecords = [] } = useQuery({
    queryKey: ["library", libraryFilters],
    queryFn: () =>
      listLibrary({
        verdict: libraryFilters.verdict,
        asset: libraryFilters.asset,
        sort: libraryFilters.sort,
      }),
    refetchInterval: 3000,
  });

  const { data: papers = [] } = useQuery({ queryKey: ["papers"], queryFn: listPapers, refetchInterval: 5000 });

  const { data: configStatus } = useQuery({
    queryKey: ["config-status"],
    queryFn: getConfigStatus,
    refetchInterval: 5000,
  });

  const handleSaveLlmKey = async (model: string, apiKey: string) => {
    await setLlmConfig(model, apiKey);
    await queryClient.invalidateQueries({ queryKey: ["config-status"] });
  };

  useEffect(() => {
    if (openTabs.length === 0 && runs.length > 0) {
      setOpenTabs([runs[0].run_id]);
      setActiveTabId(runs[0].run_id);
    }
  }, [runs, openTabs.length]);

  const isDraftActive = activeTabId === DRAFT_ID;
  const activeSessionId = isSessionId(activeTabId) ? activeTabId : null;
  const activePaperId = isPaperTab(activeTabId) ? activeTabId!.slice(PAPER_PREFIX.length) : null;
  const activeLegacyRunId = !isDraftActive && !activeSessionId && !activePaperId ? activeTabId : null;

  const { data: currentRun, isLoading: isRunLoading } = useQuery({
    queryKey: ["run", activeLegacyRunId],
    queryFn: () => getRun(activeLegacyRunId!),
    enabled: Boolean(activeLegacyRunId),
    refetchInterval: (query) => (query.state.data?.status === "running" || query.state.data?.status === "awaiting_confirmation" ? 1000 : false),
  });

  const { data: currentSession, isLoading: isSessionLoading } = useQuery({
    queryKey: ["session", activeSessionId],
    queryFn: () => getSession(activeSessionId!),
    enabled: Boolean(activeSessionId),
    refetchInterval: 1000,
  });

  const sessionRunIds = currentSession?.turns.map((turn) => turn.run_id).filter((runId): runId is string => Boolean(runId)) ?? [];
  const sessionRunQueries = useQueries({
    queries: sessionRunIds.map((runId) => ({
      queryKey: ["run", runId],
      queryFn: () => getRun(runId),
      refetchInterval: (query: { state: { data?: { status?: string } } }) =>
        query.state.data?.status === "running" || query.state.data?.status === "awaiting_confirmation" ? 1000 : false,
    })),
  });
  const sessionRuns = sessionRunQueries.map((query) => query.data).filter((run): run is NonNullable<typeof run> => Boolean(run));
  const liveSessionRun = [...sessionRuns]
    .reverse()
    .find((run) => run.status === "running" || run.status === "awaiting_confirmation");
  const liveRunId = liveSessionRun?.run_id ?? (currentRun?.status === "running" || currentRun?.status === "awaiting_confirmation" ? currentRun.run_id : null);
  const liveEvents = useRunEvents(liveRunId, Boolean(liveRunId));

  const sessionTabs: SessionTab[] = openTabs.map((id) => {
    if (id === DRAFT_ID) {
      return { id, label: "New session", status: "draft" };
    }
    if (id.startsWith(PAPER_PREFIX)) {
      const paper = papers.find((item) => item.paper_id === id.slice(PAPER_PREFIX.length));
      return { id, label: paper?.title || "Paper", status: "completed" };
    }
    if (id.startsWith("session_")) {
      const session = currentSession?.session_id === id ? currentSession : null;
      const firstRunId = session?.turns[0]?.run_id;
      const firstRun = firstRunId ? runs.find((run) => run.run_id === firstRunId) : null;
      return {
        id,
        label: firstRun?.user_request || "Session",
        status: liveSessionRun ? liveSessionRun.status : "completed",
      };
    }
    const summary = runs.find((run) => run.run_id === id);
    return {
      id,
      label: summary?.user_request || id,
      status: summary?.status ?? "running",
    };
  });

  const selectTab = (id: string) => {
    setActiveTabId(id);
  };

  const openRunTab = (runId: string) => {
    setOpenTabs((prev) => (prev.includes(runId) ? prev : [...prev, runId]));
    setActiveTabId(runId);
  };

  const openPaperTab = (paperId: string) => {
    const tabId = `${PAPER_PREFIX}${paperId}`;
    setOpenTabs((prev) => (prev.includes(tabId) ? prev : [...prev, tabId]));
    setActiveTabId(tabId);
  };

  const handleImportPaper = async (source: string) => {
    const paper = await ingestPaper(source);
    await queryClient.invalidateQueries({ queryKey: ["papers"] });
    openPaperTab(paper.paper_id);
  };

  const toggleCompare = (runId: string) => {
    setCompareRunIds((prev) => (prev.includes(runId) ? prev.filter((id) => id !== runId) : [...prev, runId]));
  };

  const handleNewTab = () => {
    if (openTabs.includes(DRAFT_ID)) {
      setActiveTabId(DRAFT_ID);
      return;
    }
    setOpenTabs((prev) => [...prev, DRAFT_ID]);
    setActiveTabId(DRAFT_ID);
  };

  const closeTab = (id: string) => {
    setOpenTabs((prev) => {
      const index = prev.indexOf(id);
      const next = prev.filter((tabId) => tabId !== id);
      if (activeTabId === id) {
        const fallback = next[index - 1] ?? next[0] ?? null;
        setActiveTabId(fallback);
      }
      return next;
    });
  };

  const runDetailById = new Map([...(currentRun ? [currentRun] : []), ...sessionRuns].map((run) => [run.run_id, run]));

  const handleSelectArtifact = (runId: string, filename: string) => {
    const run = runDetailById.get(runId);
    if (!run) return;
    const artifact = run.artifacts.find((item) => item.filename === filename);
    if (!artifact) return;
    const key = artifactKey(runId, filename);
    setOpenArtifactTabs((prev) => (prev.some((tab) => tab.key === key) ? prev : [...prev, { key, runId, artifact }]));
    setActiveArtifactKey(key);
  };

  const handleOpenCharts = (runId: string) => {
    const key = artifactKey(runId, CHARTS_FILENAME);
    setOpenArtifactTabs((prev) =>
      prev.some((tab) => tab.key === key)
        ? prev
        : [
            ...prev,
            {
              key,
              runId,
              artifact: { filename: CHARTS_FILENAME, kind: "chart-dashboard", size_bytes: 0 },
            },
          ],
    );
    setActiveArtifactKey(key);
  };

  const closeArtifactTab = (key: string) => {
    setOpenArtifactTabs((prev) => {
      const index = prev.findIndex((tab) => tab.key === key);
      const next = prev.filter((tab) => tab.key !== key);
      if (activeArtifactKey === key) {
        const fallback = next[index - 1] ?? next[0] ?? null;
        setActiveArtifactKey(fallback?.key ?? null);
      }
      return next;
    });
  };

  const handleSubmit = async (request: string) => {
    let sessionId = activeSessionId;
    if (!sessionId) {
      const session = await createSession();
      sessionId = session.session_id;
    }
    await createSessionTurn(sessionId, request);
    setOpenTabs((prev) => {
      if (activeTabId && prev.includes(activeTabId) && activeTabId === DRAFT_ID) {
        return prev.map((id) => (id === activeTabId ? sessionId : id));
      }
      if (prev.includes(sessionId)) {
        return prev;
      }
      return [...prev, sessionId];
    });
    setActiveTabId(sessionId);
    await queryClient.invalidateQueries({ queryKey: ["session", sessionId] });
    await queryClient.invalidateQueries({ queryKey: ["runs"] });
    await queryClient.invalidateQueries({ queryKey: ["library"] });
  };

  const handleStop = async () => {
    if (!liveRunId) return;
    await cancelRun(liveRunId);
    await queryClient.invalidateQueries({ queryKey: ["run", liveRunId] });
    await queryClient.invalidateQueries({ queryKey: ["runs"] });
    await queryClient.invalidateQueries({ queryKey: ["library"] });
  };

  const handleConfirmStaging = async (overrides: Record<string, unknown>) => {
    if (!liveRunId) return;
    await confirmStaging(liveRunId, overrides);
    await queryClient.invalidateQueries({ queryKey: ["run", liveRunId] });
    await queryClient.invalidateQueries({ queryKey: ["runs"] });
  };

  const handleForked = async (runId: string) => {
    openRunTab(runId);
    await queryClient.invalidateQueries({ queryKey: ["runs"] });
    await queryClient.invalidateQueries({ queryKey: ["library"] });
  };

  return (
    <div className="h-screen w-screen flex">
      {configStatus && !configStatus.llm_key_configured && (
        <ApiKeyModal currentModel={configStatus.model} onSubmit={handleSaveLlmKey} />
      )}
      {sidebarCollapsed ? (
        <div className="shrink-0 w-11 h-full bg-warm-50 flex flex-col items-center">
          <div className="h-[45px] flex items-center justify-center shrink-0">
            <button
              type="button"
              onClick={() => setSidebarCollapsed(false)}
              aria-label="展开侧栏"
              title="展开侧栏"
              className="flex items-center justify-center w-8 h-8 rounded-md text-warm-500 hover:bg-warm-100 hover:text-warm-700 transition-colors"
            >
              <SidebarToggleIcon className="w-4 h-4" />
            </button>
          </div>
        </div>
      ) : (
        <>
          <Sidebar
            runs={runs}
            libraryRecords={libraryRecords}
            papers={papers}
            selectedRunId={activeLegacyRunId}
            activePaperId={activePaperId}
            onSelect={openRunTab}
            onOpenPaper={openPaperTab}
            onImportPaper={handleImportPaper}
            onNew={handleNewTab}
            compareRunIds={compareRunIds}
            onToggleCompare={toggleCompare}
            onOpenCompare={() => {
              if (compareRunIds[0]) openRunTab(compareRunIds[0]);
            }}
            libraryFilters={libraryFilters}
            onLibraryFiltersChange={setLibraryFilters}
            isLoading={isRunsLoading}
            width={sidebarWidth}
            onToggleCollapse={() => setSidebarCollapsed(true)}
          />
          <ResizeHandle onResize={handleSidebarResize} />
        </>
      )}
      <div className="flex-1 flex flex-col min-w-0">
        <SessionTabBar tabs={sessionTabs} activeId={activeTabId} onSelect={selectTab} onClose={closeTab} />
        <div className="flex-1 flex min-h-0">
          {activePaperId ? (
            <LiteratureViewer paperId={activePaperId} onOpenRun={openRunTab} />
          ) : (
            <ChatPane
              run={currentRun ?? null}
              session={currentSession ?? null}
              sessionRuns={sessionRuns}
              isLoading={(Boolean(activeLegacyRunId) && isRunLoading) || (Boolean(activeSessionId) && isSessionLoading)}
              isDraft={isDraftActive || openTabs.length === 0}
              liveEvents={liveEvents}
              liveRunId={liveRunId}
              selectedFilename={
                activeArtifactKey ? openArtifactTabs.find((tab) => tab.key === activeArtifactKey)?.artifact.filename ?? null : null
              }
              onSelectArtifact={handleSelectArtifact}
              onOpenCharts={handleOpenCharts}
              isChartsSelected={activeArtifactKey === (activeLegacyRunId ? artifactKey(activeLegacyRunId, CHARTS_FILENAME) : null)}
              isChartsSelectedForRun={(runId) => activeArtifactKey === artifactKey(runId, CHARTS_FILENAME)}
              onSubmit={handleSubmit}
              isRunning={Boolean(liveRunId)}
              onStop={() => void handleStop()}
              onConfirmStaging={handleConfirmStaging}
              compareRunIds={compareRunIds}
              onClearCompare={() => setCompareRunIds([])}
              onForked={handleForked}
            />
          )}
        </div>
      </div>
      {!activePaperId &&
        (inspectorCollapsed ? (
          <div className="shrink-0 w-11 h-full bg-warm-50 flex flex-col items-center">
            <div className="h-[45px] flex items-center justify-center shrink-0">
              <button
                type="button"
                onClick={() => setInspectorCollapsed(false)}
                aria-label="展开 Artifact 面板"
                title="展开 Artifact 面板"
                className="flex items-center justify-center w-8 h-8 rounded-md text-warm-500 hover:bg-warm-100 hover:text-warm-700 transition-colors"
              >
                <SidebarToggleIcon className="w-4 h-4" />
              </button>
            </div>
          </div>
        ) : (
          <>
            <ResizeHandle onResize={handleInspectorResize} />
            <Suspense fallback={<div className="h-full border-l border-slate-200 bg-white" style={{ width: inspectorWidth }} />}>
              <ArtifactInspector
                tabs={openArtifactTabs}
                activeKey={activeArtifactKey}
                onSelectTab={setActiveArtifactKey}
                onCloseTab={closeArtifactTab}
                width={inspectorWidth}
                onToggleCollapse={() => setInspectorCollapsed(true)}
              />
            </Suspense>
          </>
        ))}
    </div>
  );
}

function App() {
  if (window.location.pathname === "/" || window.location.pathname === "/home") {
    return <HomePage />;
  }

  return <WorkbenchApp />;
}

export default App;

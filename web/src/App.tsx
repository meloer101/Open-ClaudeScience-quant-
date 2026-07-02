import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { listRuns, createRun, getRun, listLibrary } from "./api/client";
import { useRunEvents } from "./hooks/useRunEvents";
import { Sidebar } from "./components/Sidebar";
import { SessionTabBar, type SessionTab } from "./components/SessionTabBar";
import { ChatPane } from "./components/ChatPane";
import { ArtifactInspector, type OpenArtifactTab } from "./components/ArtifactInspector";
import { ResizeHandle } from "./components/ResizeHandle";

const DRAFT_ID = "draft";

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

function App() {
  const queryClient = useQueryClient();
  const [openTabs, setOpenTabs] = useState<string[]>([]);
  const [activeTabId, setActiveTabId] = useState<string | null>(null);
  const [openArtifactTabs, setOpenArtifactTabs] = useState<OpenArtifactTab[]>([]);
  const [activeArtifactKey, setActiveArtifactKey] = useState<string | null>(null);
  const [sidebarWidth, setSidebarWidth] = useState(SIDEBAR_DEFAULT);
  const [inspectorWidth, setInspectorWidth] = useState(INSPECTOR_DEFAULT);
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

  useEffect(() => {
    if (openTabs.length === 0 && runs.length > 0) {
      setOpenTabs([runs[0].run_id]);
      setActiveTabId(runs[0].run_id);
    }
  }, [runs, openTabs.length]);

  const isDraftActive = activeTabId === DRAFT_ID;
  const activeRunId = isDraftActive ? null : activeTabId;

  const { data: currentRun, isLoading: isRunLoading } = useQuery({
    queryKey: ["run", activeRunId],
    queryFn: () => getRun(activeRunId!),
    enabled: Boolean(activeRunId),
    refetchInterval: (query) => (query.state.data?.status === "running" ? 1000 : false),
  });

  const liveEvents = useRunEvents(activeRunId, currentRun?.status === "running");

  const sessionTabs: SessionTab[] = openTabs.map((id) => {
    if (id === DRAFT_ID) {
      return { id, label: "New session", status: "draft" };
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

  const handleSelectArtifact = (filename: string) => {
    if (!activeRunId || !currentRun) return;
    const artifact = currentRun.artifacts.find((item) => item.filename === filename);
    if (!artifact) return;
    const key = artifactKey(activeRunId, filename);
    setOpenArtifactTabs((prev) => (prev.some((tab) => tab.key === key) ? prev : [...prev, { key, runId: activeRunId, artifact }]));
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
    const { run_id } = await createRun(request);
    setOpenTabs((prev) => {
      if (activeTabId && prev.includes(activeTabId) && (activeTabId === DRAFT_ID || activeTabId === run_id)) {
        return prev.map((id) => (id === activeTabId ? run_id : id));
      }
      return [...prev, run_id];
    });
    setActiveTabId(run_id);
    await queryClient.invalidateQueries({ queryKey: ["runs"] });
    await queryClient.invalidateQueries({ queryKey: ["library"] });
  };

  const handleForked = async (runId: string) => {
    openRunTab(runId);
    await queryClient.invalidateQueries({ queryKey: ["runs"] });
    await queryClient.invalidateQueries({ queryKey: ["library"] });
  };

  return (
    <div className="h-screen w-screen flex">
      <Sidebar
        runs={runs}
        libraryRecords={libraryRecords}
        selectedRunId={activeRunId}
        onSelect={openRunTab}
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
      />
      <ResizeHandle onResize={handleSidebarResize} />
      <div className="flex-1 flex flex-col min-w-0">
        <SessionTabBar tabs={sessionTabs} activeId={activeTabId} onSelect={selectTab} onClose={closeTab} />
        <div className="flex-1 flex min-h-0">
          <ChatPane
            run={currentRun ?? null}
            isLoading={Boolean(activeRunId) && isRunLoading}
            isDraft={isDraftActive || openTabs.length === 0}
            liveEvents={liveEvents}
            selectedFilename={
              activeArtifactKey ? openArtifactTabs.find((tab) => tab.key === activeArtifactKey)?.artifact.filename ?? null : null
            }
            onSelectArtifact={handleSelectArtifact}
            onSubmit={handleSubmit}
            compareRunIds={compareRunIds}
            onClearCompare={() => setCompareRunIds([])}
            onForked={handleForked}
          />
          <ResizeHandle onResize={handleInspectorResize} />
          <ArtifactInspector
            tabs={openArtifactTabs}
            activeKey={activeArtifactKey}
            onSelectTab={setActiveArtifactKey}
            onCloseTab={closeArtifactTab}
            width={inspectorWidth}
          />
        </div>
      </div>
    </div>
  );
}

export default App;

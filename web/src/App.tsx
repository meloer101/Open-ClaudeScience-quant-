import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { listRuns, createRun, getRun } from "./api/client";
import { useRunEvents } from "./hooks/useRunEvents";
import { Sidebar } from "./components/Sidebar";
import { SessionTabBar, type SessionTab } from "./components/SessionTabBar";
import { ChatPane } from "./components/ChatPane";
import { ArtifactInspector, type OpenArtifactTab } from "./components/ArtifactInspector";

const DRAFT_ID = "draft";

function artifactKey(runId: string, filename: string): string {
  return `${runId}::${filename}`;
}

function App() {
  const queryClient = useQueryClient();
  const [openTabs, setOpenTabs] = useState<string[]>([]);
  const [activeTabId, setActiveTabId] = useState<string | null>(null);
  const [openArtifactTabs, setOpenArtifactTabs] = useState<OpenArtifactTab[]>([]);
  const [activeArtifactKey, setActiveArtifactKey] = useState<string | null>(null);

  const { data: runs = [], isLoading: isRunsLoading } = useQuery({
    queryKey: ["runs"],
    queryFn: listRuns,
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
  };

  return (
    <div className="h-screen w-screen flex">
      <Sidebar
        runs={runs}
        selectedRunId={activeRunId}
        onSelect={openRunTab}
        onNew={handleNewTab}
        isLoading={isRunsLoading}
      />
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
          />
          <ArtifactInspector
            tabs={openArtifactTabs}
            activeKey={activeArtifactKey}
            onSelectTab={setActiveArtifactKey}
            onCloseTab={closeArtifactTab}
          />
        </div>
      </div>
    </div>
  );
}

export default App;

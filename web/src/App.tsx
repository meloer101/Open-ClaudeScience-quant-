import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { listRuns, createRun, getRun } from "./api/client";
import type { ArtifactInfo } from "./types";
import { Sidebar } from "./components/Sidebar";
import { ChatPane } from "./components/ChatPane";
import { ArtifactInspector } from "./components/ArtifactInspector";

function App() {
  const queryClient = useQueryClient();
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [selectedArtifact, setSelectedArtifact] = useState<ArtifactInfo | null>(null);

  const { data: runs = [], isLoading } = useQuery({
    queryKey: ["runs"],
    queryFn: listRuns,
    refetchInterval: 3000,
  });

  useEffect(() => {
    if (!selectedRunId && runs.length > 0) {
      setSelectedRunId(runs[0].run_id);
    }
  }, [runs, selectedRunId]);

  // Single source of truth for the selected run's detail (including its
  // artifact list) - kept reactive via useQuery so a click right after
  // selecting a run always sees fresh data, instead of reading a stale
  // snapshot out of the cache during render.
  const { data: currentRun, isLoading: isRunLoading } = useQuery({
    queryKey: ["run", selectedRunId],
    queryFn: () => getRun(selectedRunId!),
    enabled: Boolean(selectedRunId),
    refetchInterval: (query) => (query.state.data?.status === "running" ? 1000 : false),
  });

  const handleSelectArtifact = (filename: string) => {
    const artifact = currentRun?.artifacts.find((item) => item.filename === filename) ?? null;
    setSelectedArtifact(artifact);
  };

  const handleNew = () => {
    setSelectedRunId(null);
    setSelectedArtifact(null);
  };

  const handleSubmit = async (request: string) => {
    const { run_id } = await createRun(request);
    setSelectedRunId(run_id);
    setSelectedArtifact(null);
    await queryClient.invalidateQueries({ queryKey: ["runs"] });
  };

  return (
    <div className="h-screen w-screen flex">
      <Sidebar
        runs={runs}
        selectedRunId={selectedRunId}
        onSelect={(id) => {
          setSelectedRunId(id);
          setSelectedArtifact(null);
        }}
        onNew={handleNew}
        isLoading={isLoading}
      />
      <ChatPane
        run={currentRun ?? null}
        isLoading={Boolean(selectedRunId) && isRunLoading}
        selectedFilename={selectedArtifact?.filename ?? null}
        onSelectArtifact={handleSelectArtifact}
        onSubmit={handleSubmit}
      />
      <ArtifactInspector
        runId={selectedRunId}
        artifact={selectedArtifact}
        onClose={() => setSelectedArtifact(null)}
      />
    </div>
  );
}

export default App;

import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { runEventsUrl } from "../api/client";
import type { RunEvent } from "../types";

/**
 * Streams live tool-call progress for a run via SSE while it's active.
 * Resets its event list whenever `runId` changes. On a terminal event
 * ("final"/"error") it invalidates the run-detail query so the completed
 * run's real data (metrics, artifacts, research note) takes over rendering.
 */
export function useRunEvents(runId: string | null, isRunning: boolean) {
  const [events, setEvents] = useState<RunEvent[]>([]);
  const queryClient = useQueryClient();
  const sourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    setEvents([]);
    sourceRef.current?.close();
    sourceRef.current = null;

    if (!runId || !isRunning) return;

    const source = new EventSource(runEventsUrl(runId));
    sourceRef.current = source;

    source.onmessage = (message) => {
      const event = JSON.parse(message.data) as RunEvent;
      setEvents((prev) => [...prev, event]);
      if (event.type === "final" || event.type === "error") {
        source.close();
        void queryClient.invalidateQueries({ queryKey: ["run", runId] });
        void queryClient.invalidateQueries({ queryKey: ["runs"] });
      }
    };

    // If the run finished before we could open a live stream (e.g. it was
    // already done, or the connection dropped), the source just closes with
    // no messages - fall back to the regular polling query, which already
    // covers that case.
    source.onerror = () => {
      source.close();
    };

    return () => {
      source.close();
    };
  }, [runId, isRunning, queryClient]);

  return events;
}

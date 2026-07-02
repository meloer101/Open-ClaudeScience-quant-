import { useState } from "react";
import { forkRun } from "../api/client";

interface ForkRunFormProps {
  runId: string;
  onForked: (runId: string) => void;
}

export function ForkRunForm({ runId, onForked }: ForkRunFormProps) {
  const [modification, setModification] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    const trimmed = modification.trim();
    if (!trimmed || isSubmitting) return;
    setIsSubmitting(true);
    setError(null);
    try {
      const response = await forkRun(runId, trimmed);
      setModification("");
      onForked(response.run_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Fork failed");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="mt-4 border-t border-warm-100 pt-3">
      <div className="text-xs font-medium text-warm-500 mb-2">Fork</div>
      <div className="flex gap-2">
        <input
          value={modification}
          onChange={(event) => setModification(event.target.value)}
          placeholder="把回看窗口从20日改成60日"
          className="flex-1 min-w-0 text-sm border border-warm-150 rounded-md px-2 py-1.5 outline-none focus:border-accent-400"
        />
        <button
          onClick={submit}
          disabled={!modification.trim() || isSubmitting}
          className="text-sm px-3 py-1.5 rounded-md bg-warm-900 text-white disabled:bg-warm-200 disabled:text-warm-500"
        >
          Fork
        </button>
      </div>
      {error && <div className="mt-1 text-xs text-danger-600">{error}</div>}
    </div>
  );
}

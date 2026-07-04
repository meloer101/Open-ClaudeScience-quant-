import { useState } from "react";
import { estimateRunCost, type CostEstimate } from "../api/client";

interface ChatInputProps {
  onSubmit: (request: string) => Promise<void>;
  isRunning?: boolean;
  onStop?: () => void;
}

export function ChatInput({ onSubmit, isRunning = false, onStop }: ChatInputProps) {
  const [value, setValue] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [estimate, setEstimate] = useState<CostEstimate | null>(null);

  const handleSubmit = async () => {
    const trimmed = value.trim();
    if (!trimmed || isSubmitting || isRunning) return;
    setIsSubmitting(true);
    try {
      await onSubmit(trimmed);
      setValue("");
      setEstimate(null);
    } finally {
      setIsSubmitting(false);
    }
  };

  const refreshEstimate = async (nextValue: string) => {
    setValue(nextValue);
    const trimmed = nextValue.trim();
    if (trimmed.length < 20) {
      setEstimate(null);
      return;
    }
    try {
      setEstimate(await estimateRunCost(trimmed));
    } catch {
      setEstimate(null);
    }
  };

  const busy = isSubmitting || isRunning;

  return (
    <div className="p-3">
      <div className="border border-warm-150 rounded-2xl bg-white flex items-end gap-2 px-3.5 py-2.5 focus-within:border-warm-400 transition-colors">
        <textarea
          value={value}
          onChange={(e) => void refreshEstimate(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void handleSubmit();
            }
          }}
          placeholder="Describe the factor, universe, and review you want to run…"
          rows={1}
          className="flex-1 resize-none outline-none text-sm py-1 max-h-40 text-warm-900 placeholder:text-warm-400"
        />
        <button
          onClick={() => (isRunning ? onStop?.() : void handleSubmit())}
          disabled={isSubmitting || (!isRunning && !value.trim())}
          className="shrink-0 w-8 h-8 rounded-full bg-warm-900 text-white disabled:bg-warm-200 flex items-center justify-center transition-colors"
          aria-label={isRunning ? "Stop" : "Send"}
        >
          {isRunning ? <span className="w-2.5 h-2.5 bg-white rounded-[2px]" /> : busy ? "…" : "↑"}
        </button>
      </div>
      <div className="mt-2 min-h-5 text-[11px] leading-5 text-warm-500">
        {estimate
          ? `Preflight: ~${estimate.estimated_tokens.toLocaleString()} tokens, ~$${estimate.estimated_usd.toFixed(4)}. Research only, not investment advice.`
          : "Research artifacts only; outputs are not investment advice."}
      </div>
    </div>
  );
}

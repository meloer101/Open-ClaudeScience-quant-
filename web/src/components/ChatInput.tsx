import { useState } from "react";

interface ChatInputProps {
  onSubmit: (request: string) => Promise<void>;
}

export function ChatInput({ onSubmit }: ChatInputProps) {
  const [value, setValue] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async () => {
    const trimmed = value.trim();
    if (!trimmed || isSubmitting) return;
    setIsSubmitting(true);
    try {
      await onSubmit(trimmed);
      setValue("");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="p-3">
      <div className="border border-warm-150 rounded-2xl bg-white flex items-end gap-2 px-3.5 py-2.5 focus-within:border-warm-400 transition-colors">
        <textarea
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void handleSubmit();
            }
          }}
          placeholder="Ask anything — @ for artifacts, # for sessions, / for skills, ⌘K to search…"
          rows={1}
          className="flex-1 resize-none outline-none text-sm py-1 max-h-40 text-warm-900 placeholder:text-warm-400"
        />
        <button
          onClick={() => void handleSubmit()}
          disabled={isSubmitting || !value.trim()}
          className="shrink-0 w-8 h-8 rounded-full bg-warm-900 text-white disabled:bg-warm-200 flex items-center justify-center transition-colors"
          aria-label="Send"
        >
          {isSubmitting ? "…" : "↑"}
        </button>
      </div>
    </div>
  );
}

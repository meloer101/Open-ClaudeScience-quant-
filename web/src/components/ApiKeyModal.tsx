import { useState } from "react";

interface ApiKeyModalProps {
  currentModel: string;
  onSubmit: (model: string, apiKey: string) => Promise<void>;
}

// Mirrors quantbench.api.llm_key.provider_key_env: litellm resolves a
// model's provider from the text before the first "/" and reads
// "<PROVIDER>_API_KEY" by convention, so the live label here matches
// whatever env var the backend will actually write the key to.
function providerKeyEnv(model: string): string {
  const provider = model.includes("/") ? model.split("/", 1)[0] : model;
  const normalized = provider.replace(/[^a-zA-Z0-9]+/g, "_").replace(/^_+|_+$/g, "").toUpperCase();
  return normalized ? `${normalized}_API_KEY` : "";
}

export function ApiKeyModal({ currentModel, onSubmit }: ApiKeyModalProps) {
  const [model, setModel] = useState(currentModel);
  const [apiKey, setApiKey] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const keyEnv = providerKeyEnv(model);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!model.trim()) {
      setError("请输入模型名称");
      return;
    }
    if (!apiKey.trim()) {
      setError("请输入 API key");
      return;
    }
    setIsSubmitting(true);
    setError(null);
    try {
      await onSubmit(model.trim(), apiKey.trim());
    } catch {
      setError("保存失败，请检查后端是否正在运行后重试");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
      <div className="w-full max-w-sm rounded-xl border border-slate-200 bg-white p-6 shadow-xl">
        <h2 className="text-base font-semibold text-slate-900">配置模型与 API Key</h2>
        <p className="mt-2 text-sm text-slate-600">
          还没有检测到可用的 LLM API key。填入 litellm 支持的模型名称（如 <code>deepseek/deepseek-chat</code>、
          <code>openai/gpt-4o</code>、<code>moonshot/kimi-k2</code>）和对应的 API key，保存后立即生效，并写入本地
          <code className="mx-1 rounded bg-slate-100 px-1 py-0.5 text-xs">~/.quantbench/.env</code>
          ，下次启动无需重新输入。
        </p>
        <form onSubmit={handleSubmit} className="mt-4 space-y-3">
          <div>
            <label htmlFor="model-input" className="mb-1 block text-xs font-medium text-slate-700">
              模型名称
            </label>
            <input
              id="model-input"
              type="text"
              autoFocus
              placeholder="deepseek/deepseek-chat"
              value={model}
              onChange={(event) => setModel(event.target.value)}
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none"
            />
          </div>
          <div>
            <label htmlFor="api-key-input" className="mb-1 block text-xs font-medium text-slate-700">
              API Key{keyEnv && <span className="text-slate-400"> · 将保存为 {keyEnv}</span>}
            </label>
            <input
              id="api-key-input"
              type="password"
              placeholder="sk-..."
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none"
            />
          </div>
          {error && <p className="text-sm text-red-600">{error}</p>}
          <button
            type="submit"
            disabled={isSubmitting}
            className="w-full rounded-lg bg-slate-900 px-3 py-2 text-sm font-medium text-white disabled:opacity-60"
          >
            {isSubmitting ? "保存中…" : "保存并开始使用"}
          </button>
        </form>
      </div>
    </div>
  );
}

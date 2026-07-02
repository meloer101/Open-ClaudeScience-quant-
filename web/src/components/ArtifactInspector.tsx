import { useQuery } from "@tanstack/react-query";
import Markdown from "react-markdown";
import Papa from "papaparse";
import type { ArtifactInfo } from "../types";
import { artifactUrl } from "../api/client";

export interface OpenArtifactTab {
  key: string; // `${runId}::${filename}`
  runId: string;
  artifact: ArtifactInfo;
}

interface ArtifactInspectorProps {
  tabs: OpenArtifactTab[];
  activeKey: string | null;
  onSelectTab: (key: string) => void;
  onCloseTab: (key: string) => void;
}

function useArtifactText(runId: string | null, artifact: ArtifactInfo | null) {
  const needsText = artifact && artifact.kind !== "image" && artifact.kind !== "binary";
  return useQuery({
    queryKey: ["artifact-text", runId, artifact?.filename],
    queryFn: async () => {
      const response = await fetch(artifactUrl(runId!, artifact!.filename));
      return response.text();
    },
    enabled: Boolean(runId && needsText),
  });
}

function CsvTable({ text }: { text: string }) {
  const parsed = Papa.parse<string[]>(text.trim(), { skipEmptyLines: true });
  const rows = parsed.data;
  if (rows.length === 0) return <div className="text-slate-400 text-sm">Empty file</div>;
  const [header, ...body] = rows;
  const truncated = body.length > 200;
  const visibleBody = truncated ? body.slice(0, 200) : body;

  return (
    <div className="overflow-auto">
      <table className="text-xs border-collapse w-full">
        <thead>
          <tr>
            {header.map((cell, i) => (
              <th key={i} className="border border-slate-200 bg-slate-50 px-2 py-1 text-left sticky top-0">
                {cell}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {visibleBody.map((row, ri) => (
            <tr key={ri}>
              {row.map((cell, ci) => (
                <td key={ci} className="border border-slate-200 px-2 py-1 whitespace-nowrap">
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {truncated && (
        <div className="text-xs text-slate-400 mt-2">
          Showing first 200 of {body.length} rows — download for the full file.
        </div>
      )}
    </div>
  );
}

function ArtifactBody({ runId, artifact }: { runId: string; artifact: ArtifactInfo }) {
  const { data: text, isLoading } = useArtifactText(runId, artifact);
  const url = artifactUrl(runId, artifact.filename);

  return (
    <div className="flex-1 overflow-auto p-3">
      {artifact.kind === "image" && <img src={url} alt={artifact.filename} className="w-full rounded" />}
      {artifact.kind === "binary" && (
        <div className="text-sm text-slate-500">
          这个文件太大或不适合直接预览，
          <a href={url} download={artifact.filename} className="text-blue-600 underline ml-1">
            点这里下载
          </a>
          。
        </div>
      )}
      {isLoading && artifact.kind !== "image" && artifact.kind !== "binary" && (
        <div className="text-sm text-slate-400">Loading…</div>
      )}
      {text !== undefined && artifact.kind === "markdown" && (
        <div className="prose prose-sm max-w-none">
          <Markdown>{text}</Markdown>
        </div>
      )}
      {text !== undefined && artifact.kind === "csv" && <CsvTable text={text} />}
      {text !== undefined && (artifact.kind === "json" || artifact.kind === "yaml" || artifact.kind === "code") && (
        <pre className="text-xs bg-slate-50 border border-slate-200 rounded p-3 overflow-auto whitespace-pre-wrap">
          {text}
        </pre>
      )}
    </div>
  );
}

export function ArtifactInspector({ tabs, activeKey, onSelectTab, onCloseTab }: ArtifactInspectorProps) {
  const activeTab = tabs.find((tab) => tab.key === activeKey) ?? null;

  if (tabs.length === 0) {
    return (
      <div className="w-96 shrink-0 border-l border-slate-200 bg-white h-full flex items-center justify-center text-sm text-slate-400 p-6 text-center">
        点击左侧生成的 artifact 卡片，在这里查看详情
      </div>
    );
  }

  return (
    <div className="w-96 shrink-0 border-l border-slate-200 bg-white h-full flex flex-col">
      <div className="flex items-stretch border-b border-slate-200 overflow-x-auto shrink-0">
        {tabs.map((tab) => (
          <div
            key={tab.key}
            onClick={() => onSelectTab(tab.key)}
            className={`group flex items-center gap-1.5 px-2.5 py-2 text-xs border-r border-slate-200 cursor-pointer max-w-32 shrink-0 ${
              tab.key === activeKey ? "bg-white font-medium text-slate-800" : "bg-slate-50 text-slate-500 hover:bg-slate-100"
            }`}
            title={tab.artifact.filename}
          >
            <span className="truncate">{tab.artifact.filename}</span>
            <button
              onClick={(event) => {
                event.stopPropagation();
                onCloseTab(tab.key);
              }}
              className="opacity-0 group-hover:opacity-100 text-slate-400 hover:text-slate-700 shrink-0"
              aria-label={`Close ${tab.artifact.filename}`}
            >
              ✕
            </button>
          </div>
        ))}
      </div>
      {activeTab && (
        <>
          <div className="flex items-center justify-between px-3 py-1.5 border-b border-slate-100 shrink-0">
            <span className="text-xs text-slate-400">{activeTab.artifact.kind}</span>
            <a
              href={artifactUrl(activeTab.runId, activeTab.artifact.filename)}
              download={activeTab.artifact.filename}
              className="text-xs text-slate-500 hover:text-slate-800"
              title="Download"
            >
              ⬇ download
            </a>
          </div>
          <ArtifactBody runId={activeTab.runId} artifact={activeTab.artifact} />
        </>
      )}
    </div>
  );
}

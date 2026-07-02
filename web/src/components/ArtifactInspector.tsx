import { useQuery } from "@tanstack/react-query";
import Markdown from "react-markdown";
import Papa from "papaparse";
import type { ArtifactInfo } from "../types";
import { artifactUrl } from "../api/client";

function FileIcon() {
  return (
    <svg viewBox="0 0 16 16" width="12" height="12" className="shrink-0 text-warm-400" aria-hidden>
      <path
        d="M3.5 1.5h6l3 3v10a.5.5 0 0 1-.5.5h-8.5a.5.5 0 0 1-.5-.5v-12a.5.5 0 0 1 .5-.5z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1"
      />
      <path d="M9.5 1.5v3h3" fill="none" stroke="currentColor" strokeWidth="1" />
    </svg>
  );
}

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
  width: number;
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
  if (rows.length === 0) return <div className="text-warm-400 text-sm">Empty file.</div>;
  const [header, ...body] = rows;
  const truncated = body.length > 200;
  const visibleBody = truncated ? body.slice(0, 200) : body;

  return (
    <div className="overflow-auto">
      <table className="text-xs border-collapse w-full">
        <thead>
          <tr>
            {header.map((cell, i) => (
              <th key={i} className="border border-warm-100 bg-warm-50 px-2 py-1 text-left sticky top-0 font-medium text-warm-700">
                {cell}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {visibleBody.map((row, ri) => (
            <tr key={ri}>
              {row.map((cell, ci) => (
                <td key={ci} className="border border-warm-100 px-2 py-1 whitespace-nowrap text-warm-800">
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {truncated && (
        <div className="text-xs text-warm-400 mt-2">
          Showing first 200 of {body.length} rows. Download for the full file.
        </div>
      )}
    </div>
  );
}

function ArtifactBody({ runId, artifact }: { runId: string; artifact: ArtifactInfo }) {
  const { data: text, isLoading } = useArtifactText(runId, artifact);
  const url = artifactUrl(runId, artifact.filename);

  return (
    <div className="flex-1 overflow-auto p-4">
      {artifact.kind === "image" && <img src={url} alt={artifact.filename} className="w-full rounded-lg" />}
      {artifact.kind === "binary" && (
        <div className="text-sm text-warm-500">
          这个文件太大或不适合直接预览，
          <a href={url} download={artifact.filename} className="text-accent-600 underline ml-1">
            点这里下载
          </a>
          。
        </div>
      )}
      {isLoading && artifact.kind !== "image" && artifact.kind !== "binary" && (
        <div className="text-sm text-warm-400">Loading…</div>
      )}
      {text !== undefined && artifact.kind === "markdown" && (
        <div className="prose prose-sm max-w-none">
          <Markdown>{text}</Markdown>
        </div>
      )}
      {text !== undefined && artifact.kind === "csv" && <CsvTable text={text} />}
      {text !== undefined && (artifact.kind === "json" || artifact.kind === "yaml" || artifact.kind === "code") && (
        <pre className="text-xs bg-warm-50 border border-warm-100 rounded-lg p-3 overflow-auto whitespace-pre-wrap text-warm-800">
          {text}
        </pre>
      )}
    </div>
  );
}

export function ArtifactInspector({ tabs, activeKey, onSelectTab, onCloseTab, width }: ArtifactInspectorProps) {
  const activeTab = tabs.find((tab) => tab.key === activeKey) ?? null;

  if (tabs.length === 0) {
    return (
      <div
        className="shrink-0 bg-white h-full flex items-center justify-center text-sm text-warm-400 p-6 text-center"
        style={{ width }}
      >
        点击左侧生成的 artifact 卡片，在这里查看详情
      </div>
    );
  }

  return (
    <div className="shrink-0 bg-white h-full flex flex-col overflow-hidden" style={{ width }}>
      <div className="flex items-center gap-1 bg-warm-25 border-b border-warm-100 overflow-x-auto shrink-0 p-1.5">
        {tabs.map((tab) => (
          <div
            key={tab.key}
            onClick={() => onSelectTab(tab.key)}
            className={`flex items-center gap-1.5 pl-2.5 pr-2 py-1.5 text-xs rounded-lg cursor-pointer max-w-36 shrink-0 transition-colors ${
              tab.key === activeKey ? "bg-warm-100 text-warm-900" : "text-warm-500 hover:bg-warm-100/60"
            }`}
            title={tab.artifact.filename}
          >
            <FileIcon />
            <span className="truncate">{tab.artifact.filename}</span>
            <button
              onClick={(event) => {
                event.stopPropagation();
                onCloseTab(tab.key);
              }}
              className="text-warm-400 hover:text-warm-700 shrink-0 leading-none w-3.5 text-center"
              aria-label={`Close ${tab.artifact.filename}`}
            >
              ×
            </button>
          </div>
        ))}
      </div>
      {activeTab && (
        <>
          <div className="flex items-center justify-between px-3.5 py-2 border-b border-warm-100 shrink-0">
            <span className="text-xs text-warm-400">{activeTab.artifact.kind}</span>
            <a
              href={artifactUrl(activeTab.runId, activeTab.artifact.filename)}
              download={activeTab.artifact.filename}
              className="text-xs text-warm-500 hover:text-warm-800"
              title="Download"
            >
              Download
            </a>
          </div>
          <ArtifactBody runId={activeTab.runId} artifact={activeTab.artifact} />
        </>
      )}
    </div>
  );
}

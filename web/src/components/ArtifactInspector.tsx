import { useQuery } from "@tanstack/react-query";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import Papa from "papaparse";
import type { ArtifactInfo, ParquetPreview } from "../types";
import { artifactUrl, previewParquet } from "../api/client";
import { ChartsPanel } from "./ChartsPanel";

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
  onToggleCollapse: () => void;
}

function InspectorToggleIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 16 16" fill="none" className={className} aria-hidden="true">
      <rect x="1.5" y="2.5" width="13" height="11" rx="1.5" stroke="currentColor" strokeWidth="1.2" />
      <line x1="10" y1="2.5" x2="10" y2="13.5" stroke="currentColor" strokeWidth="1.2" />
    </svg>
  );
}

function useArtifactText(runId: string | null, artifact: ArtifactInfo | null) {
  const needsText = artifact && artifact.kind !== "image" && artifact.kind !== "binary" && artifact.kind !== "chart-dashboard";
  return useQuery({
    queryKey: ["artifact-text", runId, artifact?.filename],
    queryFn: async () => {
      const response = await fetch(artifactUrl(runId!, artifact!.filename));
      return response.text();
    },
    enabled: Boolean(runId && needsText),
  });
}

function DataTable({
  headers,
  rows,
  truncatedNote,
}: {
  headers: string[];
  rows: (string | number)[][];
  truncatedNote?: string;
}) {
  if (rows.length === 0) return <div className="text-warm-400 text-sm">Empty file.</div>;

  return (
    <div className="overflow-auto">
      <table className="text-xs border-collapse w-full">
        <thead>
          <tr>
            {headers.map((cell, i) => (
              <th key={i} className="border border-warm-100 bg-warm-50 px-2 py-1 text-left sticky top-0 font-medium text-warm-700">
                {cell}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, ri) => (
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
      {truncatedNote && <div className="text-xs text-warm-400 mt-2">{truncatedNote}</div>}
    </div>
  );
}

function CsvTable({ text }: { text: string }) {
  const parsed = Papa.parse<string[]>(text.trim(), { skipEmptyLines: true });
  const rows = parsed.data;
  if (rows.length === 0) return <div className="text-warm-400 text-sm">Empty file.</div>;
  const [header, ...body] = rows;
  const truncated = body.length > 200;
  const visibleBody = truncated ? body.slice(0, 200) : body;

  return (
    <DataTable
      headers={header}
      rows={visibleBody}
      truncatedNote={truncated ? `Showing first 200 of ${body.length} rows. Download for the full file.` : undefined}
    />
  );
}

function ParquetTable({ runId, filename }: { runId: string; filename: string }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["parquet-preview", runId, filename],
    queryFn: () => previewParquet(runId, filename),
  });

  if (isLoading) return <div className="text-sm text-warm-400">Loading…</div>;
  if (error || !data) return <div className="text-sm text-danger-600">Failed to preview this file.</div>;

  const preview = data as ParquetPreview;
  const rows = preview.rows.map((row) => preview.columns.map((column) => formatCell(row[column])));

  return (
    <DataTable
      headers={preview.columns}
      rows={rows}
      truncatedNote={
        preview.truncated ? `Showing first ${preview.rows.length} of ${preview.total_rows} rows. Download for the full file.` : undefined
      }
    />
  );
}

function formatCell(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function tabLabel(artifact: ArtifactInfo): string {
  return artifact.kind === "chart-dashboard" ? "Interactive Charts" : artifact.filename;
}

function ReproductionComparisonCard({ text }: { text: string }) {
  let data: import("../types").ReproductionComparison;
  try {
    data = JSON.parse(text);
  } catch {
    return <pre className="text-xs text-danger-600">{text}</pre>;
  }
  const source = (data.literature_source ?? {}) as Record<string, unknown>;
  const fmt = (value: number | null, sign = false): string => {
    if (value === null || value === undefined) return "—";
    return sign ? (value >= 0 ? `+${value.toFixed(3)}` : value.toFixed(3)) : value.toFixed(3);
  };
  return (
    <div className="space-y-4">
      <div>
        <div className="text-sm font-medium text-warm-900">文献复现对比 · {data.factor_name}</div>
        {typeof source.citation === "string" && (
          <div className="text-xs text-warm-400 mt-0.5">{source.citation}</div>
        )}
        <div className="text-xs text-warm-400">
          {data.reported_sample_period ? `论文样本区间 ${data.reported_sample_period}` : ""}
          {data.reported_universe ? ` · ${data.reported_universe}` : ""}
        </div>
      </div>
      <table className="w-full text-xs border border-warm-100 rounded-lg overflow-hidden">
        <thead className="bg-warm-50 text-warm-500">
          <tr>
            <th className="text-left px-2 py-1.5">指标</th>
            <th className="text-right px-2 py-1.5">论文报告</th>
            <th className="text-right px-2 py-1.5">本地复现</th>
            <th className="text-right px-2 py-1.5">差异</th>
          </tr>
        </thead>
        <tbody>
          {data.rows.map((row) => (
            <tr key={row.metric} className="border-t border-warm-50">
              <td className="px-2 py-1.5 text-warm-800">{row.label}</td>
              <td className="px-2 py-1.5 text-right text-warm-700">{fmt(row.reported)}</td>
              <td className="px-2 py-1.5 text-right text-warm-700">{fmt(row.reproduced)}</td>
              <td className="px-2 py-1.5 text-right text-warm-600">{fmt(row.delta, true)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {data.assumptions?.length > 0 && (
        <div>
          <div className="text-xs font-medium text-warm-600 mb-1">复现假设（论文未明确）</div>
          <ul className="text-xs text-warm-600 list-disc pl-4 space-y-0.5">
            {data.assumptions.map((item, i) => (
              <li key={i}>{item}</li>
            ))}
          </ul>
        </div>
      )}
      {data.known_caveats?.length > 0 && (
        <div>
          <div className="text-xs font-medium text-warm-600 mb-1">已知局限</div>
          <ul className="text-xs text-warm-600 list-disc pl-4 space-y-0.5">
            {data.known_caveats.map((item, i) => (
              <li key={i}>{item}</li>
            ))}
          </ul>
        </div>
      )}
      <div className="text-xs text-warm-400 border-t border-warm-100 pt-2">{data.note}</div>
    </div>
  );
}

function ArtifactBody({ runId, artifact }: { runId: string; artifact: ArtifactInfo }) {
  const { data: text, isLoading } = useArtifactText(runId, artifact);
  const url = artifactUrl(runId, artifact.filename);
  const isParquet = artifact.kind === "binary" && artifact.filename.endsWith(".parquet");
  const isReproComparison = artifact.filename === "reproduction_comparison.json";

  if (artifact.kind === "chart-dashboard") {
    return <ChartsPanel runId={runId} />;
  }

  return (
    <>
      {artifact.kind === "image" && <img src={url} alt={artifact.filename} className="w-full block" />}
      {isParquet && <ParquetTable runId={runId} filename={artifact.filename} />}
      {artifact.kind === "binary" && !isParquet && (
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
          <Markdown remarkPlugins={[remarkGfm]}>{text}</Markdown>
        </div>
      )}
      {text !== undefined && artifact.kind === "csv" && <CsvTable text={text} />}
      {text !== undefined && isReproComparison && <ReproductionComparisonCard text={text} />}
      {text !== undefined && !isReproComparison && (artifact.kind === "json" || artifact.kind === "yaml" || artifact.kind === "code") && (
        <pre className="text-xs bg-warm-50 border border-warm-100 rounded-lg p-3 overflow-auto whitespace-pre-wrap text-warm-800">
          {text}
        </pre>
      )}
    </>
  );
}

export function ArtifactInspector({ tabs, activeKey, onSelectTab, onCloseTab, width, onToggleCollapse }: ArtifactInspectorProps) {
  const activeTab = tabs.find((tab) => tab.key === activeKey) ?? null;

  return (
    <div className="shrink-0 bg-warm-50 h-full flex flex-col overflow-hidden" style={{ width }}>
      <div className="flex items-center gap-1 bg-warm-50 shrink-0 p-1.5">
        <div className="flex items-center gap-1 flex-1 min-w-0 overflow-x-auto">
          {tabs.map((tab) => (
            <div
              key={tab.key}
              onClick={() => onSelectTab(tab.key)}
              className={`flex items-center gap-1.5 pl-2.5 pr-2 py-1.5 text-sm rounded-lg cursor-pointer max-w-36 shrink-0 transition-colors ${
                tab.key === activeKey ? "bg-warm-100 text-warm-900" : "text-warm-500 hover:bg-warm-100/60"
              }`}
              title={tabLabel(tab.artifact)}
            >
              <FileIcon />
              <span className="truncate">{tabLabel(tab.artifact)}</span>
              <button
                onClick={(event) => {
                  event.stopPropagation();
                  onCloseTab(tab.key);
                }}
                className="text-warm-400 hover:text-warm-700 shrink-0 leading-none w-4 text-center"
                aria-label={`Close ${tabLabel(tab.artifact)}`}
              >
                ×
              </button>
            </div>
          ))}
        </div>
        <button
          type="button"
          onClick={onToggleCollapse}
          aria-label="收起 Artifact 面板"
          title="收起 Artifact 面板"
          className="shrink-0 p-1 rounded-md text-warm-400 hover:bg-warm-100 hover:text-warm-600 transition-colors"
        >
          <InspectorToggleIcon className="w-4 h-4" />
        </button>
      </div>
      {activeTab ? (
        <div className="flex-1 min-h-0 p-3">
          <div className="h-full flex flex-col rounded-xl border border-warm-150 bg-white overflow-hidden">
            <div className="shrink-0 flex items-center justify-between px-3.5 py-2 border-b border-warm-100">
              <span className="text-xs text-warm-400">{activeTab.artifact.kind}</span>
              {activeTab.artifact.kind !== "chart-dashboard" && (
                <a
                  href={artifactUrl(activeTab.runId, activeTab.artifact.filename)}
                  download={activeTab.artifact.filename}
                  className="text-xs text-warm-500 hover:text-warm-800"
                  title="Download"
                >
                  Download
                </a>
              )}
            </div>
            <div className="shrink-0 px-3.5 py-2 text-[11px] leading-4 text-warm-500 border-b border-warm-100 bg-warm-25">
              Research artifact only. Not investment advice or an automated trading instruction.
            </div>
            <div className="flex-1 overflow-auto p-4">
              <ArtifactBody runId={activeTab.runId} artifact={activeTab.artifact} />
            </div>
          </div>
        </div>
      ) : (
        <div className="flex-1 flex items-center justify-center text-sm text-warm-400 p-6 text-center">
          点击左侧生成的 artifact 卡片，在这里查看详情
        </div>
      )}
    </div>
  );
}

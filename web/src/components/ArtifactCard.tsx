import type { ArtifactInfo } from "../types";
import { artifactUrl } from "../api/client";

const KIND_ICON: Record<ArtifactInfo["kind"], string> = {
  image: "🖼️",
  csv: "📊",
  markdown: "📝",
  json: "🗂️",
  yaml: "⚙️",
  code: "🧩",
  binary: "📦",
};

interface ArtifactCardProps {
  runId: string;
  artifact: ArtifactInfo;
  isSelected: boolean;
  onClick: () => void;
}

export function ArtifactCard({ runId, artifact, isSelected, onClick }: ArtifactCardProps) {
  return (
    <button
      onClick={onClick}
      className={`w-32 shrink-0 rounded-lg border bg-white overflow-hidden text-left hover:shadow-md transition-shadow ${
        isSelected ? "border-blue-500 ring-2 ring-blue-200" : "border-slate-200"
      }`}
    >
      <div className="h-20 bg-slate-50 flex items-center justify-center overflow-hidden">
        {artifact.kind === "image" ? (
          <img
            src={artifactUrl(runId, artifact.filename)}
            alt={artifact.filename}
            className="object-cover w-full h-full"
          />
        ) : (
          <span className="text-3xl">{KIND_ICON[artifact.kind]}</span>
        )}
      </div>
      <div className="px-2 py-1.5 text-xs text-slate-700 truncate" title={artifact.filename}>
        {artifact.filename}
      </div>
    </button>
  );
}

import type { ArtifactInfo } from "../types";
import { artifactUrl } from "../api/client";

function extensionLabel(filename: string): string {
  const ext = filename.split(".").pop() ?? "";
  return ext.toUpperCase();
}

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
      className={`w-36 shrink-0 rounded-xl border overflow-hidden text-left bg-white transition-colors ${
        isSelected ? "border-warm-900" : "border-warm-150 hover:border-warm-300"
      }`}
    >
      <div className="h-24 bg-warm-50 flex items-center justify-center overflow-hidden">
        {artifact.kind === "image" ? (
          <img
            src={artifactUrl(runId, artifact.filename)}
            alt={artifact.filename}
            className="object-cover w-full h-full"
          />
        ) : (
          <span className="text-xs font-medium tracking-wide text-warm-400">{extensionLabel(artifact.filename)}</span>
        )}
      </div>
      <div className="px-2.5 py-2 text-xs text-warm-700 truncate" title={artifact.filename}>
        {artifact.filename}
      </div>
    </button>
  );
}

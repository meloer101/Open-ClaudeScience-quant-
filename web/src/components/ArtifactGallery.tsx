import { useState } from "react";
import type { ArtifactInfo } from "../types";
import { ArtifactCard } from "./ArtifactCard";

interface ArtifactGalleryProps {
  runId: string;
  artifacts: ArtifactInfo[];
  selectedFilename: string | null;
  onSelect: (filename: string) => void;
}

const COLLAPSED_COUNT = 5;

export function ArtifactGallery({ runId, artifacts, selectedFilename, onSelect }: ArtifactGalleryProps) {
  const [expanded, setExpanded] = useState(false);
  if (artifacts.length === 0) return null;

  const visible = expanded ? artifacts : artifacts.slice(0, COLLAPSED_COUNT);
  const remaining = artifacts.length - visible.length;

  return (
    <div className="mt-4">
      <div className="text-xs text-warm-400 mb-2">Generated · {artifacts.length}</div>
      <div className="flex gap-2.5 overflow-x-auto pb-1">
        {visible.map((artifact) => (
          <ArtifactCard
            key={artifact.filename}
            runId={runId}
            artifact={artifact}
            isSelected={artifact.filename === selectedFilename}
            onClick={() => onSelect(artifact.filename)}
          />
        ))}
        {!expanded && remaining > 0 && (
          <button
            onClick={() => setExpanded(true)}
            className="w-36 h-[104px] shrink-0 rounded-xl border border-warm-150 text-sm text-warm-500 hover:bg-warm-50 transition-colors"
          >
            +{remaining} more
          </button>
        )}
      </div>
    </div>
  );
}

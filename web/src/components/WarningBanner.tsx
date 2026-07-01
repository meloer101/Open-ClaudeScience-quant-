interface WarningBannerProps {
  warnings: string[];
}

// Deliberately more prominent than a typical "AI workbench" polish pass would
// make it: this project's whole premise is honestly surfacing limitations, so
// warnings must never be styled down to something easy to skim past.
export function WarningBanner({ warnings }: WarningBannerProps) {
  if (warnings.length === 0) return null;

  return (
    <div className="border-2 border-amber-500 bg-amber-50 rounded-lg p-4 my-3">
      <div className="font-bold text-amber-900 mb-2 flex items-center gap-2">
        <span aria-hidden>⚠️</span>
        使用前必读 — review before trusting this result
      </div>
      <ul className="list-disc pl-5 space-y-1 text-sm text-amber-900">
        {warnings.map((warning, index) => (
          <li key={index}>{warning}</li>
        ))}
      </ul>
    </div>
  );
}

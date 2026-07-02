interface WarningBannerProps {
  warnings: string[];
}

// Deliberately more prominent than a typical "AI workbench" polish pass would
// make it: this project's whole premise is honestly surfacing limitations, so
// warnings must never be styled down to something easy to skim past. This is
// the one place we intentionally diverge from the reference's quiet palette.
export function WarningBanner({ warnings }: WarningBannerProps) {
  if (warnings.length === 0) return null;

  return (
    <div className="border border-warn-200 bg-warn-50 rounded-xl p-4 my-3">
      <div className="font-medium text-warn-900 mb-2 flex items-center gap-2">
        <span aria-hidden>⚠</span>
        使用前必读 — review before trusting this result
      </div>
      <ul className="list-disc pl-5 space-y-1 text-sm text-warn-900">
        {warnings.map((warning, index) => (
          <li key={index}>{warning}</li>
        ))}
      </ul>
    </div>
  );
}

import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  SEED_RESEARCH_NOTE_HEADING,
  SEED_RUN_ID,
  SEED_RUN_REQUEST,
  SEED_RUN_SUMMARY,
  SEED_RUN_WARNING,
} from "./fixtures";

// Writes a fake completed run straight into the real runs/ directory (the
// same one quantbench.config.RUNS_DIR points at) so the E2E backend and
// frontend processes - real processes, not a TestClient - have something to
// read. runs/ is gitignored, so this never touches version control; the
// matching global-teardown removes it again after the suite finishes.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const RUNS_DIR = path.resolve(__dirname, "../../runs");

export default function globalSetup() {
  const runDir = path.join(RUNS_DIR, SEED_RUN_ID);
  rmSync(runDir, { recursive: true, force: true });
  mkdirSync(runDir, { recursive: true });

  const manifest = {
    run_id: SEED_RUN_ID,
    user_request: SEED_RUN_REQUEST,
    created_at: new Date().toISOString(),
    summary: SEED_RUN_SUMMARY,
    metrics: { sharpe: 1.23, annual_return: 0.18 },
    warnings: [SEED_RUN_WARNING],
  };
  writeFileSync(path.join(runDir, "manifest.json"), JSON.stringify(manifest), "utf-8");
  writeFileSync(path.join(runDir, "config.yaml"), "hypothesis: e2e seed run\n", "utf-8");
  writeFileSync(
    path.join(runDir, "backtest_result.json"),
    JSON.stringify({ metrics: manifest.metrics }),
    "utf-8",
  );
  writeFileSync(path.join(runDir, "research_note.md"), `${SEED_RESEARCH_NOTE_HEADING}\n\nSeeded by Playwright.\n`, "utf-8");
  writeFileSync(path.join(runDir, "signal.py"), "def compute(df):\n    return df['close'].pct_change(20)\n", "utf-8");
  // Smallest valid PNG (1x1 transparent pixel) - real bytes so the artifact
  // browser's image preview has something decodable to render, not just a
  // file that exists.
  writeFileSync(
    path.join(runDir, "equity_curve.png"),
    Buffer.from(
      "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
      "base64",
    ),
  );
}

import { rmSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { SEED_RUN_ID } from "./fixtures";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const RUNS_DIR = path.resolve(__dirname, "../../runs");

export default function globalTeardown() {
  rmSync(path.join(RUNS_DIR, SEED_RUN_ID), { recursive: true, force: true });
}

import { expect, test } from "@playwright/test";
import {
  SEED_RESEARCH_NOTE_HEADING,
  SEED_RUN_REQUEST,
  SEED_RUN_SUMMARY,
  SEED_RUN_WARNING,
} from "./fixtures";

test("browsing a run end-to-end: sidebar -> detail -> warnings -> artifact", async ({ page }) => {
  await page.goto("/");

  // Scoped with hasText (checks innerText) rather than the role's accessible
  // name: the sidebar row's StatusDot contributes an aria-label ("completed")
  // to that name, and the session tab bar's "Close <label>" button is a
  // superset-string match on the raw request text too.
  const sidebarEntry = page.getByRole("button", { name: SEED_RUN_REQUEST }).filter({ hasText: SEED_RUN_REQUEST });
  await expect(sidebarEntry).toBeVisible();
  await sidebarEntry.click();

  // Selecting the run should render its request as the active session's
  // message, plus the honesty-first surfaces this project cares about:
  // warnings are never buried and the summary is always shown.
  await expect(page.getByText(SEED_RUN_REQUEST).first()).toBeVisible();
  await expect(page.getByText(SEED_RUN_WARNING)).toBeVisible();
  await expect(page.getByText(SEED_RUN_SUMMARY)).toBeVisible();

  // Opening a generated artifact routes through the ArtifactInspector panel.
  await page.getByRole("button", { name: "research_note.md" }).click();
  const renderedHeading = SEED_RESEARCH_NOTE_HEADING.replace(/^#\s*/, "");
  await expect(page.getByText(renderedHeading)).toBeVisible();
});

test("run list groups the seeded run under Today", async ({ page }) => {
  await page.goto("/");

  const todayGroup = page.getByText("Today", { exact: true });
  await expect(todayGroup).toBeVisible();

  const group = todayGroup.locator("xpath=..");
  await expect(group.getByText(SEED_RUN_REQUEST)).toBeVisible();
});

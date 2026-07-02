import { describe, expect, it } from "vitest";
import { findingByCheck, formatTimestampLabel, monthlyGroupReturnHeatmap } from "./deriveChartData";
import type { ReviewFindingPayload } from "../../types";

describe("findingByCheck", () => {
  const findings: ReviewFindingPayload[] = [
    { check: "lookahead", severity: "critical", message: "uses future data", detail: {} },
    { check: "cost_sensitivity", severity: "info", message: "fyi only", detail: {} },
  ];

  it("returns the matching non-info finding", () => {
    expect(findingByCheck(findings, "lookahead")?.message).toBe("uses future data");
  });

  it("ignores info-severity findings even if the check matches", () => {
    expect(findingByCheck(findings, "cost_sensitivity")).toBeNull();
  });

  it("returns null when no finding matches the check", () => {
    expect(findingByCheck(findings, "turnover")).toBeNull();
  });
});

describe("formatTimestampLabel", () => {
  it("truncates an ISO timestamp to the date portion", () => {
    expect(formatTimestampLabel("2024-03-15T00:00:00Z")).toBe("2024-03-15");
  });
});

describe("monthlyGroupReturnHeatmap", () => {
  it("averages per-group returns within each month", () => {
    const timestamps = ["2024-01-01", "2024-01-02", "2024-02-01"];
    const groupReturns = {
      "1": [0.1, 0.3, 0.2],
      "2": [-0.1, -0.3, 0.0],
    };

    const result = monthlyGroupReturnHeatmap(timestamps, groupReturns);

    expect(result.rowLabels).toEqual(["G1", "G2"]);
    expect(result.columnLabels).toEqual(["2024-01", "2024-02"]);
    expect(result.values).toEqual([
      [0.2, 0.2],
      [-0.2, 0.0],
    ]);
  });

  it("skips null/NaN values instead of letting them corrupt the average", () => {
    const timestamps = ["2024-01-01", "2024-01-02"];
    const groupReturns = { "1": [0.5, null as unknown as number] };

    const result = monthlyGroupReturnHeatmap(timestamps, groupReturns);

    expect(result.values).toEqual([[0.5]]);
  });

  it("returns null for a group/month bucket with no data at all", () => {
    const timestamps = ["2024-01-01", "2024-02-01"];
    const groupReturns = { "1": [0.5] };

    const result = monthlyGroupReturnHeatmap(timestamps, groupReturns);

    expect(result.values).toEqual([[0.5, null]]);
  });

  it("sorts group keys numerically, not lexicographically", () => {
    const timestamps = ["2024-01-01"];
    const groupReturns = { "10": [1], "2": [2] };

    const result = monthlyGroupReturnHeatmap(timestamps, groupReturns);

    expect(result.rowLabels).toEqual(["G2", "G10"]);
  });
});

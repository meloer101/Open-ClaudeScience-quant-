import { describe, expect, it } from "vitest";
import { linearScale, niceTicks, nearestIndex, padDomain } from "./scale";

describe("linearScale", () => {
  it("maps the domain endpoints onto the range endpoints", () => {
    const scale = linearScale([0, 100], [0, 200]);
    expect(scale(0)).toBe(0);
    expect(scale(100)).toBe(200);
    expect(scale(50)).toBe(100);
  });

  it("extrapolates outside the domain", () => {
    const scale = linearScale([0, 10], [0, 100]);
    expect(scale(-10)).toBe(-100);
    expect(scale(20)).toBe(200);
  });

  it("maps a degenerate domain to the range midpoint instead of NaN", () => {
    const scale = linearScale([5, 5], [0, 100]);
    expect(scale(5)).toBe(50);
    expect(scale(999)).toBe(50);
  });

  it("exposes the domain and range it was built with", () => {
    const scale = linearScale([1, 2], [3, 4]);
    expect(scale.domain).toEqual([1, 2]);
    expect(scale.range).toEqual([3, 4]);
  });
});

describe("padDomain", () => {
  it("expands a domain by the given fraction on both sides", () => {
    expect(padDomain([0, 100], 0.1)).toEqual([-10, 110]);
  });

  it("defaults to an 8% margin", () => {
    const [min, max] = padDomain([0, 100]);
    expect(min).toBeCloseTo(-8);
    expect(max).toBeCloseTo(108);
  });

  it("no-ops on a degenerate domain", () => {
    expect(padDomain([5, 5])).toEqual([5, 5]);
  });
});

describe("niceTicks", () => {
  it("returns count evenly-spaced ticks including both endpoints", () => {
    expect(niceTicks(0, 100, 5)).toEqual([0, 25, 50, 75, 100]);
  });

  it("falls back to just the endpoints on a degenerate domain", () => {
    expect(niceTicks(5, 5, 4)).toEqual([5, 5]);
  });

  it("falls back to just the endpoints when count < 2", () => {
    expect(niceTicks(0, 10, 1)).toEqual([0, 10]);
  });
});

describe("nearestIndex", () => {
  it("returns 0 for a single-sample series regardless of pointer position", () => {
    expect(nearestIndex(999, 500, 1)).toBe(0);
    expect(nearestIndex(0, 500, 1)).toBe(0);
  });

  it("maps a pointer position to the nearest sample index", () => {
    expect(nearestIndex(0, 100, 11)).toBe(0);
    expect(nearestIndex(100, 100, 11)).toBe(10);
    expect(nearestIndex(50, 100, 11)).toBe(5);
  });

  it("clamps out-of-bounds pointer positions", () => {
    expect(nearestIndex(-50, 100, 11)).toBe(0);
    expect(nearestIndex(500, 100, 11)).toBe(10);
  });
});

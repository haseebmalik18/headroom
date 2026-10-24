import { describe, expect, it } from "vitest";

import { formatMs, linearScale, linearTicks, logScale, logTicks, niceMax, valueScale } from "./scale";

describe("scales", () => {
  it("maps linearly", () => {
    const x = linearScale([0, 100], [0, 400]);
    expect(x(25)).toBe(100);
  });

  it("maps logarithmically", () => {
    const x = logScale([1, 1000], [0, 300]);
    expect(x(10)).toBeCloseTo(100);
    expect(x(1000)).toBeCloseTo(300);
  });

  it("rounds maxima up to a nice number", () => {
    expect(niceMax(831)).toBe(1000);
    expect(niceMax(127)).toBe(150);
    expect(niceMax(42)).toBe(50);
    expect(niceMax(8)).toBe(8);
  });

  it("makes ticks", () => {
    expect(linearTicks(1000)).toEqual([0, 250, 500, 750, 1000]);
    expect(logTicks(3, 2500)).toEqual([1, 10, 100, 1000, 10000]);
  });

  it("switches to a log scale when values span more than 10x", () => {
    expect(valueScale([5, 2500], [0, 100]).log).toBe(true);
    expect(valueScale([40, 120], [0, 100]).log).toBe(false);
  });

  it("formats milliseconds compactly", () => {
    expect(formatMs(2450.4)).toBe("2,450 ms");
    expect(formatMs(5.23)).toBe("5.2 ms");
    expect(formatMs(127.4)).toBe("127 ms");
  });
});

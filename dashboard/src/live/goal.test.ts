import { describe, expect, it } from "vitest";

import { goalText, higherIsBetter, show } from "./goal";

describe("goal", () => {
  it("describes latency, throughput and error-rate goals in their own units", () => {
    expect(goalText("p99_ms", 100)).toBe("p99 latency under 100 ms");
    expect(goalText("throughput_rps", 240)).toBe("throughput of at least 240 req/s");
    expect(goalText("error_rate", 0.001)).toBe("error rate under 0.1%");
  });

  it("formats values for each metric", () => {
    expect(show("p99_ms", 1858.4)).toBe("1,858 ms");
    expect(show("p99_ms", 8.42)).toBe("8.4 ms");
    expect(show("throughput_rps", 186.04)).toBe("186 req/s");
    expect(show("error_rate", 0.0213)).toBe("2.13%");
  });

  it("knows which direction is better", () => {
    expect(higherIsBetter("throughput_rps")).toBe(true);
    expect(higherIsBetter("p99_ms")).toBe(false);
  });
});

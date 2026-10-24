import { describe, expect, it } from "vitest";

import { formatHash, parseHash } from "./hash";

describe("hash", () => {
  it("round-trips a run and a step", () => {
    const hash = formatHash({ run: "20261023-221348-auth-service", step: "race-1" });
    expect(hash).toBe("#run=20261023-221348-auth-service&step=race-1");
    expect(parseHash(hash)).toEqual({ run: "20261023-221348-auth-service", step: "race-1" });
  });

  it("tolerates an empty or partial hash", () => {
    expect(parseHash("")).toEqual({});
    expect(parseHash("#run=x")).toEqual({ run: "x" });
  });
});

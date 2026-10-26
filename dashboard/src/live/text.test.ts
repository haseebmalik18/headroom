import { describe, expect, it } from "vitest";

import { shortTitle } from "./text";

describe("shortTitle", () => {
  it("keeps the first clause of a long title", () => {
    expect(shortTitle("Cache stampede on hot SKUs, flooding the database")).toBe("Cache stampede on hot SKUs");
  });

  it("shortens at a word boundary", () => {
    expect(shortTitle("The five dashboard queries execute sequentially within each request and add up"))
      .toBe("The five dashboard queries execute sequentially within each…");
  });
});

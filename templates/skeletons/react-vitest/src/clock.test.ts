import { afterEach, describe, expect, it, vi } from "vitest";
import { now } from "./clock";

describe("now", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("answers the time a test sets", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2030-01-31T23:59:00Z"));
    expect(now().toISOString()).toBe("2030-01-31T23:59:00.000Z");
  });
});

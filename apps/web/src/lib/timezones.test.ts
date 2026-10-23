import { describe, expect, it } from "vitest";

import { timeZoneOptions, timeZones } from "@/lib/timezones";

describe("time zones", () => {
  it("list UTC first", () => {
    expect(timeZones()[0]).toBe("UTC");
  });

  it("keep a stored zone the browser lists under another name", () => {
    const listed = ["UTC", "Asia/Calcutta", "Europe/Berlin"];
    expect(timeZoneOptions("Asia/Kolkata", listed)).toEqual(["Asia/Kolkata", ...listed]);
    expect(timeZoneOptions("Europe/Berlin", listed)).toBe(listed);
    expect(timeZoneOptions("", listed)).toBe(listed);
  });
});

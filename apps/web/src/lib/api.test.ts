import { describe, expect, it } from "vitest";

import { errorFrom } from "@/lib/api";

describe("errorFrom", () => {
  it("reads the server's error envelope", () => {
    const error = errorFrom(404, { error: { code: "not_found", message: "Workflow not found.", request_id: "req-1" } });
    expect(error).toMatchObject({ status: 404, code: "not_found", message: "Workflow not found.", requestId: "req-1" });
  });

  it("falls back when the body is not an envelope", () => {
    expect(errorFrom(502, "<html>bad gateway</html>")).toMatchObject({ code: "server_error" });
    expect(errorFrom(400, null)).toMatchObject({ code: "request_failed" });
  });
});

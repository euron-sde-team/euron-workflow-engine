import { describe, expect, it } from "vitest";

import { serializeEnv } from "@/lib/runtime-env";

describe("serializeEnv", () => {
  it("emits the configured values and trims trailing slashes", () => {
    const script = serializeEnv({ API_URL: "https://api.example.com/", PRODUCT_NAME: "Acme Automations" });
    expect(script).toBe('window.__WFE__={"apiUrl":"https://api.example.com","productName":"Acme Automations"};');
  });

  it("falls back to local defaults", () => {
    expect(serializeEnv({})).toContain('"apiUrl":"http://localhost:8130"');
  });

  it("cannot close the script tag it is served in", () => {
    const script = serializeEnv({ PRODUCT_NAME: "</script><script>alert(1)</script>" });
    expect(script).not.toContain("</script>");
  });
});

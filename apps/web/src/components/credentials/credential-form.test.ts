import { describe, expect, it } from "vitest";

import { initialValues, toPayload } from "@/components/credentials/credential-form";
import type { Credential, CredentialType } from "@/lib/types";

const postgres: CredentialType = {
  type: "postgres",
  name: "Postgres connection",
  description: "",
  icon: "database",
  secret_fields: ["password"],
  json_schema: {
    type: "object",
    required: ["host", "database", "user", "password"],
    properties: {
      host: { type: "string" },
      port: { type: "integer", default: 5432 },
      database: { type: "string" },
      user: { type: "string" },
      password: { type: "string", "x-secret": true },
      ssl_mode: { type: "string", enum: ["disable", "prefer"], default: "prefer" },
    },
  },
};

const stored: Credential = {
  id: "c1",
  name: "Warehouse",
  type: "postgres",
  description: "",
  public_fields: { host: "db", port: 5433, database: "wh", user: "reader", ssl_mode: "disable" },
  secret_fields: ["password"],
  key_provider: "kms",
  version: 1,
  used_by: [],
  created_at: "2026-10-01T00:00:00Z",
  updated_at: "2026-10-01T00:00:00Z",
  last_used_at: null,
};

describe("credential forms", () => {
  it("start from defaults for a new credential", () => {
    expect(initialValues(postgres)).toEqual({
      host: "",
      port: "5432",
      database: "",
      user: "",
      password: "",
      ssl_mode: "prefer",
    });
  });

  it("show stored public fields but never a secret", () => {
    expect(initialValues(postgres, stored)).toMatchObject({
      host: "db",
      port: "5433",
      password: "",
    });
  });

  it("send numbers as numbers and keep blank secrets out of an edit", () => {
    const values = { ...initialValues(postgres, stored), host: "db2" };
    expect(toPayload(postgres, values, true)).toEqual({
      host: "db2",
      port: 5433,
      database: "wh",
      user: "reader",
      ssl_mode: "disable",
    });
    expect(toPayload(postgres, { ...values, password: "s3cret" }, false)).toMatchObject({
      password: "s3cret",
    });
  });
});

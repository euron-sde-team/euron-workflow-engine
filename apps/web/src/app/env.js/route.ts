import { serializeEnv } from "@/lib/runtime-env";

// Read at request time, so one image serves every environment.
export const dynamic = "force-dynamic";

export function GET(): Response {
  return new Response(serializeEnv(process.env), {
    headers: {
      "content-type": "application/javascript; charset=utf-8",
      "cache-control": "no-store",
    },
  });
}

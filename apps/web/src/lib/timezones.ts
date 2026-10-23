let zones: string[] | null = null;

/** Every IANA zone the browser knows, UTC first. */
export function timeZones(): string[] {
  if (!zones) {
    const supported = (Intl as unknown as { supportedValuesOf?: (key: string) => string[] })
      .supportedValuesOf;
    const found = supported ? supported("timeZone") : [];
    zones = ["UTC", ...found.filter((zone) => zone !== "UTC")];
  }
  return zones;
}

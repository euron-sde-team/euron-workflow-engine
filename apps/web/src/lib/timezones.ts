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

/**
 * The zones to offer in a select that currently holds `current`. Browsers list some zones
 * under their legacy ICU names (Chrome offers Asia/Calcutta, not Asia/Kolkata), so a stored
 * zone can be missing from the list; it is added, never silently replaced by the first entry.
 */
export function timeZoneOptions(current: string | null | undefined, all = timeZones()): string[] {
  if (!current || all.includes(current)) return all;
  return [current, ...all];
}

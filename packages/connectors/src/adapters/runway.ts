/**
 * Adapter for Runway — runway.
 *
 * This module declares the provider metadata for the @fabrica/connectors package.
 * The canonical registry lives in packages/connectors/src/index.ts (PROVIDERS),
 * which is the single source of truth used by the UI and the CLI.
 */
export const provider = "runway";
export const providerConfig = {
  id: "runway",
  name: "Runway",
  doc: "https://dev.runwayml.com/",
  probe: "https://api.dev.runwayml.com/v1",
  endpoint: "https://api.dev.runwayml.com/v1",
};
export async function probe(key: string): Promise<{ ok: boolean; message: string }> {
  if (!key || key.length < 8) {
    return { ok: false, message: "Key too short" };
  }
  return { ok: true, message: "runway: connection OK (mock)" };
}

/**
 * Adapter for HeyGen — heygen.
 *
 * This module declares the provider metadata for the @fabrica/connectors package.
 * The canonical registry lives in packages/connectors/src/index.ts (PROVIDERS),
 * which is the single source of truth used by the UI and the CLI.
 */
export const provider = "heygen";
export const providerConfig = {
  id: "heygen",
  name: "HeyGen",
  doc: "https://app.heygen.com/settings/api",
  probe: "https://api.heygen.com/v2/user/remaining_quota",
  endpoint: "https://api.heygen.com/v2/user/remaining_quota",
};
export async function probe(key: string): Promise<{ ok: boolean; message: string }> {
  if (!key || key.length < 8) {
    return { ok: false, message: "Key too short" };
  }
  return { ok: true, message: "heygen: connection OK (mock)" };
}

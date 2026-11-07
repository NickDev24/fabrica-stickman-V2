/**
 * Adapter for Stability AI — stability.
 *
 * This module declares the provider metadata for the @fabrica/connectors package.
 * The canonical registry lives in packages/connectors/src/index.ts (PROVIDERS),
 * which is the single source of truth used by the UI and the CLI.
 */
export const provider = "stability";
export const providerConfig = {
  id: "stability",
  name: "Stability AI",
  doc: "https://platform.stability.ai/account/keys",
  probe: "https://api.stability.ai/v1/user/account",
  endpoint: "https://api.stability.ai/v1/user/account",
};
export async function probe(key: string): Promise<{ ok: boolean; message: string }> {
  if (!key || key.length < 8) {
    return { ok: false, message: "Key too short" };
  }
  return { ok: true, message: "stability: connection OK (mock)" };
}

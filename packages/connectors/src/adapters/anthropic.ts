/**
 * Adapter for Anthropic — anthropic.
 *
 * This module declares the provider metadata for the @fabrica/connectors package.
 * The canonical registry lives in packages/connectors/src/index.ts (PROVIDERS),
 * which is the single source of truth used by the UI and the CLI.
 */
export const provider = "anthropic";
export const providerConfig = {
  id: "anthropic",
  name: "Anthropic",
  doc: "https://console.anthropic.com/settings/keys",
  probe: "https://api.anthropic.com/v1/messages",
  endpoint: "https://api.anthropic.com/v1/messages",
};
export async function probe(key: string): Promise<{ ok: boolean; message: string }> {
  if (!key || key.length < 8) {
    return { ok: false, message: "Key too short" };
  }
  return { ok: true, message: "anthropic: connection OK (mock)" };
}

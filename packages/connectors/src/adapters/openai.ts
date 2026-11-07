/**
 * Adapter for OpenAI — openai.
 *
 * This module declares the provider metadata for the @fabrica/connectors package.
 * The canonical registry lives in packages/connectors/src/index.ts (PROVIDERS),
 * which is the single source of truth used by the UI and the CLI.
 */
export const provider = "openai";
export const providerConfig = {
  id: "openai",
  name: "OpenAI",
  doc: "https://platform.openai.com/api-keys",
  probe: "https://api.openai.com/v1/models",
  endpoint: "https://api.openai.com/v1/chat/completions",
};
export async function probe(key: string): Promise<{ ok: boolean; message: string }> {
  if (!key || key.length < 8) {
    return { ok: false, message: "Key too short" };
  }
  return { ok: true, message: "openai: connection OK (mock)" };
}

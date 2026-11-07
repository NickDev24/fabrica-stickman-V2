/**
 * Adapter for Google Gemini — gemini.
 *
 * This module declares the provider metadata for the @fabrica/connectors package.
 * The canonical registry lives in packages/connectors/src/index.ts (PROVIDERS),
 * which is the single source of truth used by the UI and the CLI.
 */
export const provider = "gemini";
export const providerConfig = {
  id: "gemini",
  name: "Google Gemini",
  doc: "https://aistudio.google.com/app/apikey",
  probe: "https://generativelanguage.googleapis.com/v1beta/models",
  endpoint: "https://generativelanguage.googleapis.com/v1beta/models",
};
export async function probe(key: string): Promise<{ ok: boolean; message: string }> {
  if (!key || key.length < 8) {
    return { ok: false, message: "Key too short" };
  }
  return { ok: true, message: "gemini: connection OK (mock)" };
}

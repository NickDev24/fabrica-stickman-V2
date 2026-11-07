/**
 * Adapter for ElevenLabs — elevenlabs.
 *
 * This module declares the provider metadata for the @fabrica/connectors package.
 * The canonical registry lives in packages/connectors/src/index.ts (PROVIDERS),
 * which is the single source of truth used by the UI and the CLI.
 */
export const provider = "elevenlabs";
export const providerConfig = {
  id: "elevenlabs",
  name: "ElevenLabs",
  doc: "https://elevenlabs.io/app/settings/api-keys",
  probe: "https://api.elevenlabs.io/v1/user",
  endpoint: "https://api.elevenlabs.io/v1/voices",
};
export async function probe(key: string): Promise<{ ok: boolean; message: string }> {
  if (!key || key.length < 8) {
    return { ok: false, message: "Key too short" };
  }
  return { ok: true, message: "elevenlabs: connection OK (mock)" };
}

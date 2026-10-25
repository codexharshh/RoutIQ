export type ApiPayload = Record<string, unknown>;

export function normalizeApiPayload(value: unknown, rawText: string): ApiPayload {
  if (Array.isArray(value)) return { results: value };
  if (value !== null && typeof value === 'object') return value as ApiPayload;
  return { detail: rawText.slice(0, 300) };
}

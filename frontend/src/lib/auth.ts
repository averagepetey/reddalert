const API_KEY_STORAGE_KEY = "reddalert_api_key";

export function getApiKey(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(API_KEY_STORAGE_KEY);
}

export function setApiKey(key: string): void {
  localStorage.setItem(API_KEY_STORAGE_KEY, key);
}

export function clearApiKey(): void {
  localStorage.removeItem(API_KEY_STORAGE_KEY);
}

export function getAuthHeaders(): Record<string, string> {
  const key = getApiKey();
  if (!key) return {};
  return { "X-API-Key": key };
}

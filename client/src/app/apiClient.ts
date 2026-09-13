const ACCESS_KEY_STORAGE = 'assistant-access-key';

let onAccessDenied: (() => void) | null = null;

export function setAccessDeniedHandler(handler: () => void) {
  onAccessDenied = handler;
}

export function getStoredAccessKey(): string | null {
  try {
    return localStorage.getItem(ACCESS_KEY_STORAGE);
  } catch {
    return null;
  }
}

export function storeAccessKey(key: string) {
  try {
    localStorage.setItem(ACCESS_KEY_STORAGE, key);
  } catch {
    // ignore (e.g. private browsing)
  }
}

export function clearAccessKey() {
  try {
    localStorage.removeItem(ACCESS_KEY_STORAGE);
  } catch {
    // ignore
  }
}

export async function apiFetch(url: string, options: RequestInit = {}): Promise<Response> {
  const key = getStoredAccessKey();
  const headers = new Headers(options.headers);
  if (key) headers.set('X-Access-Key', key);

  const response = await fetch(url, { ...options, headers });

  if (response.status === 401) {
    clearAccessKey();
    onAccessDenied?.();
  }

  return response;
}

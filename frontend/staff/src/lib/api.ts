const BASE = '/api';

// Declares this app's surface on every request — see the matching comment
// in frontend/student/src/lib/api.ts. "staff" does not grant anything by
// itself; the backend still resolves the caller's real course role first
// and only ever clamps toward STUDENT, never the reverse.
const APP_SURFACE = 'staff';

async function apiFetch<T>(path: string, opts: RequestInit = {}): Promise<T> {
  const token = localStorage.getItem('token');
  const res = await fetch(`${BASE}${path}`, {
    ...opts,
    headers: {
      'Content-Type': 'application/json',
      'X-App-Surface': APP_SURFACE,
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...((opts.headers as Record<string, string>) ?? {}),
    },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { message?: string }).message ?? `HTTP ${res.status}`);
  }
  const text = await res.text();
  return text ? (JSON.parse(text) as T) : ({} as T);
}

/** Multipart requests leave Content-Type to the browser, which adds the boundary. */
async function sendForm<T>(method: 'POST' | 'PUT', path: string, form: FormData): Promise<T> {
  const token = localStorage.getItem('token');
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: {
      'X-App-Surface': APP_SURFACE,
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: form,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { message?: string }).message ?? `HTTP ${res.status}`);
  }
  const text = await res.text();
  return (text ? JSON.parse(text) : {}) as T;
}

export const api = {
  get: <T>(path: string) => apiFetch<T>(path),
  post: <T>(path: string, body?: unknown) =>
    apiFetch<T>(path, {
      method: 'POST',
      body: body !== undefined ? JSON.stringify(body) : undefined,
    }),
  put: <T>(path: string, body?: unknown) =>
    apiFetch<T>(path, {
      method: 'PUT',
      body: body !== undefined ? JSON.stringify(body) : undefined,
    }),
  patch: <T>(path: string, body?: unknown) =>
    apiFetch<T>(path, {
      method: 'PATCH',
      body: body !== undefined ? JSON.stringify(body) : undefined,
    }),
  delete: <T>(path: string) => apiFetch<T>(path, { method: 'DELETE' }),
  /** POST multipart/form-data (file uploads), as in frontend/admin/src/lib/api.ts. */
  postForm: <T>(path: string, form: FormData) => sendForm<T>('POST', path, form),
  /** PUT multipart/form-data: replace a resource's uploaded files. */
  putForm: <T>(path: string, form: FormData) => sendForm<T>('PUT', path, form),
  /** GET a file (e.g. an uploaded course resource) as a Blob, with the same auth headers. */
  getBlob: async (path: string): Promise<Blob> => {
    const token = localStorage.getItem('token');
    const res = await fetch(`${BASE}${path}`, {
      headers: {
        'X-App-Surface': APP_SURFACE,
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error((err as { message?: string }).message ?? `HTTP ${res.status}`);
    }
    return res.blob();
  },
};


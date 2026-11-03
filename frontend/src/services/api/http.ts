// Fetch wrapper: attaches the JWT, unwraps the { success, data|error, requestId }
// envelope and converts failures into typed ApiError instances. A 401 clears the
// session and redirects to the login page.

const TOKEN_KEY = 'klc.token';
const USER_KEY = 'klc.user';

let inMemoryToken: string | null = null;

export const tokenStore = {
  get(): string | null {
    if (inMemoryToken) return inMemoryToken;
    try {
      inMemoryToken = sessionStorage.getItem(TOKEN_KEY);
    } catch {
      /* sessionStorage unavailable */
    }
    return inMemoryToken;
  },
  set(token: string): void {
    inMemoryToken = token;
    try {
      sessionStorage.setItem(TOKEN_KEY, token);
    } catch {
      /* ignore */
    }
  },
  clear(): void {
    inMemoryToken = null;
    try {
      sessionStorage.removeItem(TOKEN_KEY);
      sessionStorage.removeItem(USER_KEY);
    } catch {
      /* ignore */
    }
  },
};

export const userStore = {
  get<T>(): T | null {
    try {
      const raw = sessionStorage.getItem(USER_KEY);
      return raw ? (JSON.parse(raw) as T) : null;
    } catch {
      return null;
    }
  },
  set(user: unknown): void {
    try {
      sessionStorage.setItem(USER_KEY, JSON.stringify(user));
    } catch {
      /* ignore */
    }
  },
};

/**
 * Body of a 202 from a governed mutation: the maker's change was queued for a
 * checker instead of being applied. The http layer unwraps `data` as usual, so
 * a call site receives this object where it would normally get the entity.
 */
export interface PendingApproval {
  pendingApproval: true;
  changeRequestId: number;
  message: string;
}

/** Narrows a mutation response to the "queued for approval" shape. */
export function isPendingApproval(data: unknown): data is PendingApproval {
  return (
    typeof data === 'object' &&
    data !== null &&
    (data as { pendingApproval?: unknown }).pendingApproval === true
  );
}

export class ApiError extends Error {
  readonly code: string;
  readonly requestId: string | null;
  readonly status: number;

  constructor(code: string, message: string, status: number, requestId: string | null) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.status = status;
    this.requestId = requestId;
  }
}

interface Envelope<T> {
  success: boolean;
  data?: T;
  error?: { code: string; message: string };
  requestId?: string;
}

function onUnauthorized(): void {
  tokenStore.clear();
  if (!window.location.pathname.startsWith('/login')) {
    const next = encodeURIComponent(window.location.pathname + window.location.search);
    window.location.assign(`/login?next=${next}`);
  }
}

export function buildQuery(params?: Record<string, string | number | boolean | undefined>): string {
  if (!params) return '';
  const sp = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue;
    sp.set(key, String(value));
  }
  const s = sp.toString();
  return s ? `?${s}` : '';
}

interface RequestOptions {
  /**
   * Public endpoint: send no Authorization header and never redirect to the
   * login page. The requester filling in a licence form is not a user of this
   * console, so a 401/403 there is an error to display, not a session problem.
   */
  anonymous?: boolean;
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  opts?: RequestOptions,
): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' };
  const token = opts?.anonymous === true ? null : tokenStore.get();
  if (token) headers['Authorization'] = `Bearer ${token}`;
  if (body !== undefined) headers['Content-Type'] = 'application/json';

  let res: Response;
  try {
    res = await fetch(`/api/v1${path}`, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError('NETWORK_ERROR', 'Cannot reach the server. Check your connection.', 0, null);
  }

  const requestId = res.headers.get('X-Request-Id');

  let envelope: Envelope<T> | null = null;
  try {
    envelope = (await res.json()) as Envelope<T>;
  } catch {
    /* non-JSON body */
  }

  if (res.status === 401 && opts?.anonymous !== true && !path.startsWith('/auth/login')) {
    onUnauthorized();
    throw new ApiError(
      envelope?.error?.code ?? 'UNAUTHORIZED',
      envelope?.error?.message ?? 'Session expired. Please sign in again.',
      401,
      envelope?.requestId ?? requestId,
    );
  }

  if (!res.ok || !envelope || envelope.success !== true) {
    throw new ApiError(
      envelope?.error?.code ?? (res.ok ? 'INTERNAL_ERROR' : `HTTP_${res.status}`),
      envelope?.error?.message ?? `Request failed with status ${res.status}.`,
      res.status,
      envelope?.requestId ?? requestId,
    );
  }

  return envelope.data as T;
}

export const http = {
  get: <T>(path: string, params?: Record<string, string | number | boolean | undefined>) =>
    request<T>('GET', `${path}${buildQuery(params)}`),
  post: <T>(path: string, body?: unknown) => request<T>('POST', path, body),
  put: <T>(path: string, body?: unknown) => request<T>('PUT', path, body),
  delete: <T>(path: string) => request<T>('DELETE', path),
};

/**
 * Bare call for the unauthenticated `/api/v1/public` endpoints: no token is
 * attached and a 401 does not bounce the caller to /login. Everything else —
 * envelope unwrapping, ApiError, request-id capture — is shared with `http`.
 */
export function publicRequest<T>(method: string, path: string, body?: unknown): Promise<T> {
  return request<T>(method, path, body, { anonymous: true });
}

export const publicHttp = {
  get: <T>(path: string) => publicRequest<T>('GET', path),
  post: <T>(path: string, body?: unknown) => publicRequest<T>('POST', path, body),
};

/**
 * Downloads an authenticated file response (e.g. a signed .lic) and hands it to
 * the browser as a save. A plain <a href> cannot carry the bearer token, so the
 * file is fetched here and saved from a Blob. The filename comes from the
 * server's Content-Disposition, so the portal never has to guess it.
 */
export async function downloadFile(path: string, fallbackName: string): Promise<void> {
  const token = tokenStore.get();
  const res = await fetch(`/api/v1${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) {
    let message = `Download failed with status ${res.status}.`;
    try {
      const env = (await res.json()) as { error?: { message?: string } };
      if (env.error?.message) message = env.error.message;
    } catch {
      /* not JSON */
    }
    throw new ApiError(`HTTP_${res.status}`, message, res.status, res.headers.get('X-Request-Id'));
  }
  const cd = res.headers.get('Content-Disposition') ?? '';
  const name = /filename="([^"]+)"/.exec(cd)?.[1] ?? fallbackName;
  saveText(await res.text(), name);
}

/** Saves text the browser already holds (a file just returned by the API). */
export function saveText(text: string, name: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/plain;charset=utf-8' }));
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

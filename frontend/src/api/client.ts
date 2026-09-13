// Thin typed client for the MANAK MARG FastAPI backend (served under /api).

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

type Params = Record<string, string | number | boolean | null | undefined>;

// Empty by default: the SPA is served by the API itself. Set VITE_API_BASE_URL at build time only when the
// frontend is hosted separately (the API must then list the frontend origin in MANAKMARG_CORS_ORIGINS).
const API_BASE = ((import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "").replace(/\/+$/, "");

function withParams(path: string, params?: Params): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  }
  const query = search.toString();
  return `${API_BASE}/api${path}${query ? `?${query}` : ""}`;
}

async function parse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let message = response.statusText;
    try {
      const body = await response.json();
      message = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      /* not JSON */
    }
    throw new ApiError(response.status, message);
  }
  return (await response.json()) as T;
}

export const api = {
  get: async <T>(path: string, params?: Params, signal?: AbortSignal) =>
    parse<T>(await fetch(withParams(path, params), { signal })),
  post: async <T>(path: string, body: unknown, signal?: AbortSignal) =>
    parse<T>(
      await fetch(withParams(path), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal,
      }),
    ),
  upload: async <T>(path: string, form: FormData) => parse<T>(await fetch(withParams(path), { method: "POST", body: form })),
  delete: async <T>(path: string) => parse<T>(await fetch(withParams(path), { method: "DELETE" })),
  url: withParams,
};

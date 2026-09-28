// A small client for the Synapse API.
//
// The session lives in an HttpOnly cookie the page cannot read. What the page does hold is
// the CSRF token, kept in memory only (never in localStorage, where a script injection could
// read it), and sent on every state-changing request (ADR 0006).

const CLIENT_HEADER = "X-Synapse-Client";
const CSRF_HEADER = "X-Synapse-CSRF";

let csrfToken: string | null = null;

export function rememberCsrfToken(token: string | null): void {
  csrfToken = token;
}

/** An error response from the API, carrying the stable error code from its body. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly retryAfterSeconds: number | null;

  constructor(status: number, code: string, retryAfterSeconds: number | null) {
    super(`${String(status)} ${code}`);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

/** The request never reached the API (offline, server down, blocked). */
export class NetworkError extends Error {
  constructor(cause: unknown) {
    super("network error", { cause });
    this.name = "NetworkError";
  }
}

type Method = "GET" | "POST" | "PATCH" | "DELETE";

export async function apiRequest<T>(method: Method, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { [CLIENT_HEADER]: "web" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET" && csrfToken !== null) headers[CSRF_HEADER] = csrfToken;

  let response: Response;
  try {
    response = await fetch(path, {
      method,
      headers,
      credentials: "same-origin",
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
  } catch (error) {
    throw new NetworkError(error);
  }

  if (!response.ok) {
    throw new ApiError(response.status, await errorCode(response), retryAfter(response));
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

async function errorCode(response: Response): Promise<string> {
  try {
    const parsed: unknown = await response.json();
    if (typeof parsed === "object" && parsed !== null && "error" in parsed) {
      if (typeof parsed.error === "string") return parsed.error;
    }
  } catch {
    // Not JSON, for example an error page from a proxy in front of the API.
  }
  return "unexpected";
}

function retryAfter(response: Response): number | null {
  const value = Number(response.headers.get("Retry-After"));
  return Number.isFinite(value) && value > 0 ? value : null;
}

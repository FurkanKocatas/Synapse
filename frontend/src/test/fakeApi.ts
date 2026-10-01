// A scripted stand-in for the backend, so UI tests exercise real fetch calls.

import { vi } from "vitest";

export interface Call {
  method: string;
  path: string;
  headers: Record<string, string>;
  body: unknown;
  // The body as sent, for uploads that are not JSON.
  raw: unknown;
}

// ``text`` is sent as it is (server-sent events, for example); ``body`` as JSON.
type Handler = (call: Call) => {
  status: number;
  body?: unknown;
  text?: string;
  headers?: Record<string, string>;
};

export function fakeApi(handler: Handler) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((path: string, init: RequestInit = {}) => {
      const call: Call = {
        method: init.method ?? "GET",
        path,
        headers: (init.headers ?? {}) as Record<string, string>,
        body: typeof init.body === "string" ? JSON.parse(init.body) : undefined,
        raw: init.body,
      };
      calls.push(call);
      const { status, body, text, headers } = handler(call);
      const content = text ?? (body === undefined ? null : JSON.stringify(body));
      return Promise.resolve(
        new Response(content, {
          status,
          headers: { "Content-Type": "application/json", ...headers },
        }),
      );
    }),
  );
  return calls;
}

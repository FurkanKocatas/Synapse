// The current session as shared server state, and where each session level belongs.

import { queryOptions } from "@tanstack/react-query";

import { ApiError } from "@/lib/api";

import { fetchSession, type Session } from "./authApi";

export const sessionQuery = queryOptions({
  queryKey: ["session"],
  queryFn: async (): Promise<Session | null> => {
    try {
      return await fetchSession();
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) return null;
      throw error;
    }
  },
  staleTime: 30_000,
});

export type Place = "/login" | "/mfa" | "/enroll" | "/";

/** The page a session of this level must be on. */
export function placeFor(session: Session | null): Place {
  if (session === null) return "/login";
  switch (session.auth_level) {
    case "pending_mfa":
      return "/mfa";
    case "enroll_mfa":
      return "/enroll";
    case "full":
      return "/";
  }
}

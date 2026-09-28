// Typed calls for /api/account (see docs/design/identity.md).

import { apiRequest } from "@/lib/api";
import type { Locale } from "@/paraglide/runtime.js";

export interface SessionInfo {
  id: string;
  created_at: string;
  last_seen_at: string;
  client_ip: string | null;
  user_agent: string | null;
  current: boolean;
}

export const accountApi = {
  changePassword: (current: string, next: string) =>
    apiRequest<undefined>("POST", "/api/account/password", {
      current_password: current,
      new_password: next,
    }),
  sessions: () => apiRequest<SessionInfo[]>("GET", "/api/account/sessions"),
  endSession: (id: string) => apiRequest<undefined>("DELETE", `/api/account/sessions/${id}`),
  setLocale: (locale: Locale) =>
    apiRequest<undefined>("PUT", "/api/account/preferences", { locale }),
};

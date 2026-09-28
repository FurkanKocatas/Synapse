// Typed calls for /api/auth (see docs/design/identity.md).

import { apiRequest, rememberCsrfToken } from "@/lib/api";

export type AuthLevel = "pending_mfa" | "enroll_mfa" | "full";

export interface User {
  id: string;
  email: string;
  display_name: string;
  role: "admin" | "editor" | "member" | "auditor";
  locale: string;
}

export interface Session {
  auth_level: AuthLevel;
  csrf_token: string;
  user: User | null;
}

export interface Enrollment {
  secret: string;
  provisioning_uri: string;
}

export interface EnrollmentConfirmed extends Session {
  recovery_codes: string[];
}

function remember<T extends { csrf_token: string }>(response: T): T {
  rememberCsrfToken(response.csrf_token);
  return response;
}

export async function fetchSession(): Promise<Session> {
  return remember(await apiRequest<Session>("GET", "/api/auth/session"));
}

export async function login(email: string, password: string): Promise<Session> {
  return remember(await apiRequest<Session>("POST", "/api/auth/login", { email, password }));
}

export async function verifySecondFactor(code: string): Promise<Session> {
  return remember(await apiRequest<Session>("POST", "/api/auth/mfa/verify", { code }));
}

export async function startTotpEnrollment(): Promise<Enrollment> {
  return apiRequest<Enrollment>("POST", "/api/auth/mfa/totp/enroll");
}

export async function confirmTotpEnrollment(code: string): Promise<EnrollmentConfirmed> {
  return remember(
    await apiRequest<EnrollmentConfirmed>("POST", "/api/auth/mfa/totp/confirm", { code }),
  );
}

export async function logout(): Promise<void> {
  await apiRequest<undefined>("POST", "/api/auth/logout");
  rememberCsrfToken(null);
}

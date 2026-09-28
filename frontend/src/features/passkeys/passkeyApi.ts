// Passkey ceremonies: the server's options go to the browser's WebAuthn API and its answer goes
// back unchanged (see docs/design/identity.md).

import {
  browserSupportsWebAuthn,
  startAuthentication,
  startRegistration,
  type PublicKeyCredentialCreationOptionsJSON,
  type PublicKeyCredentialRequestOptionsJSON,
} from "@simplewebauthn/browser";

import type { Session } from "@/features/auth/authApi";
import { apiRequest, rememberCsrfToken } from "@/lib/api";

export interface Passkey {
  id: string;
  name: string;
  synced: boolean;
  created_at: string;
  last_used_at: string | null;
}

export interface Registered {
  id: string;
  recovery_codes: string[] | null;
  session: Session | null;
}

export function supportsPasskeys(): boolean {
  return browserSupportsWebAuthn();
}

/** Creates a passkey on this device and registers it; may also complete enrollment. */
export async function registerPasskey(name: string): Promise<Registered> {
  const optionsJSON = await apiRequest<PublicKeyCredentialCreationOptionsJSON>(
    "POST",
    "/api/auth/passkeys/registration-options",
  );
  const credential = await startRegistration({ optionsJSON });
  const registered = await apiRequest<Registered>("POST", "/api/auth/passkeys", {
    credential,
    name,
  });
  if (registered.session !== null) rememberCsrfToken(registered.session.csrf_token);
  return registered;
}

/** Completes a pending sign-in with a passkey. */
export async function signInWithPasskey(): Promise<Session> {
  const optionsJSON = await apiRequest<PublicKeyCredentialRequestOptionsJSON>(
    "POST",
    "/api/auth/mfa/passkey/options",
  );
  const credential = await startAuthentication({ optionsJSON });
  const session = await apiRequest<Session>("POST", "/api/auth/mfa/passkey", { credential });
  rememberCsrfToken(session.csrf_token);
  return session;
}

export const passkeyApi = {
  list: () => apiRequest<Passkey[]>("GET", "/api/account/passkeys"),
  remove: (id: string) => apiRequest<undefined>("DELETE", `/api/account/passkeys/${id}`),
};

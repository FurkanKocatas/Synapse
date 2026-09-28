// Routes and the guard that keeps every session level on its own page.

import { QueryClient } from "@tanstack/react-query";
import {
  createRootRouteWithContext,
  createRoute,
  createRouter,
  Outlet,
  redirect,
} from "@tanstack/react-router";

import { EnrollPage } from "@/features/auth/EnrollPage";
import { LoginPage } from "@/features/auth/LoginPage";
import { MfaPage } from "@/features/auth/MfaPage";
import { placeFor, sessionQuery, type Place } from "@/features/auth/session";
import { HomePage } from "@/pages/HomePage";

interface RouterContext {
  queryClient: QueryClient;
}

const rootRoute = createRootRouteWithContext<RouterContext>()({ component: Outlet });

/** Sends the visitor to the page that matches their session, unless they are on it already. */
function guard(place: Place) {
  return async ({ context }: { context: RouterContext }) => {
    const session = await context.queryClient.query(sessionQuery);
    const target = placeFor(session);
    if (target !== place) {
      // eslint-disable-next-line @typescript-eslint/only-throw-error -- the router's redirect protocol
      throw redirect({ to: target });
    }
  };
}

const routes = [
  createRoute({
    getParentRoute: () => rootRoute,
    path: "/",
    beforeLoad: guard("/"),
    component: HomePage,
  }),
  createRoute({
    getParentRoute: () => rootRoute,
    path: "/login",
    beforeLoad: guard("/login"),
    component: LoginPage,
  }),
  createRoute({
    getParentRoute: () => rootRoute,
    path: "/mfa",
    beforeLoad: guard("/mfa"),
    component: MfaPage,
  }),
  createRoute({
    getParentRoute: () => rootRoute,
    path: "/enroll",
    beforeLoad: guard("/enroll"),
    component: EnrollPage,
  }),
];

export function createAppRouter(queryClient: QueryClient) {
  return createRouter({
    routeTree: rootRoute.addChildren(routes),
    context: { queryClient },
    defaultPreload: false,
  });
}

declare module "@tanstack/react-router" {
  interface Register {
    router: ReturnType<typeof createAppRouter>;
  }
}

// Routes and the guard that keeps every session level on its own page.

import { QueryClient } from "@tanstack/react-query";
import {
  createRootRouteWithContext,
  createRoute,
  createRouter,
  Outlet,
  redirect,
} from "@tanstack/react-router";

import { AccountPage } from "@/features/account/AccountPage";
import { adminAreas } from "@/features/admin/adminApi";
import { CollectionsPage } from "@/features/admin/CollectionsPage";
import { GroupsPage } from "@/features/admin/GroupsPage";
import { UsersPage } from "@/features/admin/UsersPage";
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

/** Like the "/" guard, and the role must also have this administration area. */
function adminGuard(area: keyof ReturnType<typeof adminAreas>) {
  return async ({ context }: { context: RouterContext }) => {
    await guard("/")({ context });
    const session = await context.queryClient.query(sessionQuery);
    if (!adminAreas(session?.user?.role)[area]) {
      // eslint-disable-next-line @typescript-eslint/only-throw-error -- the router's redirect protocol
      throw redirect({ to: "/" });
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
  createRoute({
    getParentRoute: () => rootRoute,
    path: "/account",
    beforeLoad: guard("/"),
    component: AccountPage,
  }),
  createRoute({
    getParentRoute: () => rootRoute,
    path: "/admin/users",
    beforeLoad: adminGuard("users"),
    component: UsersPage,
  }),
  createRoute({
    getParentRoute: () => rootRoute,
    path: "/admin/groups",
    beforeLoad: adminGuard("groups"),
    component: GroupsPage,
  }),
  createRoute({
    getParentRoute: () => rootRoute,
    path: "/admin/collections",
    beforeLoad: adminGuard("collections"),
    component: CollectionsPage,
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

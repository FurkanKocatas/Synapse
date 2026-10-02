// Routes and the guard that keeps every session level on its own page.

import { QueryClient } from "@tanstack/react-query";
import {
  createRootRouteWithContext,
  createRoute,
  createRouter,
  Outlet,
  redirect,
} from "@tanstack/react-router";

import { AppLayout } from "@/components/AppShell";
import { AccountPage } from "@/features/account/AccountPage";
import { adminAreas } from "@/features/admin/adminApi";
import { CollectionsPage } from "@/features/admin/CollectionsPage";
import { GroupsPage } from "@/features/admin/GroupsPage";
import { UsersPage } from "@/features/admin/UsersPage";
import { EnrollPage } from "@/features/auth/EnrollPage";
import { LoginPage } from "@/features/auth/LoginPage";
import { MfaPage } from "@/features/auth/MfaPage";
import { placeFor, sessionQuery, type Place } from "@/features/auth/session";
import { ChatPage } from "@/features/chat/ChatPage";
import { LibraryPage } from "@/features/library/LibraryPage";

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

/** The signed-in pages' guard is on their layout; the role must also have this area. */
function adminGuard(area: keyof ReturnType<typeof adminAreas>) {
  return async ({ context }: { context: RouterContext }) => {
    const session = await context.queryClient.query(sessionQuery);
    if (!adminAreas(session?.user?.role)[area]) {
      // eslint-disable-next-line @typescript-eslint/only-throw-error -- the router's redirect protocol
      throw redirect({ to: "/" });
    }
  };
}

// The signed-in pages share one layout, so the navigation (and the conversation list in it)
// stays put while the page beside it changes.
const appRoute = createRoute({
  getParentRoute: () => rootRoute,
  id: "app",
  beforeLoad: guard("/"),
  component: AppLayout,
});

const signedIn = [
  createRoute({
    getParentRoute: () => appRoute,
    path: "/",
    // ?c=<id> opens a conversation; a search change keeps the page, and an answer streaming.
    validateSearch: (search: Record<string, unknown>): { c?: string } =>
      typeof search.c === "string" ? { c: search.c } : {},
    component: ChatPage,
  }),
  createRoute({ getParentRoute: () => appRoute, path: "/library", component: LibraryPage }),
  createRoute({ getParentRoute: () => appRoute, path: "/account", component: AccountPage }),
  createRoute({
    getParentRoute: () => appRoute,
    path: "/admin/users",
    beforeLoad: adminGuard("users"),
    component: UsersPage,
  }),
  createRoute({
    getParentRoute: () => appRoute,
    path: "/admin/groups",
    beforeLoad: adminGuard("groups"),
    component: GroupsPage,
  }),
  createRoute({
    getParentRoute: () => appRoute,
    path: "/admin/collections",
    beforeLoad: adminGuard("collections"),
    component: CollectionsPage,
  }),
];

const signIn = [
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
    routeTree: rootRoute.addChildren([appRoute.addChildren(signedIn), ...signIn]),
    context: { queryClient },
    defaultPreload: false,
  });
}

declare module "@tanstack/react-router" {
  interface Register {
    router: ReturnType<typeof createAppRouter>;
  }
  interface HistoryState {
    // Set by "New conversation", so the chat page starts over even when it is already open.
    fresh?: number;
  }
}

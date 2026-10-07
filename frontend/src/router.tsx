// Routes and the guard that keeps every session level on its own page.

import { QueryClient } from "@tanstack/react-query";
import {
  createRootRouteWithContext,
  createRoute,
  createRouter,
  lazyRouteComponent,
  Outlet,
  redirect,
} from "@tanstack/react-router";

import { AppLayout } from "@/components/AppShell";
import { adminAreas, hasAdministration } from "@/features/admin/adminApi";
import { LoginPage } from "@/features/auth/LoginPage";
import { placeFor, sessionQuery, type Place } from "@/features/auth/session";
import { ChatPage, ClassicChatPage } from "@/features/chat/ChatPage";

interface RouterContext {
  queryClient: QueryClient;
}

const rootRoute = createRootRouteWithContext<RouterContext>()({ component: Outlet });

// Signing in and the chat load with the app; every other page loads when first opened, so the
// first screen does not wait for administration code most users never see.

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

/** The signed-in pages' guard is on their layout; the role must also have this area (or,
 * for the panel's overview, any area). */
function adminGuard(area: keyof ReturnType<typeof adminAreas> | "any") {
  return async ({ context }: { context: RouterContext }) => {
    const session = await context.queryClient.query(sessionQuery);
    const role = session?.user?.role;
    if (!(area === "any" ? hasAdministration(role) : adminAreas(role)[area])) {
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
  createRoute({
    getParentRoute: () => appRoute,
    path: "/chat",
    // The classic chat, where the installation offers it.
    beforeLoad: async ({ context }) => {
      const session = await context.queryClient.query(sessionQuery);
      if (session?.features?.classic_chat !== true) {
        // eslint-disable-next-line @typescript-eslint/only-throw-error -- the router's redirect protocol
        throw redirect({ to: "/" });
      }
    },
    validateSearch: (search: Record<string, unknown>): { c?: string } =>
      typeof search.c === "string" ? { c: search.c } : {},
    component: ClassicChatPage,
  }),
  createRoute({
    getParentRoute: () => appRoute,
    path: "/library",
    component: lazyRouteComponent(() => import("@/features/library/LibraryPage"), "LibraryPage"),
  }),
  createRoute({
    getParentRoute: () => appRoute,
    path: "/account",
    component: lazyRouteComponent(() => import("@/features/account/AccountPage"), "AccountPage"),
  }),
  createRoute({
    getParentRoute: () => appRoute,
    path: "/admin",
    beforeLoad: adminGuard("any"),
    component: lazyRouteComponent(() => import("@/features/admin/AdminOverview"), "AdminOverview"),
  }),
  createRoute({
    getParentRoute: () => appRoute,
    path: "/admin/users",
    beforeLoad: adminGuard("users"),
    component: lazyRouteComponent(() => import("@/features/admin/UsersPage"), "UsersPage"),
  }),
  createRoute({
    getParentRoute: () => appRoute,
    path: "/admin/groups",
    beforeLoad: adminGuard("groups"),
    component: lazyRouteComponent(() => import("@/features/admin/GroupsPage"), "GroupsPage"),
  }),
  createRoute({
    getParentRoute: () => appRoute,
    path: "/admin/collections",
    beforeLoad: adminGuard("collections"),
    component: lazyRouteComponent(
      () => import("@/features/admin/CollectionsPage"),
      "CollectionsPage",
    ),
  }),
  createRoute({
    getParentRoute: () => appRoute,
    path: "/admin/system",
    beforeLoad: adminGuard("operations"),
    component: lazyRouteComponent(() => import("@/features/admin/SystemPage"), "SystemPage"),
  }),
  createRoute({
    getParentRoute: () => appRoute,
    path: "/admin/settings",
    beforeLoad: adminGuard("settings"),
    component: lazyRouteComponent(() => import("@/features/admin/SettingsPage"), "SettingsPage"),
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
    component: lazyRouteComponent(() => import("@/features/auth/MfaPage"), "MfaPage"),
  }),
  createRoute({
    getParentRoute: () => rootRoute,
    path: "/enroll",
    beforeLoad: guard("/enroll"),
    component: lazyRouteComponent(() => import("@/features/auth/EnrollPage"), "EnrollPage"),
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

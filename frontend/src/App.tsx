import { QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { useState } from "react";

import { sessionQuery } from "./features/auth/session";
import { ApiError } from "./lib/api";
import { createAppRouter } from "./router";

const RETRIES = 3;

/** The query client and the router, made together: a query that finds the session gone sends
 * the page to the sign-in form instead of asking again and again. */
function createApp() {
  let router: ReturnType<typeof createAppRouter> | null = null;
  const queryClient = new QueryClient({
    queryCache: new QueryCache({
      onError: (error, query) => {
        const expired = error instanceof ApiError && error.status === 401;
        if (!expired || query.queryKey[0] === sessionQuery.queryKey[0]) return;
        queryClient.setQueryData(sessionQuery.queryKey, null);
        void router?.navigate({ to: "/login" });
      },
    }),
    defaultOptions: {
      queries: {
        // A refusal (4xx) will not change by asking again; a network or server failure may.
        retry: (count, error) =>
          !(error instanceof ApiError && error.status < 500) && count < RETRIES,
      },
    },
  });
  router = createAppRouter(queryClient);
  return { queryClient, router };
}

export function App() {
  // Created once per app instance, so tests can mount isolated apps.
  const [{ queryClient, router }] = useState(createApp);
  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  );
}

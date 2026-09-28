import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { errorMessage } from "@/features/auth/errors";

/**
 * Runs a change through the API, shows its failure as a sentence, and refreshes the lists it
 * affects. One instance per form or page keeps a single, announced error line.
 */
export function useAction() {
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(action: () => Promise<unknown>, refresh: string[][]): Promise<boolean> {
    setBusy(true);
    setError(null);
    try {
      await action();
      await Promise.all(refresh.map((queryKey) => queryClient.invalidateQueries({ queryKey })));
      return true;
    } catch (failure) {
      setError(errorMessage(failure));
      return false;
    } finally {
      setBusy(false);
    }
  }

  return { run, error, busy };
}

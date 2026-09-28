import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { FormError } from "@/components/AuthLayout";
import { Button, buttonVariants } from "@/components/ui/button";
import { useAction } from "@/lib/useAction";
import { m } from "@/paraglide/messages.js";
import { getLocale } from "@/paraglide/runtime.js";

import { failureText, formatSize, statusLabel } from "./labels";
import {
  IN_PROGRESS,
  libraryApi,
  type LibraryCollection,
  type LibraryDocument,
} from "./libraryApi";

const REFRESH_MS = 3000;

export function DocumentTable({ collection }: { collection: LibraryCollection }) {
  const key = ["library", "documents", collection.id];
  const documents = useQuery({
    queryKey: key,
    queryFn: () => libraryApi.documents(collection.id),
    // Keep asking while something is being processed, then stop.
    refetchInterval: (query) =>
      query.state.data?.some((document) => IN_PROGRESS.has(document.status)) ? REFRESH_MS : false,
  });
  const { run, error, busy } = useAction();
  const [confirming, setConfirming] = useState<string | null>(null);
  const locale = getLocale();
  const dates = new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" });

  if (documents.data === undefined) {
    return <p className="text-sm text-muted-foreground">{m.common_loading()}</p>;
  }
  if (documents.data.length === 0) {
    return <p className="text-sm text-muted-foreground">{m.library_empty()}</p>;
  }

  function remove(document: LibraryDocument) {
    setConfirming(null);
    void run(() => libraryApi.remove(document.id), [key]);
  }

  return (
    <div className="flex flex-col gap-2">
      <FormError message={error} />
      <div className="overflow-x-auto rounded-lg border">
        <table className="w-full text-sm">
          <thead className="bg-muted/50 text-left">
            <tr>
              <th className="p-2">{m.library_col_title()}</th>
              <th className="p-2">{m.library_col_status()}</th>
              <th className="p-2">{m.library_col_size()}</th>
              <th className="p-2">{m.library_col_updated()}</th>
              <th className="p-2">
                <span className="sr-only">{m.admin_field_actions()}</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {documents.data.map((document) => (
              <tr key={document.id} className="border-t">
                <td className="p-2">{document.title}</td>
                <td className="p-2">
                  {statusLabel[document.status]()}
                  {document.status === "failed" && (
                    <span className="block text-xs text-destructive">
                      {failureText(document.failure)}
                    </span>
                  )}
                </td>
                <td className="p-2 tabular-nums">{formatSize(document.size_bytes, locale)}</td>
                <td className="p-2">{dates.format(new Date(document.updated_at))}</td>
                <td className="flex flex-wrap justify-end gap-2 p-2">
                  <a
                    className={buttonVariants({ variant: "outline", size: "sm" })}
                    href={libraryApi.fileUrl(document.id, document.latest_version)}
                    aria-label={`${m.library_download()}: ${document.title}`}
                  >
                    {m.library_download()}
                  </a>
                  {collection.can_write &&
                    (confirming === document.id ? (
                      <Button
                        variant="destructive"
                        size="sm"
                        disabled={busy}
                        onClick={() => {
                          remove(document);
                        }}
                      >
                        {m.library_delete_confirm()}
                      </Button>
                    ) : (
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={busy}
                        aria-label={`${m.library_delete()}: ${document.title}`}
                        onClick={() => {
                          setConfirming(document.id);
                        }}
                      >
                        {m.library_delete()}
                      </Button>
                    ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

import { useQueryClient } from "@tanstack/react-query";
import { useRef, useState, type DragEvent } from "react";

import { Button } from "@/components/ui/button";
import { errorMessage } from "@/features/auth/errors";
import { cn } from "@/lib/utils";
import { m } from "@/paraglide/messages.js";

import { libraryApi } from "./libraryApi";

interface Problem {
  name: string;
  reason: string;
}

/** Uploads one file at a time, so every failure is reported against its own file. */
export function UploadBox({ collectionId }: { collectionId: string }) {
  const queryClient = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [current, setCurrent] = useState<string | null>(null);
  const [problems, setProblems] = useState<Problem[]>([]);
  const [dragging, setDragging] = useState(false);

  async function send(files: FileList | File[]) {
    const found: Problem[] = [];
    for (const file of Array.from(files)) {
      setCurrent(file.name);
      try {
        await libraryApi.upload(collectionId, file);
      } catch (failure) {
        found.push({ name: file.name, reason: errorMessage(failure) });
      }
    }
    setCurrent(null);
    setProblems(found);
    await queryClient.invalidateQueries({ queryKey: ["library", "documents", collectionId] });
  }

  function drop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    if (current === null) void send(event.dataTransfer.files);
  }

  return (
    <div
      className={cn(
        "flex flex-col gap-2 rounded-lg border border-dashed p-4",
        dragging && "border-primary bg-muted/50",
      )}
      onDragOver={(event) => {
        event.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => {
        setDragging(false);
      }}
      onDrop={drop}
    >
      <div className="flex flex-wrap items-center gap-3">
        <Button type="button" disabled={current !== null} onClick={() => input.current?.click()}>
          {m.library_upload()}
        </Button>
        <span className="text-sm text-muted-foreground">{m.library_drop_hint()}</span>
        <input
          ref={input}
          type="file"
          multiple
          hidden
          aria-label={m.library_upload()}
          onChange={(event) => {
            if (event.target.files) void send(event.target.files);
            event.target.value = "";
          }}
        />
      </div>
      {current !== null && (
        <p role="status" className="text-sm">
          {m.library_uploading({ name: current })}
        </p>
      )}
      {problems.length > 0 && (
        <ul role="alert" className="text-sm text-destructive">
          {problems.map((problem) => (
            <li key={problem.name}>{m.library_upload_failed(problem)}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

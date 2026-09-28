import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { m } from "@/paraglide/messages.js";

interface RecoveryCodesProps {
  codes: string[];
  onContinue: () => void;
}

/** Shows the one-time recovery codes once, with copy and download. */
export function RecoveryCodes({ codes, onContinue }: RecoveryCodesProps) {
  const [copied, setCopied] = useState(false);

  // The codes are shown only once. Until the user confirms, leaving or reloading the page
  // asks for confirmation first, so they are not lost by accident.
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
    };
    window.addEventListener("beforeunload", warn);
    return () => {
      window.removeEventListener("beforeunload", warn);
    };
  }, []);
  const text = [m.auth_recovery_file_heading(), "", ...codes, ""].join("\n");

  async function copy() {
    await navigator.clipboard.writeText(codes.join("\n"));
    setCopied(true);
  }

  function download() {
    const url = URL.createObjectURL(new Blob([text], { type: "text/plain;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = "synapse-recovery-codes.txt";
    link.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-muted-foreground">{m.auth_recovery_description()}</p>
      {/* A code split across lines is easy to copy wrongly, so codes never wrap. */}
      <ul className="grid grid-cols-1 gap-1 rounded-md bg-muted p-3 font-mono text-sm min-[360px]:grid-cols-2 min-[360px]:gap-x-4">
        {codes.map((code) => (
          <li key={code} className="whitespace-nowrap">
            {code}
          </li>
        ))}
      </ul>
      <div className="flex gap-2">
        <Button type="button" variant="outline" onClick={() => void copy()}>
          {copied ? m.auth_recovery_copied() : m.auth_recovery_copy()}
        </Button>
        <Button type="button" variant="outline" onClick={download}>
          {m.auth_recovery_download()}
        </Button>
      </div>
      <Button type="button" onClick={onContinue}>
        {m.auth_recovery_continue()}
      </Button>
    </div>
  );
}

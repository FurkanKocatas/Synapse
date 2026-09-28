import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

interface CodeFieldProps {
  label: string;
  /** Recovery codes contain letters, so only pure TOTP fields get the numeric keyboard. */
  numericOnly: boolean;
}

/** A one-time code input that phones and password managers recognise. */
export function CodeField({ label, numericOnly }: CodeFieldProps) {
  return (
    <div className="flex flex-col gap-2">
      <Label htmlFor="code">{label}</Label>
      <Input
        id="code"
        name="code"
        autoComplete="one-time-code"
        inputMode={numericOnly ? "numeric" : "text"}
        maxLength={numericOnly ? 6 : 24}
        required
        autoFocus
      />
    </div>
  );
}

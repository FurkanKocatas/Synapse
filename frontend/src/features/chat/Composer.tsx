import { ArrowUpIcon, LockSimpleIcon, StopIcon } from "@phosphor-icons/react";
import { useEffect, useRef, useState } from "react";

import { Label } from "@/components/ui/label";
import { m } from "@/paraglide/messages.js";

const MAX_QUESTION = 1000;
const MAX_HEIGHT = 200;

/** The box to ask in. Enter sends, Shift and Enter makes a new line; while an answer is
 * being written the send button stops it. ``focusKey`` puts the cursor back when it changes. */
export function Composer({
  running,
  onAsk,
  onStop,
  focusKey,
}: {
  running: boolean;
  onAsk: (question: string) => void;
  onStop: () => void;
  focusKey?: unknown;
}) {
  const [question, setQuestion] = useState("");
  const box = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    // Not on touch screens, where focusing opens the keyboard over the page.
    const touch =
      typeof window.matchMedia === "function" && matchMedia("(pointer: coarse)").matches;
    if (!touch) box.current?.focus();
  }, [focusKey]);

  function grow() {
    const element = box.current;
    if (element === null) return;
    element.style.height = "auto";
    element.style.height = `${String(Math.min(element.scrollHeight, MAX_HEIGHT))}px`;
  }

  function submit(event: { preventDefault: () => void }) {
    event.preventDefault();
    const asked = question.trim();
    if (asked === "" || running) return;
    setQuestion("");
    if (box.current !== null) box.current.style.height = "auto";
    onAsk(asked);
  }

  return (
    <form onSubmit={submit} className="mx-auto w-full max-w-[44rem]">
      <div className="rounded-[20px] border border-input bg-card shadow-floating transition-[border-color,box-shadow,transform] duration-300 focus-within:-translate-y-0.5 focus-within:border-ring focus-within:ring-4 focus-within:ring-ring/15">
        <Label htmlFor="question" className="sr-only">
          {m.chat_question_label()}
        </Label>
        <textarea
          ref={box}
          id="question"
          value={question}
          maxLength={MAX_QUESTION}
          rows={1}
          placeholder={m.chat_placeholder()}
          onChange={(event) => {
            setQuestion(event.target.value);
            grow();
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
              submit(event);
            }
          }}
          className="block max-h-[200px] min-h-14 w-full resize-none bg-transparent px-5 pt-4 pb-1.5 text-base leading-normal outline-none placeholder:text-muted-foreground"
        />
        <div className="flex items-center gap-2 px-2 pb-2 pl-2.5">
          <span
            title={m.chat_scope_hint()}
            className="inline-flex h-7 min-w-0 items-center gap-1.5 rounded-lg px-1.5 text-xs text-subtle-foreground"
          >
            <LockSimpleIcon className="size-3.5 shrink-0" aria-hidden="true" />
            <span className="truncate">{m.chat_scope()}</span>
          </span>
          <span className="flex-1" />
          {running ? (
            <button
              type="button"
              aria-label={m.chat_stop()}
              title={m.chat_stop()}
              onClick={onStop}
              className="inline-flex size-9 animate-pulse items-center justify-center rounded-xl bg-foreground text-background transition-transform active:scale-95"
            >
              <StopIcon weight="fill" className="size-3.5" aria-hidden="true" />
            </button>
          ) : (
            <button
              type="submit"
              aria-label={m.chat_ask()}
              title={m.chat_ask()}
              disabled={question.trim() === ""}
              className="inline-flex size-9 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-raised transition-[background-color,opacity,transform] hover:-translate-y-px hover:bg-primary-hover active:scale-95 disabled:translate-y-0 disabled:opacity-35"
            >
              <ArrowUpIcon weight="bold" className="size-4" aria-hidden="true" />
            </button>
          )}
        </div>
      </div>
      <p className="mt-2 hidden text-center text-xs text-muted-foreground sm:block">
        {m.chat_hint()}
      </p>
    </form>
  );
}

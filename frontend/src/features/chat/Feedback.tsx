import { Menu } from "@base-ui/react/menu";
import {
  CircleDashedIcon,
  CopyIcon,
  FileXIcon,
  ThumbsDownIcon,
  ThumbsUpIcon,
  WarningIcon,
  type Icon,
} from "@phosphor-icons/react";
import { useState } from "react";

import { IconButton } from "@/components/ui/IconButton";
import { menuItem, menuLabel, menuPopup } from "@/components/ui/menu";
import { cn } from "@/lib/utils";
import { m } from "@/paraglide/messages.js";

import { chatApi, plainAnswer, type Feedback } from "./chatApi";

const PROBLEMS: [Feedback, () => string, Icon][] = [
  ["wrong_source", m.chat_feedback_wrong_source, FileXIcon],
  ["incomplete", m.chat_feedback_incomplete, CircleDashedIcon],
  ["invented", m.chat_feedback_invented, WarningIcon],
];

/** Under an answer: copy it, call it helpful, or say what is wrong with it. */
export function AnswerActions({
  text,
  initial,
  conversationId,
  ordinal,
}: {
  text: string;
  initial: Feedback | null;
  conversationId: string;
  ordinal: number;
}) {
  const [chosen, setChosen] = useState<Feedback | null>(initial);
  const [note, setNote] = useState<string | null>(null);
  const problem = chosen !== null && chosen !== "helpful";

  async function choose(kind: Feedback) {
    const next = chosen === kind ? null : kind;
    try {
      await chatApi.feedback(conversationId, ordinal, next);
      setChosen(next);
      setNote(next === null ? null : m.chat_feedback_saved());
    } catch {
      setNote(m.error_unexpected());
    }
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(plainAnswer(text));
      setNote(m.chat_copied());
    } catch {
      setNote(m.error_unexpected());
    }
  }

  return (
    <div role="group" aria-label={m.chat_feedback_label()} className="flex items-center gap-0.5">
      <IconButton label={m.chat_copy()} onClick={() => void copy()}>
        <CopyIcon aria-hidden="true" />
      </IconButton>
      <IconButton
        label={m.chat_feedback_helpful()}
        aria-pressed={chosen === "helpful"}
        onClick={() => void choose("helpful")}
      >
        <ThumbsUpIcon weight={chosen === "helpful" ? "fill" : "regular"} aria-hidden="true" />
      </IconButton>
      <Menu.Root>
        <Menu.Trigger
          aria-label={m.chat_feedback_problem()}
          title={m.chat_feedback_problem()}
          className={cn(
            "inline-flex size-8 items-center justify-center rounded-lg text-subtle-foreground transition-colors outline-none hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring data-[popup-open]:bg-accent [&_svg]:size-4",
            problem && "text-secondary-foreground",
          )}
        >
          <ThumbsDownIcon weight={problem ? "fill" : "regular"} aria-hidden="true" />
        </Menu.Trigger>
        <Menu.Portal>
          <Menu.Positioner align="start" sideOffset={4} className="z-50">
            <Menu.Popup className={menuPopup}>
              <p className={menuLabel}>{m.chat_feedback_problem_title()}</p>
              {PROBLEMS.map(([kind, label, IconFor]) => (
                <Menu.Item
                  key={kind}
                  className={cn(menuItem, chosen === kind && "font-medium")}
                  aria-checked={chosen === kind}
                  role="menuitemcheckbox"
                  onClick={() => void choose(kind)}
                >
                  <IconFor aria-hidden="true" weight={chosen === kind ? "fill" : "regular"} />
                  {label()}
                </Menu.Item>
              ))}
            </Menu.Popup>
          </Menu.Positioner>
        </Menu.Portal>
      </Menu.Root>
      {note !== null && (
        <span role="status" className="ml-1.5 animate-arrive text-xs text-muted-foreground">
          {note}
        </span>
      )}
    </div>
  );
}

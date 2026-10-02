import { HardDrivesIcon, LockKeyIcon, QuotesIcon } from "@phosphor-icons/react";
import type { ReactNode } from "react";

import { LanguageSwitch } from "@/components/LanguageSwitch";
import { LineField } from "@/components/LineField";
import { Wordmark } from "@/components/Logo";
import { ThemeSwitch } from "@/components/ThemeSwitch";
import { FileIcon } from "@/lib/fileKind";
import { m } from "@/paraglide/messages.js";

interface AuthLayoutProps {
  title: string;
  description?: string;
  children: ReactNode;
}

const POINTS = [
  { icon: QuotesIcon, text: m.auth_brand_point_cited },
  { icon: LockKeyIcon, text: m.auth_brand_point_access },
  { icon: HardDrivesIcon, text: m.auth_brand_point_local },
];

/** Every sign-in step: the step's form on one side, on wide screens a glimpse of what the
 * product does on the other. */
export function AuthLayout({ title, description, children }: AuthLayoutProps) {
  return (
    <div className="grid min-h-dvh bg-background lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
      <div className="flex min-h-dvh flex-col p-4 sm:p-6">
        <header className="flex items-center justify-between gap-2">
          <Wordmark />
          <div className="flex items-center gap-2">
            <LanguageSwitch />
            <ThemeSwitch />
          </div>
        </header>
        <main className="flex flex-1 items-center justify-center py-10">
          <div className="w-full max-w-sm animate-arrive">
            <h1 className="text-2xl font-medium tracking-tight">{title}</h1>
            {description === undefined ? null : (
              <p className="mt-1.5 text-sm text-subtle-foreground">{description}</p>
            )}
            <div className="mt-7">{children}</div>
          </div>
        </main>
        <p className="text-xs text-muted-foreground">{m.app_tagline()}</p>
      </div>
      <aside className="relative hidden overflow-hidden border-l bg-sidebar lg:flex lg:flex-col">
        <LineField className="absolute inset-0 size-full" />
        <div className="relative flex flex-1 items-center justify-center p-10">
          <Glimpse />
        </div>
        <ul className="relative flex flex-wrap gap-x-6 gap-y-2 px-10 pb-8 text-[13px] text-subtle-foreground">
          {POINTS.map(({ icon: IconFor, text }) => (
            <li key={text()} className="flex items-center gap-2">
              <IconFor className="size-4 shrink-0 text-secondary-foreground" aria-hidden="true" />
              {text()}
            </li>
          ))}
        </ul>
      </aside>
    </div>
  );
}

/** A still of an answer with its sources, the way the chat shows one. */
function Glimpse() {
  const sources = [
    { number: 1, title: m.auth_glimpse_source_1(), page: 9, file: "x.pdf" },
    { number: 2, title: m.auth_glimpse_source_2(), page: 3, file: "x.docx" },
  ];
  return (
    <div
      aria-hidden="true"
      className="w-full max-w-md animate-[float_9s_ease-in-out_infinite] rounded-2xl border bg-card p-5 shadow-floating"
    >
      <p className="text-base font-medium tracking-tight">{m.auth_glimpse_question()}</p>
      <div className="mt-3 flex gap-2">
        {sources.map((source) => (
          <div key={source.number} className="flex w-44 flex-col gap-1 rounded-xl border px-3 py-2">
            <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <FileIcon name={source.file} />
              {m.chat_page({ page: String(source.page) })}
              <span className="ml-auto rounded-[5px] bg-muted px-1 font-mono text-[11px]">
                {source.number}
              </span>
            </span>
            <span className="line-clamp-2 text-xs font-medium">{source.title}</span>
          </div>
        ))}
      </div>
      <p className="mt-3 text-[13.5px] leading-6">
        {m.auth_glimpse_answer_1()} <Chip number={1} /> {m.auth_glimpse_answer_2()}{" "}
        <Chip number={1} />
        <Chip number={2} />
      </p>
    </div>
  );
}

function Chip({ number }: { number: number }) {
  return (
    <span className="ml-[3px] inline-flex h-[18px] min-w-[18px] items-center justify-center rounded-[5px] bg-muted px-1 align-[2px] font-mono text-[11px] text-subtle-foreground">
      {number}
    </span>
  );
}

/** An error line that screen readers announce as soon as it appears. */
export function FormError({ message }: { message: string | null }) {
  if (message === null) return null;
  return (
    <p role="alert" className="text-sm text-destructive">
      {message}
    </p>
  );
}

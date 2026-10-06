import type { Icon } from "@phosphor-icons/react";
import type { ReactNode } from "react";

/** A settings card: its icon, title and what it is for, then its controls. */
export function SettingsCard({
  icon: IconFor,
  title,
  lead,
  children,
}: {
  icon: Icon;
  title: string;
  lead: string;
  children: ReactNode;
}) {
  return (
    <section className="animate-rise rounded-2xl border bg-card shadow-raised">
      <header className="flex gap-3 px-5 pt-5 pb-1">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-[10px] bg-secondary text-secondary-foreground">
          <IconFor weight="fill" className="size-5" aria-hidden="true" />
        </span>
        <div>
          <h3 className="text-base font-semibold">{title}</h3>
          <p className="mt-0.5 text-sm text-subtle-foreground">{lead}</p>
        </div>
      </header>
      <div className="px-5 pt-3 pb-5 sm:pl-[68px]">{children}</div>
    </section>
  );
}

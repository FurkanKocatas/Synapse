import { XIcon } from "@phosphor-icons/react";
import { Outlet } from "@tanstack/react-router";
import { AnimatePresence, LayoutGroup, motion } from "motion/react";
import { createContext, use, useEffect, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { Wordmark } from "@/components/Logo";
import { Sidebar } from "@/components/Sidebar";
import { TopBar } from "@/components/TopBar";
import { cn } from "@/lib/utils";
import { m } from "@/paraglide/messages.js";

// Where a page puts its title and actions: the left part of the top bar.
const Shell = createContext<{ titleSlot: HTMLElement | null }>({ titleSlot: null });

/** The frame of every signed-in page: a bar across the top (the page's title, the mark in the
 * middle, administration and the account on the right), the navigation on the left and the
 * page beside it. The frame stays mounted while pages change; on narrow screens the
 * navigation opens as a drawer. */
export function AppLayout() {
  const [open, setOpen] = useState(false);
  const [titleSlot, setTitleSlot] = useState<HTMLElement | null>(null);

  return (
    <Shell value={{ titleSlot }}>
      <div className="flex h-dvh flex-col overflow-hidden bg-background">
        <TopBar
          titleSlot={setTitleSlot}
          onOpenNavigation={() => {
            setOpen(true);
          }}
        />
        <div className="flex min-h-0 flex-1">
          <aside className="hidden w-64 shrink-0 flex-col border-r bg-sidebar md:flex">
            <LayoutGroup id="side">
              <Sidebar />
            </LayoutGroup>
          </aside>
          <AnimatePresence>
            {open && (
              <Drawer
                onClose={() => {
                  setOpen(false);
                }}
              />
            )}
          </AnimatePresence>
          <Outlet />
        </div>
      </div>
    </Shell>
  );
}

function Drawer({ onClose }: { onClose: () => void }) {
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-40 md:hidden">
      <motion.button
        type="button"
        aria-label={m.viewer_close()}
        className="absolute inset-0 bg-black/40"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        onClick={onClose}
      />
      <motion.aside
        className="absolute inset-y-0 left-0 flex w-72 max-w-[85vw] flex-col bg-sidebar shadow-floating"
        initial={{ x: "-100%" }}
        animate={{ x: 0 }}
        exit={{ x: "-100%" }}
        transition={{ type: "tween", ease: [0.32, 0.72, 0, 1], duration: 0.3 }}
      >
        <div className="flex h-13 shrink-0 items-center justify-between border-b px-4">
          <Wordmark />
          <button
            type="button"
            aria-label={m.viewer_close()}
            className="rounded-lg p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground"
            onClick={onClose}
          >
            <XIcon className="size-4" aria-hidden="true" />
          </button>
        </div>
        <LayoutGroup id="drawer">
          <Sidebar onNavigate={onClose} />
        </LayoutGroup>
      </motion.aside>
    </div>
  );
}

interface PageProps {
  title: string;
  // Before the title: where the page is (a collection's place in the library, for example).
  crumb?: ReactNode;
  // Page actions, after the title in the top bar.
  actions?: ReactNode;
  // At the top of the page: the tabs of a section with several pages (administration).
  subnav?: ReactNode;
  // A column beside the page, the full height under the top bar (the document viewer).
  panel?: ReactNode;
  // The page lays itself out (the chat): no scrolling, centred column of its own.
  wide?: boolean;
  children: ReactNode;
}

/** One signed-in page: its title and actions go to the top bar, its content below it, and an
 * optional panel beside it. */
export function Page({ title, crumb, actions, subnav, panel, wide = false, children }: PageProps) {
  const { titleSlot } = use(Shell);
  return (
    <>
      {titleSlot !== null &&
        createPortal(
          <>
            {crumb}
            <h1 className="min-w-0 truncate text-sm font-medium">{title}</h1>
            {actions !== undefined && (
              <div className="flex shrink-0 items-center gap-1.5">{actions}</div>
            )}
          </>,
          titleSlot,
        )}
      <div className="flex min-w-0 flex-1 flex-col">
        {subnav}
        {wide ? (
          <main className="flex min-h-0 flex-1 flex-col">{children}</main>
        ) : (
          <main className="min-h-0 flex-1 overflow-y-auto">
            <div className="mx-auto flex w-full max-w-5xl flex-col gap-5 px-4 py-6 sm:px-8">
              {children}
            </div>
          </main>
        )}
      </div>
      {panel}
    </>
  );
}

/** A titled block of a page: a form, a list, a table. */
export function Section({
  title,
  description,
  actions,
  children,
  className,
}: {
  title?: string;
  description?: string;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("flex flex-col gap-4 rounded-xl border bg-card p-5", className)}>
      {(title !== undefined || actions !== undefined) && (
        <div className="flex flex-wrap items-start gap-3">
          <div className="min-w-0 flex-1">
            {title !== undefined && <h2 className="font-medium">{title}</h2>}
            {description !== undefined && (
              <p className="mt-0.5 text-sm text-muted-foreground">{description}</p>
            )}
          </div>
          {actions}
        </div>
      )}
      {children}
    </section>
  );
}

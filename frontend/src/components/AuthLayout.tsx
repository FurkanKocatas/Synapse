import { FileSearch, Lock, Server } from "lucide-react";
import type { ReactNode } from "react";

import { LanguageSwitch } from "@/components/LanguageSwitch";
import { LogoMark } from "@/components/Logo";
import { ThemeSwitch } from "@/components/ThemeSwitch";
import { m } from "@/paraglide/messages.js";

interface AuthLayoutProps {
  title: string;
  description?: string;
  children: ReactNode;
}

const POINTS = [
  { icon: FileSearch, text: m.auth_brand_point_cited },
  { icon: Lock, text: m.auth_brand_point_access },
  { icon: Server, text: m.auth_brand_point_local },
];

/** Every sign-in step: what the product is on one side, the step's form on the other. */
export function AuthLayout({ title, description, children }: AuthLayoutProps) {
  return (
    <div className="grid min-h-screen bg-background lg:grid-cols-[1fr_1fr]">
      <aside className="relative hidden flex-col overflow-hidden bg-rail p-10 text-rail-foreground lg:flex">
        <Network />
        <div className="relative flex items-center gap-3">
          <LogoMark className="size-9" />
          <span className="text-lg font-semibold">{m.app_name()}</span>
        </div>
        <div className="relative mt-auto max-w-md">
          <p className="text-3xl leading-tight font-semibold tracking-tight">
            {m.auth_brand_title()}
          </p>
          <p className="mt-3 text-rail-muted">{m.app_tagline()}</p>
          <ul className="mt-8 flex flex-col gap-3 text-sm">
            {POINTS.map(({ icon: Icon, text }) => (
              <li key={text()} className="flex items-start gap-3">
                <span className="flex size-7 shrink-0 items-center justify-center rounded-lg bg-white/10">
                  <Icon className="size-4" aria-hidden="true" />
                </span>
                <span className="pt-1">{text()}</span>
              </li>
            ))}
          </ul>
        </div>
      </aside>
      <div className="flex min-h-screen flex-col">
        <header className="flex items-center justify-between gap-2 p-4">
          <span className="flex items-center gap-2 font-semibold lg:invisible">
            <LogoMark className="size-7" />
            {m.app_name()}
          </span>
          <div className="flex items-center gap-2">
            <LanguageSwitch compact />
            <ThemeSwitch />
          </div>
        </header>
        <main className="flex flex-1 items-center justify-center p-4 pb-16">
          <div className="w-full max-w-sm">
            <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
            {description === undefined ? null : (
              <p className="mt-1.5 text-sm text-muted-foreground">{description}</p>
            )}
            <div className="mt-6">{children}</div>
          </div>
        </main>
      </div>
    </div>
  );
}

/** Nodes and links, faint, behind the brand panel. */
function Network() {
  const nodes = [
    [60, 80],
    [210, 40],
    [330, 150],
    [140, 220],
    [420, 60],
    [470, 260],
    [260, 330],
    [90, 400],
    [390, 420],
  ];
  const links = [
    [0, 1],
    [1, 2],
    [0, 3],
    [3, 2],
    [1, 4],
    [2, 5],
    [3, 6],
    [6, 5],
    [6, 7],
    [6, 8],
    [5, 8],
  ];
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 520 480"
      className="pointer-events-none absolute -top-10 -right-24 w-[620px] opacity-25"
    >
      {links.map(([a = 0, b = 0]) => (
        <line
          key={`${String(a)}-${String(b)}`}
          x1={nodes[a]?.[0]}
          y1={nodes[a]?.[1]}
          x2={nodes[b]?.[0]}
          y2={nodes[b]?.[1]}
          className="stroke-rail-muted"
          strokeWidth="1.2"
        />
      ))}
      {nodes.map(([x, y], index) => (
        <circle
          key={index}
          cx={x}
          cy={y}
          r={index % 3 === 0 ? 7 : 4.5}
          className={index % 3 === 0 ? "fill-highlight" : "fill-rail-foreground"}
        />
      ))}
    </svg>
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

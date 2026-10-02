import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

// Elements written as the rest of the page is; links open in a new tab and say where to.
const COMPONENTS: Components = {
  p: ({ children }) => <p className="my-3 first:mt-0 last:mb-0">{children}</p>,
  ul: ({ children }) => <ul className="my-3 list-disc space-y-1 pl-6">{children}</ul>,
  ol: ({ children }) => <ol className="my-3 list-decimal space-y-1 pl-6">{children}</ol>,
  h1: ({ children }) => <h3 className="mt-5 mb-2 text-lg font-semibold">{children}</h3>,
  h2: ({ children }) => <h3 className="mt-5 mb-2 text-lg font-semibold">{children}</h3>,
  h3: ({ children }) => <h4 className="mt-4 mb-2 text-base font-semibold">{children}</h4>,
  h4: ({ children }) => <h4 className="mt-4 mb-2 text-base font-semibold">{children}</h4>,
  strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
  a: ({ href, children }) => (
    <a
      href={href}
      target="_blank"
      rel="noreferrer noopener"
      className="text-secondary-foreground underline underline-offset-4"
    >
      {children}
    </a>
  ),
  blockquote: ({ children }) => (
    <blockquote className="my-3 border-l-2 border-input pl-3 text-subtle-foreground">
      {children}
    </blockquote>
  ),
  code: ({ className, children }) =>
    className?.startsWith("language-") ? (
      <code className={className}>{children}</code>
    ) : (
      <code className="rounded-md bg-muted px-1.5 py-0.5 font-mono text-[0.9em]">{children}</code>
    ),
  pre: ({ children }) => (
    <pre className="my-3 overflow-x-auto rounded-xl bg-foreground/[0.04] p-4 font-mono text-[13px] leading-relaxed dark:bg-white/[0.06]">
      {children}
    </pre>
  ),
  table: ({ children }) => (
    <div className="my-3 overflow-x-auto rounded-xl border">
      <table className="w-full text-sm">{children}</table>
    </div>
  ),
  th: ({ children }) => (
    <th className="border-b bg-sidebar px-3 py-2 text-left font-medium">{children}</th>
  ),
  td: ({ children }) => <td className="border-t px-3 py-2">{children}</td>,
  hr: () => <hr className="my-4" />,
};

/** An answer that rests on no document, written in Markdown by the model. Raw HTML in it is
 * left out, never rendered (ADR 0011). */
export function Markdown({ text }: { text: string }) {
  return (
    <div className="text-base leading-[1.75] text-pretty">
      <ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml components={COMPONENTS}>
        {text}
      </ReactMarkdown>
    </div>
  );
}

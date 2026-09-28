import { LanguageSwitch } from "./components/LanguageSwitch";
import { m } from "./paraglide/messages.js";

export function App() {
  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col gap-6 p-8">
      <header className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">{m.app_name()}</h1>
        <LanguageSwitch />
      </header>
      <p className="text-lg">{m.app_tagline()}</p>
    </main>
  );
}

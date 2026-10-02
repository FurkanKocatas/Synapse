import { Menu } from "@base-ui/react/menu";
import { CaretUpDownIcon, SignOutIcon, UserCircleIcon } from "@phosphor-icons/react";
import { useQueryClient, useSuspenseQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useState } from "react";

import { chooseLocale, languageNames } from "@/components/LanguageSwitch";
import { switchTheme, THEMES } from "@/components/ThemeSwitch";
import {
  menuItem,
  menuLabel,
  menuPopup,
  menuSeparator,
  segment,
  segmented,
} from "@/components/ui/menu";
import { roleLabel } from "@/features/admin/labels";
import { logout } from "@/features/auth/authApi";
import { sessionQuery } from "@/features/auth/session";
import { initials } from "@/lib/initials";
import { storedTheme, type ThemeChoice } from "@/lib/theme";
import { m } from "@/paraglide/messages.js";
import { getLocale, locales, type Locale } from "@/paraglide/runtime.js";

/** Who is signed in, at the foot of the navigation; the account page, the theme, the language
 * and signing out are in its menu. */
export function AccountMenu() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data: session } = useSuspenseQuery(sessionQuery);
  const [theme, setTheme] = useState<ThemeChoice>(storedTheme);
  const user = session?.user;

  async function signOut() {
    await logout();
    queryClient.setQueryData(sessionQuery.queryKey, null);
    await navigate({ to: "/login" });
  }

  return (
    <Menu.Root>
      <Menu.Trigger
        aria-label={m.account_menu()}
        className="mt-2 flex w-full items-center gap-2.5 rounded-lg p-1.5 text-left transition-colors outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring data-[popup-open]:bg-accent"
      >
        <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-secondary text-xs font-semibold text-secondary-foreground">
          {initials(user?.display_name ?? "")}
        </span>
        <span className="min-w-0 flex-1 leading-tight">
          <span className="block truncate text-sm font-medium">{user?.display_name}</span>
          <span className="block truncate text-xs text-muted-foreground">{user?.email}</span>
        </span>
        <CaretUpDownIcon className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
      </Menu.Trigger>
      <Menu.Portal>
        <Menu.Positioner side="top" align="start" sideOffset={6} className="z-50">
          <Menu.Popup className={`${menuPopup} w-(--anchor-width) min-w-60`}>
            <div className="px-2.5 pt-1.5 pb-2 leading-snug">
              <p className="font-medium">{user?.display_name}</p>
              <p className="truncate text-xs text-muted-foreground">
                {user?.role === undefined ? "" : `${roleLabel[user.role]()} · `}
                {user?.email}
              </p>
            </div>
            <Menu.Separator className={menuSeparator} />
            <Menu.Item className={menuItem} onClick={() => void navigate({ to: "/account" })}>
              <UserCircleIcon aria-hidden="true" />
              {m.nav_account()}
            </Menu.Item>
            <Menu.Group>
              <Menu.GroupLabel className={menuLabel}>{m.theme_label()}</Menu.GroupLabel>
              <Menu.RadioGroup
                value={theme}
                onValueChange={(value: ThemeChoice) => {
                  switchTheme(value);
                  setTheme(value);
                }}
                className={segmented}
              >
                {THEMES.map(([value, IconFor, label]) => (
                  <Menu.RadioItem key={value} value={value} className={segment}>
                    <IconFor aria-hidden="true" />
                    {label()}
                  </Menu.RadioItem>
                ))}
              </Menu.RadioGroup>
            </Menu.Group>
            <Menu.Group>
              <Menu.GroupLabel className={menuLabel}>{m.language_switch_label()}</Menu.GroupLabel>
              <Menu.RadioGroup
                value={getLocale()}
                onValueChange={(value: Locale) => void chooseLocale(queryClient, value)}
                className={segmented}
              >
                {locales.map((locale) => (
                  <Menu.RadioItem key={locale} value={locale} className={segment}>
                    {languageNames[locale]()}
                  </Menu.RadioItem>
                ))}
              </Menu.RadioGroup>
            </Menu.Group>
            <Menu.Separator className={menuSeparator} />
            <Menu.Item className={menuItem} onClick={() => void signOut()}>
              <SignOutIcon aria-hidden="true" />
              {m.auth_logout()}
            </Menu.Item>
          </Menu.Popup>
        </Menu.Positioner>
      </Menu.Portal>
    </Menu.Root>
  );
}

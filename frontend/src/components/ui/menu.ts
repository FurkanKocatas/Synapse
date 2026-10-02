// Shared looks for Base UI's menus, popovers and dialogs, so they open and close alike.

export const floatingPanel =
  "rounded-xl border bg-popover text-popover-foreground shadow-floating outline-none origin-[var(--transform-origin)] transition-[opacity,scale] duration-150 ease-out-soft data-[starting-style]:scale-97 data-[starting-style]:opacity-0 data-[ending-style]:scale-97 data-[ending-style]:opacity-0";

export const menuPopup = `${floatingPanel} min-w-52 p-1 text-sm`;

export const menuItem =
  "flex h-8 cursor-default items-center gap-2.5 rounded-md px-2.5 outline-none select-none data-[highlighted]:bg-accent [&_svg]:size-4 [&_svg]:text-subtle-foreground";

export const menuItemDanger = `${menuItem} text-destructive [&_svg]:text-destructive`;

export const menuSeparator = "-mx-1 my-1 h-px bg-border";

export const menuLabel = "px-2.5 pt-1.5 pb-1 text-xs text-muted-foreground";

export const segmented = "mx-1.5 mb-1 flex rounded-lg bg-muted p-0.5";

export const segment =
  "flex h-7 flex-1 cursor-default items-center justify-center gap-1.5 rounded-md text-xs text-subtle-foreground outline-none data-[checked]:bg-card data-[checked]:text-foreground data-[checked]:shadow-raised data-[highlighted]:text-foreground [&_svg]:size-3.5";

export const dialogBackdrop =
  "fixed inset-0 z-50 bg-black/40 transition-opacity duration-200 data-[starting-style]:opacity-0 data-[ending-style]:opacity-0";

export const dialogPopup =
  "fixed top-1/2 left-1/2 z-50 w-[min(28rem,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 rounded-xl border bg-popover p-5 text-popover-foreground shadow-floating outline-none transition-[opacity,scale] duration-200 ease-out-soft data-[starting-style]:scale-97 data-[starting-style]:opacity-0 data-[ending-style]:scale-97 data-[ending-style]:opacity-0";

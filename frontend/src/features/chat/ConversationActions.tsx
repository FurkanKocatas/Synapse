import { AlertDialog } from "@base-ui/react/alert-dialog";
import { Dialog } from "@base-ui/react/dialog";
import { Menu } from "@base-ui/react/menu";
import { DotsThreeIcon, PencilSimpleIcon, TrashIcon } from "@phosphor-icons/react";
import { useLocation, useNavigate, useSearch } from "@tanstack/react-router";
import { useState, type SubmitEvent } from "react";

import { FormError } from "@/components/AuthLayout";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  dialogBackdrop,
  dialogPopup,
  menuItem,
  menuItemDanger,
  menuPopup,
} from "@/components/ui/menu";
import { useAction } from "@/lib/useAction";
import { cn } from "@/lib/utils";
import { m } from "@/paraglide/messages.js";

import { CHAT_PATH, chatApi, CONVERSATIONS, conversationKey, modeOf } from "./chatApi";

interface Named {
  id: string;
  title: string;
}

/** A conversation's menu: rename it, or delete it after asking. */
export function ConversationActions({
  conversation,
  label,
  className,
}: {
  conversation: Named;
  label: string;
  className?: string;
}) {
  const [dialog, setDialog] = useState<"rename" | "delete" | null>(null);
  const close = () => {
    setDialog(null);
  };

  return (
    <>
      <Menu.Root>
        <Menu.Trigger
          aria-label={label}
          className={cn(
            "flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors outline-none hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring data-[popup-open]:bg-muted data-[popup-open]:text-foreground",
            className,
          )}
        >
          <DotsThreeIcon weight="bold" className="size-4" aria-hidden="true" />
        </Menu.Trigger>
        <Menu.Portal>
          <Menu.Positioner align="start" sideOffset={4} className="z-50">
            <Menu.Popup className={menuPopup}>
              <Menu.Item
                className={menuItem}
                onClick={() => {
                  setDialog("rename");
                }}
              >
                <PencilSimpleIcon aria-hidden="true" />
                {m.chat_rename()}
              </Menu.Item>
              <Menu.Item
                className={menuItemDanger}
                onClick={() => {
                  setDialog("delete");
                }}
              >
                <TrashIcon aria-hidden="true" />
                {m.chat_delete()}
              </Menu.Item>
            </Menu.Popup>
          </Menu.Positioner>
        </Menu.Portal>
      </Menu.Root>
      <RenameDialog conversation={conversation} open={dialog === "rename"} onClose={close} />
      <DeleteDialog conversation={conversation} open={dialog === "delete"} onClose={close} />
    </>
  );
}

function RenameDialog({
  conversation,
  open,
  onClose,
}: {
  conversation: Named;
  open: boolean;
  onClose: () => void;
}) {
  return (
    <Dialog.Root
      open={open}
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
    >
      <Dialog.Portal>
        <Dialog.Backdrop className={dialogBackdrop} />
        <Dialog.Popup className={dialogPopup}>
          <Dialog.Title className="font-medium">{m.chat_rename()}</Dialog.Title>
          <RenameForm conversation={conversation} onDone={onClose} />
        </Dialog.Popup>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

// Its own component, so it starts from the current title each time the dialog opens.
function RenameForm({ conversation, onDone }: { conversation: Named; onDone: () => void }) {
  const [title, setTitle] = useState(conversation.title);
  const { run, error, busy } = useAction();

  async function rename(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    const ok = await run(
      () => chatApi.rename(conversation.id, title.trim()),
      [CONVERSATIONS, conversationKey(conversation.id)],
    );
    if (ok) onDone();
  }

  return (
    <form className="mt-4 flex flex-col gap-4" onSubmit={(event) => void rename(event)}>
      <div className="flex flex-col gap-2">
        <Label htmlFor="conversation-title">{m.chat_title_label()}</Label>
        <Input
          id="conversation-title"
          value={title}
          maxLength={200}
          autoFocus
          onChange={(event) => {
            setTitle(event.target.value);
          }}
        />
      </div>
      <FormError message={error} />
      <div className="flex justify-end gap-2">
        <Dialog.Close render={<Button type="button" variant="outline" />}>
          {m.common_cancel()}
        </Dialog.Close>
        <Button type="submit" disabled={busy || title.trim() === ""}>
          {m.chat_save()}
        </Button>
      </div>
    </form>
  );
}

function DeleteDialog({
  conversation,
  open,
  onClose,
}: {
  conversation: Named;
  open: boolean;
  onClose: () => void;
}) {
  const { c: openId } = useSearch({ strict: false });
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const { run, error, busy } = useAction();

  async function remove() {
    if (await run(() => chatApi.remove(conversation.id), [CONVERSATIONS])) {
      onClose();
      if (openId === conversation.id) {
        await navigate({
          to: CHAT_PATH[modeOf(pathname)],
          search: {},
          state: () => ({ fresh: Date.now() }),
        });
      }
    }
  }

  return (
    <AlertDialog.Root
      open={open}
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
    >
      <AlertDialog.Portal>
        <AlertDialog.Backdrop className={dialogBackdrop} />
        <AlertDialog.Popup className={dialogPopup}>
          <AlertDialog.Title className="font-medium">{m.chat_delete()}</AlertDialog.Title>
          <AlertDialog.Description className="mt-1.5 text-sm text-muted-foreground">
            {m.chat_delete_confirm()}
          </AlertDialog.Description>
          <p className="mt-3 truncate rounded-lg bg-muted px-3 py-2 text-sm">
            {conversation.title}
          </p>
          <div className="mt-2">
            <FormError message={error} />
          </div>
          <div className="mt-3 flex justify-end gap-2">
            <AlertDialog.Close render={<Button type="button" variant="outline" />}>
              {m.common_cancel()}
            </AlertDialog.Close>
            <Button variant="destructive" disabled={busy} onClick={() => void remove()}>
              {m.common_remove()}
            </Button>
          </div>
        </AlertDialog.Popup>
      </AlertDialog.Portal>
    </AlertDialog.Root>
  );
}

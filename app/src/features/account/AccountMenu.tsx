import { Check, LogIn, LogOut, Plus, Settings, Trash2 } from "lucide-react";
import { accountKey, forgetAccount, logout, switchAccount, useAccount } from "@/lib/account";
import { appStore } from "@/lib/app-state";
import { Popover, PopoverClose, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { Avatar } from "./Avatar";
import { openAccountDialog } from "./AccountDialog";

export function AccountMenu() {
  const user = useAccount((s) => s.user);
  const accounts = useAccount((s) => s.accounts);
  const activeKey = useAccount((s) => s.activeKey);
  const offline = useAccount((s) => s.offline);

  const item = "flex w-full cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs text-muted hover:bg-surface-2 hover:text-fg [&_svg]:size-3.5";
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button className="relative cursor-pointer rounded-full transition-shadow hover:shadow-glow" aria-label="Account">
          {user ? <Avatar name={user.username} url={user.avatar_url} size={30} /> : (
            <span className="flex size-[30px] items-center justify-center rounded-full border border-border text-faint hover:text-fg"><LogIn className="size-4" /></span>
          )}
          {user && <span className={cn("absolute -bottom-0.5 -right-0.5 size-2.5 rounded-full border-2 border-bg", offline ? "bg-warning" : "bg-success")} />}
        </button>
      </PopoverTrigger>
      <PopoverContent side="right" align="end">
        {user ? (
          <div className="flex items-center gap-2.5 border-b border-border px-2 pb-2.5 pt-1.5">
            <Avatar name={user.username} url={user.avatar_url} size={34} />
            <div className="min-w-0">
              <div className="flex items-center gap-1.5 truncate text-[13px] font-medium">
                {user.display_name}
                {user.role === "owner" && <Badge variant="accent">Owner</Badge>}
              </div>
              <div className="truncate text-[11px] text-muted">@{user.username} · {user.plan}</div>
            </div>
          </div>
        ) : (
          <PopoverClose className={item} onClick={() => openAccountDialog("login")}><LogIn /> Sign in</PopoverClose>
        )}
        {accounts.length > 0 && (
          <div className="border-b border-border py-1">
            <div className="px-2 py-1 text-[10px] uppercase tracking-wider text-faint">Accounts</div>
            {accounts.map((a) => {
              const key = accountKey(a.server, a.username);
              return (
                <div key={key} className="group flex items-center">
                  <PopoverClose className={item} onClick={async () => { if (!(await switchAccount(key))) openAccountDialog("login", a.username); }}>
                    <Avatar name={a.username} url={a.avatar_url} size={20} />
                    <span className="truncate">{a.username}</span>
                    {key === activeKey && user && <Check className="ml-auto text-accent" />}
                  </PopoverClose>
                  <button className="hidden cursor-pointer p-1 text-faint hover:text-danger group-hover:block" title="Remove from this computer" onClick={() => forgetAccount(key)}>
                    <Trash2 className="size-3" />
                  </button>
                </div>
              );
            })}
          </div>
        )}
        <div className="pt-1">
          <PopoverClose className={item} onClick={() => openAccountDialog("login")}><Plus /> Add account</PopoverClose>
          {user && <PopoverClose className={item} onClick={() => appStore.setState({ view: "settings" })}><Settings /> Account settings</PopoverClose>}
          {user && <PopoverClose className={item} onClick={() => logout()}><LogOut /> Sign out</PopoverClose>}
        </div>
      </PopoverContent>
    </Popover>
  );
}

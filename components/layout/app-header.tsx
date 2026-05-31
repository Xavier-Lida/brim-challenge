"use client";

import { usePathname } from "next/navigation";
import { BellIcon, MagnifyingGlassIcon } from "@phosphor-icons/react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { SidebarTrigger } from "@/components/ui/sidebar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useMockStore } from "@/lib/hooks/use-mock-store";

const pageTitles: Record<string, string> = {
  "/assistant": "Brim Assistant",
  "/approvals": "Approvals",
  "/flagged": "Flagged transactions",
  "/transactions": "Transactions",
  "/reports": "Expense reports",
  "/policy": "Expense policy",
  "/settings": "Settings",
};

function formatRelativeTime(iso: string) {
  const diff = Date.now() - new Date(iso).getTime();
  const hours = Math.floor(diff / (1000 * 60 * 60));
  if (hours < 1) return "Just now";
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export function AppHeader() {
  const pathname = usePathname();
  const {
    searchQuery,
    setSearchQuery,
    notifications,
    unreadNotificationsCount,
    markNotificationRead,
  } = useMockStore();

  const title = pageTitles[pathname] ?? "Brim";

  return (
    <header className="flex h-16 shrink-0 items-center gap-3 border-b border-dim-gray/40 bg-arctic-mist px-5">
      <SidebarTrigger className="text-muted-foreground hover:text-foreground" />
      <h1 className="hidden text-base font-semibold text-deep-ocean tracking-[-0.29px] sm:block" style={{ fontSize: "16px", lineHeight: 1.43 }}>
        {title}
      </h1>
      <div className="ml-auto flex items-center gap-2">
        <div className="relative hidden w-64 md:block">
          <MagnifyingGlassIcon className="absolute top-1/2 left-3.5 -translate-y-1/2 text-muted-foreground" size={15} />
          <Input
            placeholder="Search transactions..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-9 h-9 border-dim-gray/60"
          />
        </div>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon-sm" className="relative text-muted-foreground hover:text-foreground">
              <BellIcon size={18} />
              {unreadNotificationsCount > 0 && (
                <span className="absolute top-1.5 right-1.5 size-2 rounded-full bg-hope-blue" />
              )}
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-80 rounded-[18px] border-dim-gray/40">
            <DropdownMenuGroup>
              <DropdownMenuLabel className="text-deep-ocean font-semibold tracking-[-0.25px]">Notifications</DropdownMenuLabel>
              <DropdownMenuSeparator />
              {notifications.map((notif) => (
                <DropdownMenuItem
                  key={notif.id}
                  className="flex flex-col items-start gap-0.5 py-2.5 rounded-[10px]"
                  onClick={() => markNotificationRead(notif.id)}
                >
                  <span
                    className={
                      notif.read
                        ? "text-sm text-muted-foreground"
                        : "text-sm font-medium text-foreground tracking-[-0.25px]"
                    }
                  >
                    {notif.message}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {formatRelativeTime(notif.created_at)}
                  </span>
                </DropdownMenuItem>
              ))}
            </DropdownMenuGroup>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  );
}

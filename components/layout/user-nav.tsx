"use client";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { useMockStore } from "@/lib/hooks/use-mock-store";

export function UserNav() {
  const { workspaceUser } = useMockStore();
  const initials = workspaceUser.name
    .split(" ")
    .map((n) => n[0])
    .join("");

  return (
    <div className="flex items-center gap-2.5 px-1 py-1">
      <Avatar size="sm">
        <AvatarFallback className="bg-hope-blue/20 text-white text-xs font-semibold">
          {initials}
        </AvatarFallback>
      </Avatar>
      <div className="flex min-w-0 flex-col">
        <span className="truncate text-sm font-semibold text-sidebar-foreground tracking-[-0.25px]">
          {workspaceUser.name}
        </span>
        <span className="truncate text-xs text-sidebar-foreground/60">
          {workspaceUser.role}
        </span>
      </div>
    </div>
  );
}

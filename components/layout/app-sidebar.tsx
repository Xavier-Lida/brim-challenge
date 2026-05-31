"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  CheckCircleIcon,
  FileTextIcon,
  FlagIcon,
  GearIcon,
  ReceiptIcon,
  ShieldIcon,
  SparkleIcon,
} from "@phosphor-icons/react";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarSeparator,
} from "@/components/ui/sidebar";
import { CompanySpendCard } from "@/components/layout/company-spend-card";
import { UserNav } from "@/components/layout/user-nav";
import { useMockStore } from "@/lib/hooks/use-mock-store";

const navItems = [
  { title: "Brim Assistant", href: "/assistant", icon: SparkleIcon },
  { title: "Approvals", href: "/approvals", icon: CheckCircleIcon, badge: "approvals" as const },
  { title: "Flagged", href: "/flagged", icon: FlagIcon },
  { title: "Transactions", href: "/transactions", icon: ReceiptIcon },
  { title: "Reports", href: "/reports", icon: FileTextIcon },
  { title: "Policy", href: "/policy", icon: ShieldIcon },
  { title: "Settings", href: "/settings", icon: GearIcon },
];

export function AppSidebar() {
  const pathname = usePathname();
  const { pendingApprovalsCount } = useMockStore();

  const getBadgeCount = (type?: "approvals") => {
    if (type === "approvals") return pendingApprovalsCount;
    return 0;
  };

  return (
    <Sidebar>
      <SidebarHeader className="border-b border-sidebar-border p-5">
        <Link href="/assistant" className="flex items-center gap-3">
          <div className="flex size-9 items-center justify-center rounded-[12px] bg-hope-blue/20 text-white">
            <SparkleIcon weight="fill" size={18} />
          </div>
          <div className="flex flex-col">
            <span className="text-sm font-semibold text-sidebar-foreground tracking-[-0.25px]">
              Northwind Labs
            </span>
            <span className="text-xs text-sidebar-foreground/60">Brim workspace</span>
          </div>
        </Link>
      </SidebarHeader>
      <SidebarContent className="pt-2">
        <SidebarGroup>
          <SidebarGroupContent>
            <SidebarMenu>
              {navItems.map((item) => {
                const count = getBadgeCount(item.badge);
                const isActive =
                  pathname === item.href ||
                  (item.href !== "/assistant" && pathname.startsWith(item.href));

                return (
                  <SidebarMenuItem key={item.href}>
                    <SidebarMenuButton asChild isActive={isActive} className="rounded-[10px] text-sidebar-foreground/80 hover:bg-sidebar-accent hover:text-sidebar-foreground data-[active=true]:bg-hope-blue data-[active=true]:text-white data-[active=true]:shadow-[rgba(154,207,246,0.3)_0px_4px_0px_0px]">
                      <Link href={item.href}>
                        <item.icon weight={isActive ? "fill" : "regular"} />
                        <span>{item.title}</span>
                      </Link>
                    </SidebarMenuButton>
                    {count > 0 && item.badge && (
                      <SidebarMenuBadge className="rounded-full bg-hope-blue/20 text-white text-xs">
                        {count}
                      </SidebarMenuBadge>
                    )}
                  </SidebarMenuItem>
                );
              })}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
      <SidebarFooter className="flex flex-col gap-3 p-4">
        <CompanySpendCard />
        <SidebarSeparator className="bg-sidebar-border" />
        <UserNav />
      </SidebarFooter>
    </Sidebar>
  );
}

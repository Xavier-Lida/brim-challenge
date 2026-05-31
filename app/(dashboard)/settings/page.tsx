"use client";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useMockStore } from "@/lib/hooks/use-mock-store";

export default function SettingsPage() {
  const { workspaceUser } = useMockStore();

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6">
      <div>
        <h2 className="text-xl font-normal text-foreground/90">
          Settings
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Workspace and notification preferences
        </p>
      </div>

      <Card className="border-border/50 shadow-none">
        <CardHeader>
          <CardTitle className="text-base font-medium">Workspace</CardTitle>
          <CardDescription>
            Company-wide settings for Northwind Labs
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="workspace">Workspace name</Label>
            <Input id="workspace" defaultValue="Northwind Labs" />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="approver">Primary approver email</Label>
            <Input
              id="approver"
              type="email"
              defaultValue={workspaceUser.email}
            />
          </div>
        </CardContent>
      </Card>

      <Card className="border-border/50 shadow-none">
        <CardHeader>
          <CardTitle className="text-base font-medium">Notifications</CardTitle>
          <CardDescription>
            When Brim sends email alerts to approvers
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="weight-threshold">
              Compliance flag email threshold
            </Label>
            <Input
              id="weight-threshold"
              type="number"
              defaultValue={3}
              min={1}
              max={5}
            />
            <p className="text-xs text-muted-foreground">
              Send email when flag weight is ≥ this value (default: 3)
            </p>
          </div>
          <Separator />
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="approval-threshold">
              Pre-approval amount threshold
            </Label>
            <Input
              id="approval-threshold"
              defaultValue="$500"
              placeholder="$500"
            />
            <p className="text-xs text-muted-foreground">
              Matches hardware approval policy — editable when backend is connected
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

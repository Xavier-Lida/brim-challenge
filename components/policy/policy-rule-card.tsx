"use client";

import {
  CurrencyDollarIcon,
  ShieldIcon,
  WarningIcon,
} from "@phosphor-icons/react";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { Button } from "@/components/ui/button";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import type { Policy } from "@/lib/types/brim";
import { TrashIcon } from "@phosphor-icons/react";
import { EditPolicyDialog } from "@/components/policy/edit-policy-dialog";

function PolicyIcon({ req }: { req: Policy["policy_requirements"] }) {
  if (
    (req.restricted_categories?.length ?? 0) > 0 ||
    (req.restricted_merchants?.length ?? 0) > 0
  ) {
    return <WarningIcon />;
  }
  if (req.approval_threshold_cad != null) {
    return <ShieldIcon />;
  }
  return <CurrencyDollarIcon />;
}

type PolicyRuleCardProps = {
  policy: Policy;
  onToggle: (id: string) => void;
  onDelete: (id: string) => void;
};

export function PolicyRuleCard({
  policy,
  onToggle,
  onDelete,
}: PolicyRuleCardProps) {
  const req = policy.policy_requirements;
  const categoryEntries = Object.entries(req.category_limits_cad ?? {});

  return (
    <div className="flex items-start gap-4 rounded-[18px] border border-dim-gray/40 bg-card p-6 shadow-[rgba(0,0,0,0.05)_0px_3px_0px_0px]">
      <div className="flex size-10 shrink-0 items-center justify-center rounded-full bg-powder-blue text-hope-blue">
        <PolicyIcon req={req} />
      </div>
      <div className="flex min-w-0 flex-1 flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="text-sm font-medium text-foreground">
            {policy.policy_name}
          </h3>
          <Badge variant="secondary">
            {policy.active ? "Active" : "Inactive"}
          </Badge>
          <Badge variant="outline">{policy.effective_date}</Badge>
        </div>
        {req.approval_threshold_cad != null && (
          <p className="text-base font-medium text-primary">
            Pre-approval above ${req.approval_threshold_cad} CAD
          </p>
        )}
        {categoryEntries.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {categoryEntries.map(([category, limit]) => (
              <Badge key={category} variant="secondary" className="font-normal">
                {category}: ${limit} max
              </Badge>
            ))}
          </div>
        )}
        {(req.restricted_categories?.length ?? 0) > 0 && (
          <p className="text-sm text-muted-foreground">
            Blocked categories: {req.restricted_categories?.join(", ")}
          </p>
        )}
        {(req.restricted_merchants?.length ?? 0) > 0 && (
          <p className="text-sm text-muted-foreground">
            Blocked merchants: {req.restricted_merchants?.join(", ")}
          </p>
        )}
        {req.notes && (
          <p className="text-sm text-muted-foreground">{req.notes}</p>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <Switch
          checked={policy.active}
          onCheckedChange={() => onToggle(policy.id)}
        />
        <EditPolicyDialog policy={policy} />
        <AlertDialog>
          <AlertDialogTrigger asChild>
            <Button variant="ghost" size="icon-sm">
              <TrashIcon />
            </Button>
          </AlertDialogTrigger>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>Delete this rule?</AlertDialogTitle>
              <AlertDialogDescription>
                &ldquo;{policy.policy_name}&rdquo; will be permanently removed from
                Supabase. Use the toggle to disable a rule without deleting it.
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>Cancel</AlertDialogCancel>
              <AlertDialogAction onClick={() => onDelete(policy.id)}>
                Delete
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </div>
    </div>
  );
}

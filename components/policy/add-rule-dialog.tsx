"use client";

import { useState } from "react";
import { PlusIcon, TrashIcon } from "@phosphor-icons/react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { BRIM_CATEGORIES } from "@/lib/constants/brim-categories";
import { useMockStore } from "@/lib/hooks/use-mock-store";
import type { PolicyRequirements } from "@/lib/types/brim";

type CategoryLimitRow = { category: string; limit: string };

const emptyForm = {
  policy_name: "",
  approval_threshold_cad: "",
  notes: "",
  effective_date: new Date().toISOString().slice(0, 10),
  restricted_categories: "",
  restricted_merchants: "",
  category_limits: [{ category: BRIM_CATEGORIES[0], limit: "" }] as CategoryLimitRow[],
};

export function AddRuleDialog() {
  const { addPolicy } = useMockStore();
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [form, setForm] = useState(emptyForm);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.policy_name.trim()) {
      toast.error("Policy name is required");
      return;
    }

    const category_limits_cad: Record<string, number> = {};
    for (const row of form.category_limits) {
      const limit = parseFloat(row.limit);
      if (row.category && !Number.isNaN(limit)) {
        category_limits_cad[row.category] = limit;
      }
    }

    const requirements: PolicyRequirements = {
      notes: form.notes.trim() || undefined,
      category_limits_cad:
        Object.keys(category_limits_cad).length > 0 ? category_limits_cad : undefined,
      restricted_categories: form.restricted_categories
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
      restricted_merchants: form.restricted_merchants
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
    };

    const threshold = parseFloat(form.approval_threshold_cad);
    if (!Number.isNaN(threshold)) {
      requirements.approval_threshold_cad = threshold;
    }

    setLoading(true);
    try {
      await addPolicy({
        policy_name: form.policy_name.trim(),
        policy_requirements: requirements,
        effective_date: form.effective_date,
      });
      toast.success("Policy rule added");
      setOpen(false);
      setForm(emptyForm);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to add policy");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline">
          <PlusIcon data-icon="inline-start" />
          Add rule
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[90vh] max-w-lg overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Add expense rule</DialogTitle>
          <DialogDescription>
            Define structured policy requirements. Brim&apos;s compliance engine uses
            these thresholds directly.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="policy_name">Rule name</Label>
            <Input
              id="policy_name"
              value={form.policy_name}
              onChange={(e) =>
                setForm((f) => ({ ...f, policy_name: e.target.value }))
              }
              placeholder="Meal limits"
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="approval_threshold">Pre-approval threshold (CAD)</Label>
              <Input
                id="approval_threshold"
                type="number"
                min="0"
                value={form.approval_threshold_cad}
                onChange={(e) =>
                  setForm((f) => ({
                    ...f,
                    approval_threshold_cad: e.target.value,
                  }))
                }
                placeholder="500"
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="effective_date">Effective date</Label>
              <Input
                id="effective_date"
                type="date"
                value={form.effective_date}
                onChange={(e) =>
                  setForm((f) => ({ ...f, effective_date: e.target.value }))
                }
              />
            </div>
          </div>

          <div className="flex flex-col gap-2">
            <Label>Category limits (CAD per transaction)</Label>
            {form.category_limits.map((row, index) => (
              <div key={index} className="flex gap-2">
                <select
                  value={row.category}
                  onChange={(e) =>
                    setForm((f) => {
                      const next = [...f.category_limits];
                      next[index] = { ...next[index], category: e.target.value };
                      return { ...f, category_limits: next };
                    })
                  }
                  className="flex h-9 min-w-0 flex-1 rounded-md border border-input bg-transparent px-2 text-sm"
                >
                  {BRIM_CATEGORIES.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </select>
                <Input
                  type="number"
                  min="0"
                  placeholder="75"
                  value={row.limit}
                  onChange={(e) =>
                    setForm((f) => {
                      const next = [...f.category_limits];
                      next[index] = { ...next[index], limit: e.target.value };
                      return { ...f, category_limits: next };
                    })
                  }
                  className="w-24"
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-sm"
                  disabled={form.category_limits.length === 1}
                  onClick={() =>
                    setForm((f) => ({
                      ...f,
                      category_limits: f.category_limits.filter((_, i) => i !== index),
                    }))
                  }
                >
                  <TrashIcon />
                </Button>
              </div>
            ))}
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() =>
                setForm((f) => ({
                  ...f,
                  category_limits: [
                    ...f.category_limits,
                    { category: BRIM_CATEGORIES[0], limit: "" },
                  ],
                }))
              }
            >
              Add category limit
            </Button>
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="restricted_categories">Restricted categories (comma-separated)</Label>
            <Input
              id="restricted_categories"
              value={form.restricted_categories}
              onChange={(e) =>
                setForm((f) => ({ ...f, restricted_categories: e.target.value }))
              }
              placeholder="Autre"
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="restricted_merchants">Restricted merchants (comma-separated)</Label>
            <Input
              id="restricted_merchants"
              value={form.restricted_merchants}
              onChange={(e) =>
                setForm((f) => ({ ...f, restricted_merchants: e.target.value }))
              }
              placeholder="bar, nightclub"
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="notes">Notes (LLM context)</Label>
            <Textarea
              id="notes"
              value={form.notes}
              onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))}
              placeholder="Team meals exempt up to $1,000..."
            />
          </div>
          <DialogFooter>
            <Button type="submit" disabled={loading}>
              {loading ? "Saving..." : "Add rule"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

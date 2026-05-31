"use client";

import { useState } from "react";
import {
  CheckCircleIcon,
  FlaskIcon,
  WarningIcon,
} from "@phosphor-icons/react";
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
import { Badge } from "@/components/ui/badge";
import {
  createMockTransaction,
  type MockTransactionResult,
} from "@/lib/api/transactions";

// Friendly merchant types -> a representative MCC the compliance engine maps to a
// Brim spend category. Lets the demo pick a category without knowing MCC codes.
const MERCHANT_PRESETS: { label: string; mcc: string }[] = [
  { label: "Restaurant / client meal", mcc: "5812" },
  { label: "Fast food / solo meal", mcc: "5814" },
  { label: "Bar / alcohol", mcc: "5813" },
  { label: "Groceries (personal)", mcc: "5411" },
  { label: "Airline / travel", mcc: "4511" },
  { label: "Hotel / lodging", mcc: "7011" },
  { label: "Software / IT", mcc: "5734" },
  { label: "Fuel / gas", mcc: "5541" },
  { label: "Office supplies", mcc: "5943" },
  { label: "Other", mcc: "5999" },
];

const emptyForm = {
  amount: "",
  merchant_name: "",
  mcc: MERCHANT_PRESETS[0].mcc,
  city: "",
  date: new Date().toISOString().slice(0, 10),
};

function weightTone(weight: number) {
  if (weight >= 4) return "bg-red-500/15 text-red-600 dark:text-red-400";
  if (weight >= 3) return "bg-amber-500/15 text-amber-600 dark:text-amber-400";
  return "bg-muted text-muted-foreground";
}

export function CreateMockTransactionDialog({
  onResult,
}: {
  onResult?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [form, setForm] = useState(emptyForm);
  const [result, setResult] = useState<MockTransactionResult | null>(null);

  const reset = () => {
    setForm(emptyForm);
    setResult(null);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const amount = parseFloat(form.amount);
    if (Number.isNaN(amount) || amount <= 0) {
      toast.error("Enter a valid amount");
      return;
    }
    if (!form.merchant_name.trim()) {
      toast.error("Merchant name is required");
      return;
    }
    setLoading(true);
    try {
      const res = await createMockTransaction({
        amount,
        merchant_name: form.merchant_name.trim(),
        merchant_category: form.mcc,
        city: form.city.trim() || undefined,
        date: form.date || undefined,
      });
      setResult(res);
      onResult?.();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to run transaction");
    } finally {
      setLoading(false);
    }
  };

  const pass = result?.verdict === "auto_pass";

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        setOpen(o);
        if (!o) reset();
      }}
    >
      <DialogTrigger asChild>
        <Button>
          <FlaskIcon data-icon="inline-start" />
          Test a transaction
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[90vh] max-w-lg overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Test a card transaction</DialogTitle>
          <DialogDescription>
            Run a mock charge through the live policy engine and see instantly
            whether it auto-passes or gets routed to the finance approver.
          </DialogDescription>
        </DialogHeader>

        {!result ? (
          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <div className="grid grid-cols-2 gap-3">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="mock_amount">Amount (CAD)</Label>
                <Input
                  id="mock_amount"
                  type="number"
                  min="0"
                  step="0.01"
                  value={form.amount}
                  onChange={(e) => setForm((f) => ({ ...f, amount: e.target.value }))}
                  placeholder="1500"
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="mock_date">Date</Label>
                <Input
                  id="mock_date"
                  type="date"
                  value={form.date}
                  onChange={(e) => setForm((f) => ({ ...f, date: e.target.value }))}
                />
              </div>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="mock_merchant">Merchant</Label>
              <Input
                id="mock_merchant"
                value={form.merchant_name}
                onChange={(e) =>
                  setForm((f) => ({ ...f, merchant_name: e.target.value }))
                }
                placeholder="TechConf Registration"
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="mock_type">Merchant type</Label>
                <select
                  id="mock_type"
                  value={form.mcc}
                  onChange={(e) => setForm((f) => ({ ...f, mcc: e.target.value }))}
                  className="flex h-9 min-w-0 rounded-md border border-input bg-transparent px-2 text-sm"
                >
                  {MERCHANT_PRESETS.map((p) => (
                    <option key={p.mcc} value={p.mcc}>
                      {p.label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="mock_city">City</Label>
                <Input
                  id="mock_city"
                  value={form.city}
                  onChange={(e) => setForm((f) => ({ ...f, city: e.target.value }))}
                  placeholder="San Diego"
                />
              </div>
            </div>
            <DialogFooter>
              <Button type="submit" disabled={loading}>
                {loading ? "Running…" : "Run through policy engine"}
              </Button>
            </DialogFooter>
          </form>
        ) : (
          <div className="flex flex-col gap-4">
            <div
              className={`flex items-start gap-3 rounded-lg border p-4 ${
                pass
                  ? "border-emerald-500/30 bg-emerald-500/10"
                  : "border-amber-500/30 bg-amber-500/10"
              }`}
            >
              {pass ? (
                <CheckCircleIcon className="mt-0.5 size-5 shrink-0 text-emerald-600 dark:text-emerald-400" />
              ) : (
                <WarningIcon className="mt-0.5 size-5 shrink-0 text-amber-600 dark:text-amber-400" />
              )}
              <div className="flex flex-col gap-1">
                <p className="text-sm font-medium text-foreground">
                  {pass ? "Auto-approved" : "Needs finance approval"}
                </p>
                <p className="text-sm text-muted-foreground">{result.summary}</p>
              </div>
            </div>

            <div className="rounded-lg border p-3 text-sm">
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">
                  {result.transaction.merchant_name} · {result.transaction.brim_category}
                </span>
                <span className="font-medium">
                  ${result.transaction.amount.toLocaleString()} CAD
                </span>
              </div>
              <div className="mt-1 text-xs text-muted-foreground">
                {result.transaction.employee_name}
                {result.transaction.city ? ` · ${result.transaction.city}` : ""} ·
                approval threshold ${result.threshold_cad.toLocaleString()}
              </div>
            </div>

            <div className="flex flex-col gap-2">
              <p className="text-sm font-medium text-foreground">
                Compliance flags ({result.flags.length})
              </p>
              {result.flags.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No policy violations detected.
                </p>
              ) : (
                <ul className="flex flex-col gap-2">
                  {result.flags.map((f, i) => (
                    <li
                      key={i}
                      className="flex items-start gap-2 rounded-md border p-2.5 text-sm"
                    >
                      <Badge className={`shrink-0 ${weightTone(f.weight)}`}>
                        sev {f.weight}
                      </Badge>
                      <div className="flex flex-col">
                        <span className="text-foreground">{f.warning_message}</span>
                        {f.policy_name ? (
                          <span className="text-xs text-muted-foreground">
                            {f.policy_name}
                          </span>
                        ) : null}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <DialogFooter>
              <Button variant="outline" onClick={reset}>
                Test another
              </Button>
            </DialogFooter>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

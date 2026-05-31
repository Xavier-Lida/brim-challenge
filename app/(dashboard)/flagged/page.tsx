"use client";

import { useMemo, useState } from "react";
import { MagnifyingGlassIcon, ScanIcon } from "@phosphor-icons/react";
import { toast } from "sonner";
import { FlagRow } from "@/components/flagged/flag-row";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useMockStore } from "@/lib/hooks/use-mock-store";
import { getSeverityCounts } from "@/lib/flags/severity";
import type { TransactionFlag } from "@/lib/types/brim";

function matchesQuery(flag: TransactionFlag, query: string): boolean {
  const q = query.toLowerCase().trim();
  if (!q) return true;
  const txn = flag.transaction;
  return (
    (flag.employee_name ?? "").toLowerCase().includes(q) ||
    (txn?.employee_name ?? "").toLowerCase().includes(q) ||
    (txn?.merchant_name ?? "").toLowerCase().includes(q) ||
    (flag.policy_name ?? "").toLowerCase().includes(q)
  );
}

export default function FlaggedPage() {
  const {
    flags,
    flagsHasMore,
    flagsLoading,
    flagsLoadingMore,
    analyzeForFlags,
    loadMoreFlags,
    error,
    refreshAll,
  } = useMockStore();
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [analyzeProgress, setAnalyzeProgress] = useState<{
    current: number;
    total: number;
  } | null>(null);
  const [query, setQuery] = useState("");

  const sorted = useMemo(
    () => [...flags].sort((a, b) => b.weight - a.weight),
    [flags]
  );
  const severityCounts = useMemo(() => getSeverityCounts(sorted), [sorted]);
  const visible = useMemo(
    () => sorted.filter((f) => matchesQuery(f, query)),
    [sorted, query]
  );

  const handleAnalyze = async () => {
    setIsAnalyzing(true);
    setAnalyzeProgress(null);
    try {
      const { flagsFound } = await analyzeForFlags((progress) => {
        setAnalyzeProgress({ current: progress.current, total: progress.total });
      });
      if (flagsFound > 0) {
        toast.success(`Analysis complete — ${flagsFound} flag(s) created`);
      } else {
        toast.success("Analysis complete — no violations found");
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to analyze transactions");
    } finally {
      setIsAnalyzing(false);
      setAnalyzeProgress(null);
    }
  };

  const progressLabel =
    analyzeProgress && analyzeProgress.total > 0
      ? `Analyzing employee ${analyzeProgress.current} of ${analyzeProgress.total}…`
      : isAnalyzing
        ? "Starting analysis…"
        : null;

  const showEmptyAnalyzeCta =
    visible.length === 0 &&
    !query.trim() &&
    !flagsLoading &&
    !isAnalyzing;

  if (error && flags.length === 0 && !flagsLoading) {
    return (
      <div className="mx-auto flex max-w-3xl flex-col items-center gap-4 py-8">
        <p className="text-sm text-destructive">{error}</p>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={() => void refreshAll()}>
            Retry
          </Button>
          <Button onClick={() => void handleAnalyze()} disabled={isAnalyzing}>
            <ScanIcon className="size-4" />
            Analyze anyway
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-normal text-foreground/90">
            Flagged transactions
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            {progressLabel ??
              (flagsLoading && flags.length === 0
                ? "Loading flags…"
                : `${flags.length} flag${flags.length !== 1 ? "s" : ""}${
                    flagsHasMore ? " · more available" : ""
                  }`)}
          </p>
        </div>
        <Button onClick={() => void handleAnalyze()} disabled={isAnalyzing}>
          <ScanIcon className="size-4" />
          {isAnalyzing ? "Analyzing…" : "Analyze"}
        </Button>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <SeverityCounter label="High" count={severityCounts.high} dotClass="bg-red-600" />
        <SeverityCounter label="Medium" count={severityCounts.medium} dotClass="bg-orange-500" />
        <SeverityCounter label="Low" count={severityCounts.low} dotClass="bg-muted-foreground/40" />
      </div>

      <div className="relative min-w-0">
        <MagnifyingGlassIcon className="absolute top-1/2 left-2.5 -translate-y-1/2 text-muted-foreground" />
        <Input
          placeholder="Search by employee, merchant, or policy…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="border-border/60 bg-muted/50 pl-8"
          disabled={isAnalyzing}
        />
      </div>

      <div className="flex flex-col gap-2">
        {flagsLoading && flags.length === 0 && (
          <p className="py-8 text-center text-sm text-muted-foreground">
            Loading flags…
          </p>
        )}
        {visible.map((flag) => (
          <FlagRow key={flag.id} flag={flag} />
        ))}
        {visible.length === 0 && !showEmptyAnalyzeCta && (
          <p className="py-8 text-center text-sm text-muted-foreground">
            {query.trim()
              ? `No flags match "${query.trim()}".`
              : "No flagged transactions."}
          </p>
        )}
        {showEmptyAnalyzeCta && (
          <div className="flex flex-col items-center justify-center gap-4 rounded-xl border border-dashed border-border/60 bg-card/50 px-6 py-12 text-center">
            <p className="text-sm text-muted-foreground">
              No flagged transactions yet. Run analysis to scan expenses against your
              policy and create flags when violations are found.
            </p>
            <Button onClick={() => void handleAnalyze()} disabled={isAnalyzing}>
              <ScanIcon className="size-4" />
              {isAnalyzing ? "Analyzing…" : "Analyze"}
            </Button>
          </div>
        )}
      </div>

      {flagsHasMore && (
        <div className="flex justify-center pb-4">
          <Button
            variant="outline"
            onClick={() => void loadMoreFlags()}
            disabled={flagsLoadingMore || isAnalyzing}
          >
            {flagsLoadingMore ? "Loading…" : "Load more"}
          </Button>
        </div>
      )}
    </div>
  );
}

function SeverityCounter({
  label,
  count,
  dotClass,
}: {
  label: string;
  count: number;
  dotClass: string;
}) {
  return (
    <div className="flex items-center gap-1.5 rounded-full border border-border/60 px-2.5 py-1 text-xs text-muted-foreground">
      <span className={`size-2 rounded-full ${dotClass}`} />
      <span className="font-medium text-foreground">{count}</span>
      {label}
    </div>
  );
}

"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { PurchaseMapSection } from "@/components/reports/purchase-map/purchase-map-section";
import { ReportCard } from "@/components/reports/report-card";
import { ReportsLegend } from "@/components/reports/reports-legend";
import { Button } from "@/components/ui/button";
import { useMockStore } from "@/lib/hooks/use-mock-store";

export default function ReportsPage() {
  const {
    reports,
    reportsHasMore,
    reportsLoading,
    reportsLoadingMore,
    reportsTotalCount,
    generateReports,
    loadReports,
    loadMoreReports,
  } = useMockStore();
  const [isGenerating, setIsGenerating] = useState(false);
  const [showLegend, setShowLegend] = useState(false);

  useEffect(() => {
    if (reports.length === 0 && !reportsLoading) {
      void loadReports();
    }
  }, [reports.length, reportsLoading, loadReports]);

  const handleGenerate = async () => {
    setIsGenerating(true);
    try {
      await generateReports();
      toast.success("Reports generated");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to generate reports");
    } finally {
      setIsGenerating(false);
    }
  };

  const reportsSubtitle = (() => {
    const loaded = `Showing ${reports.length} loaded report${reports.length !== 1 ? "s" : ""}`;
    const total =
      reportsTotalCount != null ? ` of ${reportsTotalCount}` : "";
    const more = reportsHasMore ? " · more available" : "";
    return `${loaded}${total}${more} · AI recommendations included`;
  })();

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6">
      <PurchaseMapSection />

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-normal text-foreground/90">Expense reports</h2>
          <p className="mt-1 text-sm text-muted-foreground">{reportsSubtitle}</p>
          <button
            type="button"
            onClick={() => setShowLegend((prev) => !prev)}
            aria-expanded={showLegend}
            className="mt-1 text-xs font-medium text-primary/80 hover:underline"
          >
            {showLegend ? "Hide" : "What do these labels mean?"}
          </button>
        </div>
        <Button onClick={() => void handleGenerate()} disabled={isGenerating}>
          {isGenerating ? "Generating…" : "Generate reports"}
        </Button>
      </div>

      {showLegend && <ReportsLegend />}

      {reportsLoading && reports.length === 0 ? (
        <p className="py-8 text-center text-sm text-muted-foreground">Loading reports…</p>
      ) : (
        <div className="flex flex-col gap-4">
          {reports.map((report) => (
            <ReportCard key={report.id} report={report} />
          ))}
          {reports.length === 0 && (
            <p className="py-8 text-center text-sm text-muted-foreground">
              No expense reports yet. Generate reports from unassigned transactions.
            </p>
          )}
        </div>
      )}

      {reportsHasMore && (
        <div className="flex justify-center pb-4">
          <Button
            variant="outline"
            onClick={() => void loadMoreReports()}
            disabled={reportsLoadingMore}
          >
            {reportsLoadingMore ? "Loading…" : "Load more"}
          </Button>
        </div>
      )}
    </div>
  );
}

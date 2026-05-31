"use client";

import { useState } from "react";
import { toast } from "sonner";
import { ApprovalDeck } from "@/components/approvals/approval-deck";
import { Button } from "@/components/ui/button";
import { useMockStore } from "@/lib/hooks/use-mock-store";

export default function ApprovalsPage() {
  const {
    approvals,
    approvalsHasMore,
    approvalsLoading,
    approvalsLoadingMore,
    pendingApprovalsCount,
    decideApproval,
    runApprovalsPipeline,
    loadMoreApprovals,
    error,
    refreshAll,
  } = useMockStore();
  const [submittingId, setSubmittingId] = useState<string | null>(null);
  const [isRunningPipeline, setIsRunningPipeline] = useState(false);

  const handleDecide = async (id: string, status: "approved" | "denied") => {
    setSubmittingId(id);
    try {
      await decideApproval(id, status);
      toast.success(status === "approved" ? "Expense approved" : "Expense denied");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to update approval");
    } finally {
      setSubmittingId(null);
    }
  };

  const handleRunPipeline = async () => {
    setIsRunningPipeline(true);
    try {
      await runApprovalsPipeline();
      toast.success("Approval pipeline completed");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to run pipeline");
    } finally {
      setIsRunningPipeline(false);
    }
  };

  if (error && approvals.length === 0 && !approvalsLoading) {
    return (
      <div className="mx-auto flex max-w-lg flex-col items-center gap-4 py-8">
        <p className="text-sm text-destructive">{error}</p>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={() => void refreshAll()}>
            Retry
          </Button>
          <Button onClick={() => void handleRunPipeline()} disabled={isRunningPipeline}>
            {isRunningPipeline ? "Running…" : "Run approval pipeline"}
          </Button>
        </div>
      </div>
    );
  }

  const showEmptyPipelineCta =
    approvals.length === 0 && !approvalsLoading && !isRunningPipeline;

  return (
    <div className="mx-auto flex max-w-lg flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-normal text-foreground/90">Approvals</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            {approvalsLoading && approvals.length === 0
              ? "Loading approvals…"
              : `${pendingApprovalsCount} pending total`}
          </p>
        </div>
        <Button
          variant="outline"
          onClick={() => void handleRunPipeline()}
          disabled={isRunningPipeline || approvalsLoading}
        >
          {isRunningPipeline ? "Running…" : "Run approval pipeline"}
        </Button>
      </div>

      {approvalsLoading && approvals.length === 0 ? (
        <p className="py-8 text-center text-sm text-muted-foreground">
          Loading approvals…
        </p>
      ) : isRunningPipeline && approvals.length === 0 ? (
        <p className="py-8 text-center text-sm text-muted-foreground">
          Generating approval requests from flags…
        </p>
      ) : showEmptyPipelineCta ? (
        <div className="flex flex-col items-center justify-center gap-4 rounded-xl border border-dashed border-border/60 bg-card/50 px-6 py-16 text-center">
          <p className="text-lg font-medium text-foreground/90">No approvals yet</p>
          <p className="max-w-sm text-sm text-muted-foreground">
            After analyzing flagged transactions, run the approval pipeline to generate
            review requests from policy violations.
          </p>
          <Button onClick={() => void handleRunPipeline()} disabled={isRunningPipeline}>
            {isRunningPipeline ? "Running…" : "Run approval pipeline"}
          </Button>
        </div>
      ) : (
        <ApprovalDeck
          approvals={approvals}
          onDecide={handleDecide}
          isSubmitting={submittingId !== null}
        />
      )}

      {approvalsHasMore && (
        <div className="flex justify-center pb-4">
          <Button
            variant="outline"
            onClick={() => void loadMoreApprovals()}
            disabled={approvalsLoadingMore}
          >
            {approvalsLoadingMore ? "Loading…" : "Load more"}
          </Button>
        </div>
      )}
    </div>
  );
}

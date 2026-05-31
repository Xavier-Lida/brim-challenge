"use client";

import { useState } from "react";
import {
  CaretDownIcon,
  DownloadSimpleIcon,
  SpinnerIcon,
} from "@phosphor-icons/react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { downloadReportPdf } from "@/lib/api/reports";
import {
  formatReportAmount,
  getReportStatusMeta,
  REPORT_AI_META,
} from "@/lib/reports/display";
import { cn } from "@/lib/utils";
import type { ExpenseReport } from "@/lib/types/brim";

type ReportCardProps = {
  report: ExpenseReport;
};

export function ReportCard({ report }: ReportCardProps) {
  const [isExporting, setIsExporting] = useState(false);
  const [showTransactions, setShowTransactions] = useState(false);

  const ai = REPORT_AI_META[report.ai_recommendation];
  const status = getReportStatusMeta(report.status);
  const transactions = report.transactions ?? [];
  const transactionCount = report.transaction_count ?? transactions.length;

  const subtitleParts = [`${report.date_from} – ${report.date_to}`];
  if (transactionCount > 0) {
    subtitleParts.push(
      `${transactionCount} transaction${transactionCount !== 1 ? "s" : ""}`
    );
  }

  const handleExport = async () => {
    setIsExporting(true);
    try {
      await downloadReportPdf(report);
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Failed to export the PDF"
      );
    } finally {
      setIsExporting(false);
    }
  };

  return (
    <TooltipProvider delayDuration={200}>
      <Card className="border-border/50 shadow-none">
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <CardTitle className="text-base font-medium">
                {report.title}
              </CardTitle>
              {(report.employee_name || report.department_name) && (
                <p className="mt-0.5 text-sm text-foreground/80">
                  {report.employee_name}
                  {report.employee_name && report.department_name ? " · " : ""}
                  {report.department_name}
                </p>
              )}
              <CardDescription>{subtitleParts.join(" · ")}</CardDescription>
            </div>
            <div className="flex flex-col items-end gap-2">
              <span className="text-lg font-semibold tabular-nums">
                {formatReportAmount(report.total_amount, report.currency)}
              </span>
              <div className="flex flex-wrap items-center justify-end gap-2">
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Badge
                      variant={
                        report.ai_recommendation === "deny"
                          ? "destructive"
                          : "secondary"
                      }
                      className={cn(
                        "cursor-help",
                        report.ai_recommendation === "approve" &&
                          "border border-primary/20 bg-blue-soft text-primary/80"
                      )}
                    >
                      AI: {ai.label}
                    </Badge>
                  </TooltipTrigger>
                  <TooltipContent side="bottom" className="max-w-xs text-wrap">
                    {ai.description}
                  </TooltipContent>
                </Tooltip>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Badge variant={status.badgeVariant} className="cursor-help">
                      {status.label}
                    </Badge>
                  </TooltipTrigger>
                  <TooltipContent side="bottom" className="max-w-xs text-wrap">
                    {status.description}
                  </TooltipContent>
                </Tooltip>
              </div>
            </div>
          </div>
        </CardHeader>

        <CardContent className="flex flex-col gap-3">
          <div>
            <p className="text-xs font-medium text-muted-foreground">
              AI recommendation — {ai.action}
            </p>
            <p className="mt-1 text-sm text-muted-foreground">
              {report.ai_reasoning}
            </p>
          </div>

          {transactions.length > 0 && (
            <div>
              <button
                type="button"
                onClick={() => setShowTransactions((prev) => !prev)}
                aria-expanded={showTransactions}
                className="flex items-center gap-1 text-xs font-medium text-foreground/70 hover:text-foreground"
              >
                <CaretDownIcon
                  className={cn(
                    "size-3 transition-transform",
                    showTransactions && "rotate-180"
                  )}
                />
                {showTransactions ? "Hide" : "Show"} {transactions.length}{" "}
                transaction{transactions.length !== 1 ? "s" : ""}
              </button>
              {showTransactions && (
                <div className="mt-2 rounded-none border border-border/50">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Date</TableHead>
                        <TableHead>Merchant</TableHead>
                        <TableHead>Category</TableHead>
                        <TableHead>City</TableHead>
                        <TableHead className="text-right">Amount</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {transactions.map((txn, index) => (
                        <TableRow key={`${txn.date}-${txn.merchant_name}-${index}`}>
                          <TableCell>{txn.date}</TableCell>
                          <TableCell>{txn.merchant_name}</TableCell>
                          <TableCell>{txn.merchant_category}</TableCell>
                          <TableCell>{txn.city}</TableCell>
                          <TableCell className="text-right tabular-nums">
                            {formatReportAmount(txn.amount, report.currency)}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
            </div>
          )}
        </CardContent>

        <CardFooter>
          <Button
            variant="outline"
            size="sm"
            onClick={() => void handleExport()}
            disabled={isExporting}
          >
            {isExporting ? (
              <SpinnerIcon className="size-4 animate-spin" />
            ) : (
              <DownloadSimpleIcon className="size-4" />
            )}
            {isExporting ? "Exporting…" : "Export PDF"}
          </Button>
        </CardFooter>
      </Card>
    </TooltipProvider>
  );
}

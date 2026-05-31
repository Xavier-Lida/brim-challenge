"use client";

import { useState } from "react";
import { UploadIcon } from "@phosphor-icons/react";
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
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useMockStore } from "@/lib/hooks/use-mock-store";
import type { PolicyImportDraft } from "@/lib/types/brim";
import { fileToBase64 } from "@/lib/utils/pdf";

export function ImportPolicyDialog() {
  const { analyzeImport, importPolicies } = useMockStore();
  const [open, setOpen] = useState(false);
  const [step, setStep] = useState<"upload" | "preview">("upload");
  const [content, setContent] = useState("");
  const [pdfBase64, setPdfBase64] = useState<string | null>(null);
  const [pdfFileName, setPdfFileName] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<PolicyImportDraft[]>([]);
  const [loading, setLoading] = useState(false);

  const reset = () => {
    setStep("upload");
    setContent("");
    setPdfBase64(null);
    setPdfFileName(null);
    setDrafts([]);
    setLoading(false);
  };

  const canAnalyze = Boolean(pdfBase64 || content.trim());

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (file.type !== "application/pdf" && !file.name.toLowerCase().endsWith(".pdf")) {
      toast.error("Please select a PDF file");
      return;
    }
    try {
      const base64 = await fileToBase64(file);
      setPdfBase64(base64);
      setPdfFileName(file.name);
      setContent("");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to read PDF");
    }
  };

  const handleAnalyze = async () => {
    if (!canAnalyze) {
      toast.error("Upload a PDF or paste policy text first");
      return;
    }
    setLoading(true);
    try {
      const result = pdfBase64
        ? await analyzeImport({ pdf_base64: pdfBase64 })
        : await analyzeImport({ content: content.trim() });
      setDrafts(result);
      setStep("preview");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Import analysis failed");
    } finally {
      setLoading(false);
    }
  };

  const handleConfirm = async () => {
    setLoading(true);
    try {
      await importPolicies(drafts);
      toast.success(`${drafts.length} rules imported`);
      setOpen(false);
      reset();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Import failed");
    } finally {
      setLoading(false);
    }
  };

  const updateDraftName = (index: number, policy_name: string) => {
    setDrafts((prev) =>
      prev.map((d, i) => (i === index ? { ...d, policy_name } : d))
    );
  };

  const formatRequirements = (draft: PolicyImportDraft) => {
    const req = draft.policy_requirements;
    const parts: string[] = [];
    if (req.approval_threshold_cad != null) {
      parts.push(`Threshold: $${req.approval_threshold_cad}`);
    }
    const limits = Object.entries(req.category_limits_cad ?? {});
    if (limits.length > 0) {
      parts.push(
        limits.map(([cat, amt]) => `${cat}: $${amt}`).join("; ")
      );
    }
    if (req.notes) parts.push(req.notes.slice(0, 80));
    return parts.join(" · ") || "—";
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        setOpen(v);
        if (!v) reset();
      }}
    >
      <DialogTrigger asChild>
        <Button>
          <UploadIcon data-icon="inline-start" />
          Import policy
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Import expense policy</DialogTitle>
          <DialogDescription>
            Upload a PDF or paste policy text. Brim extracts structured JSONB
            rules for your review before saving to Supabase.
          </DialogDescription>
        </DialogHeader>

        {step === "upload" ? (
          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="policy-file">PDF upload</Label>
              <Input
                id="policy-file"
                type="file"
                accept=".pdf,application/pdf"
                onChange={handleFileChange}
              />
              {pdfFileName && (
                <p className="text-xs text-muted-foreground">
                  Selected: {pdfFileName}
                </p>
              )}
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="policy-text">Or paste policy text</Label>
              <Textarea
                id="policy-text"
                value={content}
                onChange={(e) => {
                  setContent(e.target.value);
                  if (e.target.value.trim()) {
                    setPdfBase64(null);
                    setPdfFileName(null);
                  }
                }}
                placeholder="Paste your expense policy document here..."
                rows={6}
                disabled={Boolean(pdfBase64)}
              />
            </div>
            <DialogFooter>
              <Button onClick={handleAnalyze} disabled={loading || !canAnalyze}>
                {loading ? "Analyzing..." : "Analyze with AI"}
              </Button>
            </DialogFooter>
          </div>
        ) : (
          <div className="flex min-w-0 flex-col gap-4">
            <p className="text-sm text-muted-foreground">
              Review extracted rules before confirming import.
            </p>
            <div className="min-w-0 max-h-64 overflow-y-auto rounded-md border border-border">
              <Table className="table-fixed w-full">
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-[35%]">Rule name</TableHead>
                    <TableHead className="w-[45%]">Requirements</TableHead>
                    <TableHead className="w-[20%]">Effective</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {drafts.map((draft, i) => (
                    <TableRow key={i}>
                      <TableCell className="min-w-0">
                        <Input
                          value={draft.policy_name}
                          onChange={(e) => updateDraftName(i, e.target.value)}
                          className="h-8"
                        />
                      </TableCell>
                      <TableCell className="whitespace-normal break-words text-xs text-muted-foreground line-clamp-3">
                        {formatRequirements(draft)}
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-sm">
                        {draft.effective_date}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
            <DialogFooter className="gap-2 sm:gap-0">
              <Button variant="outline" onClick={() => setStep("upload")}>
                Back
              </Button>
              <Button onClick={handleConfirm} disabled={loading}>
                {loading ? "Importing..." : `Confirm import (${drafts.length})`}
              </Button>
            </DialogFooter>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

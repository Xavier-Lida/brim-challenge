"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { ApprovalRequest } from "@/lib/types/brim";

function pendingOnly(approvals: ApprovalRequest[]): ApprovalRequest[] {
  return approvals.filter((a) => a.status === "pending");
}

export function useApprovalQueue(approvals: ApprovalRequest[]) {
  const pending = useMemo(() => pendingOnly(approvals), [approvals]);
  const [queue, setQueue] = useState<ApprovalRequest[]>([]);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    setQueue((prev) => {
      const pendingMap = new Map(pending.map((a) => [a.id, a]));
      const next = prev
        .filter((a) => pendingMap.has(a.id))
        .map((a) => pendingMap.get(a.id)!);
      const inQueue = new Set(next.map((a) => a.id));
      for (const a of pending) {
        if (!inQueue.has(a.id)) next.push(a);
      }
      if (next.length === 0 && pending.length > 0) return pending;
      return next;
    });
  }, [pending]);

  useEffect(() => {
    setExpanded(false);
  }, [queue[0]?.id]);

  const current = queue[0] ?? null;
  const queueSize = queue.length;

  const skip = useCallback(() => {
    setQueue((prev) => {
      if (prev.length <= 1) return prev;
      const [head, ...rest] = prev;
      return [...rest, head];
    });
  }, []);

  const removeCurrent = useCallback(() => {
    setQueue((prev) => prev.slice(1));
  }, []);

  return {
    current,
    queueSize,
    position: queueSize > 0 ? 1 : 0,
    skip,
    removeCurrent,
    expanded,
    setExpanded,
  };
}

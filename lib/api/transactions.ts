import { apiFetch } from "@/lib/api/client";
import type { Transaction } from "@/lib/types/brim";

export const TRANSACTIONS_PAGE_SIZE = 30;

export type TransactionsPage = {
  items: Transaction[];
  has_more: boolean;
  limit: number;
  offset: number;
};

export function getTransactions(params?: {
  limit?: number;
  offset?: number;
}) {
  return apiFetch<TransactionsPage>("/api/transactions", {
    params: {
      limit: params?.limit ?? TRANSACTIONS_PAGE_SIZE,
      offset: params?.offset ?? 0,
    },
  });
}

// ---- Mock transaction injector (demo: "what happens if I run this card charge?") ----

export type MockTransactionInput = {
  amount: number;
  merchant_name: string;
  merchant_category: string; // MCC code, e.g. "5812"
  city?: string;
  date?: string;
  employee_id?: string;
};

export type MockTransactionFlag = {
  warning_message: string;
  weight: number;
  policy_name: string | null;
};

export type MockTransactionResult = {
  transaction: {
    id: string;
    employee_id: string;
    employee_name: string;
    date: string;
    amount: number;
    merchant_name: string;
    merchant_category: string;
    brim_category: string;
    city: string | null;
    status: string;
  };
  flags: MockTransactionFlag[];
  needs_approval: boolean;
  verdict: "needs_approval" | "auto_pass";
  over_threshold: boolean;
  threshold_cad: number;
  summary: string;
};

export function createMockTransaction(input: MockTransactionInput) {
  return apiFetch<MockTransactionResult>("/api/transactions/mock", {
    method: "POST",
    body: input,
  });
}

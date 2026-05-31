"use client";

import { useEffect, useMemo } from "react";
import { TransactionsTable, TransactionsTableSkeleton } from "@/components/transactions/transactions-table";
import { CreateMockTransactionDialog } from "@/components/transactions/create-mock-transaction-dialog";
import { Button } from "@/components/ui/button";
import { useMockStore } from "@/lib/hooks/use-mock-store";

export default function TransactionsPage() {
  const {
    transactions,
    transactionsHasMore,
    transactionsLoading,
    transactionsLoadingMore,
    searchQuery,
    loadTransactions,
    loadMoreTransactions,
  } = useMockStore();

  useEffect(() => {
    if (transactions.length === 0 && !transactionsLoading) {
      void loadTransactions();
    }
  }, [transactions.length, transactionsLoading, loadTransactions]);

  const filtered = useMemo(() => {
    const q = searchQuery.toLowerCase().trim();
    if (!q) return transactions;
    return transactions.filter(
      (t) =>
        t.employee_name.toLowerCase().includes(q) ||
        t.merchant_name.toLowerCase().includes(q) ||
        t.city.toLowerCase().includes(q) ||
        t.merchant_category.toLowerCase().includes(q)
    );
  }, [transactions, searchQuery]);

  if (transactionsLoading && transactions.length === 0) {
    return <TransactionsTableSkeleton />;
  }

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-xl font-normal text-foreground/90">Transactions</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Showing {filtered.length} loaded transaction
            {filtered.length !== 1 ? "s" : ""}
            {searchQuery ? ` matching "${searchQuery}"` : ""}
            {!searchQuery && transactionsHasMore ? " · more available" : ""}
          </p>
        </div>
        <CreateMockTransactionDialog onResult={() => void loadTransactions()} />
      </div>
      <TransactionsTable transactions={filtered} />
      {transactionsHasMore && !searchQuery.trim() && (
        <div className="flex justify-center pb-4">
          <Button
            variant="outline"
            onClick={() => void loadMoreTransactions()}
            disabled={transactionsLoadingMore}
          >
            {transactionsLoadingMore ? "Loading…" : "Load more"}
          </Button>
        </div>
      )}
    </div>
  );
}

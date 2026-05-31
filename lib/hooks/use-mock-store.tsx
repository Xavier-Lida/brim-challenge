"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { askAssistantStream } from "@/lib/api/assistant-stream";
import { createAssistantStreamHandler } from "@/lib/hooks/assistant-stream-handler";
import {
  APPROVALS_PAGE_SIZE,
  decideApproval as decideApprovalApi,
  getApprovals,
  runApprovalsPipeline as runApprovalsPipelineApi,
} from "@/lib/api/approvals";
import { runComplianceScan as runComplianceScanApi } from "@/lib/api/compliance";
import { getEmployees } from "@/lib/api/employees";
import {
  FLAGS_PAGE_SIZE,
  getFlags,
} from "@/lib/api/flags";
import {
  getNotifications,
  markNotificationReadApi,
} from "@/lib/api/notifications";
import {
  confirmPolicyImport,
  createPolicy,
  deletePolicy as deletePolicyApi,
  getPolicies,
  importPoliciesPreview,
  updatePolicy,
} from "@/lib/api/policies";
import {
  generateReports as generateReportsApi,
  getReports,
  REPORTS_PAGE_SIZE,
} from "@/lib/api/reports";
import { getTransactions, TRANSACTIONS_PAGE_SIZE } from "@/lib/api/transactions";
import {
  companySpend,
  workspaceUser,
} from "@/lib/mocks/fixtures";
import { useAssistantSession } from "@/lib/hooks/use-assistant-session";
import { toast } from "sonner";
import type {
  ApprovalRequest,
  ApprovalStatus,
  AssistantMessage,
  AssistantSessionState,
  ExpenseReport,
  Notification,
  Policy,
  PolicyImportDraft,
  PolicyRequirements,
  Transaction,
  TransactionFlag,
  Visualization,
  VisualizationHistoryEntry,
} from "@/lib/types/brim";

type MockStore = {
  policies: Policy[];
  approvals: ApprovalRequest[];
  approvalsHasMore: boolean;
  approvalsLoading: boolean;
  approvalsLoadingMore: boolean;
  flags: TransactionFlag[];
  flagsHasMore: boolean;
  flagsLoading: boolean;
  flagsLoadingMore: boolean;
  transactions: Transaction[];
  transactionsHasMore: boolean;
  transactionsLoading: boolean;
  transactionsLoadingMore: boolean;
  reports: ExpenseReport[];
  reportsHasMore: boolean;
  reportsLoading: boolean;
  reportsLoadingMore: boolean;
  reportsTotalCount: number | null;
  notifications: Notification[];
  assistantMessages: AssistantMessage[];
  assistantSession: AssistantSessionState;
  assistantActiveVisualization?: Visualization;
  assistantVisualizationHistory: VisualizationHistoryEntry[];
  assistantIsSending: boolean;
  assistantVizFullscreenOpen: boolean;
  setAssistantVizFullscreenOpen: (open: boolean) => void;
  clearAssistantChat: () => void;
  selectAssistantVisualization: (messageId: string) => void;
  assistantLatestVisualization?: Visualization;
  searchQuery: string;
  companySpend: typeof companySpend;
  workspaceUser: typeof workspaceUser;
  isLoading: boolean;
  error: string | null;
  pendingApprovalsCount: number;
  unreadNotificationsCount: number;
  activePoliciesCount: number;
  setSearchQuery: (query: string) => void;
  loadTransactions: () => Promise<void>;
  loadMoreTransactions: () => Promise<void>;
  refreshTransactions: () => Promise<void>;
  loadFlags: () => Promise<void>;
  loadMoreFlags: () => Promise<void>;
  refreshFlags: () => Promise<void>;
  loadReports: () => Promise<void>;
  loadMoreReports: () => Promise<void>;
  loadApprovals: () => Promise<void>;
  loadMoreApprovals: () => Promise<void>;
  refreshApprovals: () => Promise<void>;
  refreshReports: () => Promise<void>;
  refreshPolicies: () => Promise<void>;
  refreshNotifications: () => Promise<void>;
  refreshAll: () => Promise<void>;
  togglePolicy: (id: string) => Promise<void>;
  deletePolicy: (id: string) => Promise<void>;
  addPolicy: (data: {
    policy_name: string;
    policy_requirements: PolicyRequirements;
    effective_date?: string;
  }) => Promise<void>;
  editPolicy: (
    id: string,
    data: Partial<{
      policy_name: string;
      policy_requirements: PolicyRequirements;
      effective_date: string;
      active: boolean;
    }>
  ) => Promise<void>;
  importPolicies: (drafts: PolicyImportDraft[]) => Promise<void>;
  analyzeImport: (input: {
    content?: string;
    pdf_base64?: string;
  }) => Promise<PolicyImportDraft[]>;
  decideApproval: (id: string, status: ApprovalStatus) => Promise<void>;
  markNotificationRead: (id: string) => Promise<void>;
  sendAssistantMessage: (text: string) => Promise<void>;
  runComplianceScan: () => Promise<void>;
  analyzeForFlags: (
    onProgress?: (progress: {
      current: number;
      total: number;
      flagsFound: number;
    }) => void
  ) => Promise<{ flagsFound: number; employeesScanned: number }>;
  runApprovalsPipeline: () => Promise<void>;
  generateReports: () => Promise<void>;
};

const MockStoreContext = createContext<MockStore | null>(null);

export function MockStoreProvider({ children }: { children: ReactNode }) {
  const [policies, setPolicies] = useState<Policy[]>([]);
  const [approvals, setApprovals] = useState<ApprovalRequest[]>([]);
  const approvalsRef = useRef<ApprovalRequest[]>([]);
  const [approvalsHasMore, setApprovalsHasMore] = useState(false);
  const [approvalsLoading, setApprovalsLoading] = useState(false);
  const [approvalsLoadingMore, setApprovalsLoadingMore] = useState(false);
  const [pendingApprovalsCount, setPendingApprovalsCount] = useState(0);
  const [flags, setFlags] = useState<TransactionFlag[]>([]);
  const flagsRef = useRef<TransactionFlag[]>([]);
  const [flagsHasMore, setFlagsHasMore] = useState(false);
  const [flagsLoading, setFlagsLoading] = useState(false);
  const [flagsLoadingMore, setFlagsLoadingMore] = useState(false);
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const transactionsRef = useRef<Transaction[]>([]);
  const [transactionsHasMore, setTransactionsHasMore] = useState(false);
  const [transactionsLoading, setTransactionsLoading] = useState(false);
  const [transactionsLoadingMore, setTransactionsLoadingMore] = useState(false);
  const [reports, setReports] = useState<ExpenseReport[]>([]);
  const reportsRef = useRef<ExpenseReport[]>([]);
  const [reportsHasMore, setReportsHasMore] = useState(false);
  const [reportsLoading, setReportsLoading] = useState(false);
  const [reportsLoadingMore, setReportsLoadingMore] = useState(false);
  const [reportsTotalCount, setReportsTotalCount] = useState<number | null>(null);
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const assistant = useAssistantSession();
  const [searchQuery, setSearchQuery] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    transactionsRef.current = transactions;
  }, [transactions]);

  useEffect(() => {
    flagsRef.current = flags;
  }, [flags]);

  useEffect(() => {
    reportsRef.current = reports;
  }, [reports]);

  useEffect(() => {
    approvalsRef.current = approvals;
  }, [approvals]);

  const mergeApprovals = useCallback(
    (prev: ApprovalRequest[], incoming: ApprovalRequest[]) => {
      const seen = new Set(prev.map((a) => a.id));
      const unique = incoming.filter((a) => !seen.has(a.id));
      return unique.length > 0 ? [...prev, ...unique] : prev;
    },
    []
  );

  const mergeFlags = useCallback(
    (prev: TransactionFlag[], incoming: TransactionFlag[]) => {
      const seen = new Set(prev.map((f) => f.id));
      const unique = incoming.filter((f) => !seen.has(f.id));
      return unique.length > 0 ? [...prev, ...unique] : prev;
    },
    []
  );

  const mergeReports = useCallback(
    (prev: ExpenseReport[], incoming: ExpenseReport[]) => {
      const seen = new Set(prev.map((r) => r.id));
      const unique = incoming.filter((r) => !seen.has(r.id));
      return unique.length > 0 ? [...prev, ...unique] : prev;
    },
    []
  );

  const mergeTransactions = useCallback(
    (prev: Transaction[], incoming: Transaction[]) => {
      const seen = new Set(prev.map((t) => t.id));
      const unique = incoming.filter((t) => !seen.has(t.id));
      return unique.length > 0 ? [...prev, ...unique] : prev;
    },
    []
  );

  const loadTransactions = useCallback(async () => {
    setTransactionsLoading(true);
    try {
      const page = await getTransactions({
        limit: TRANSACTIONS_PAGE_SIZE,
        offset: 0,
      });
      setTransactions(page.items);
      setTransactionsHasMore(page.has_more);
    } finally {
      setTransactionsLoading(false);
    }
  }, []);

  const loadMoreTransactions = useCallback(async () => {
    if (!transactionsHasMore || transactionsLoadingMore) return;
    setTransactionsLoadingMore(true);
    const offset = transactionsRef.current.length;
    try {
      const page = await getTransactions({
        limit: TRANSACTIONS_PAGE_SIZE,
        offset,
      });
      setTransactions((prev) => mergeTransactions(prev, page.items));
      setTransactionsHasMore(page.has_more);
    } finally {
      setTransactionsLoadingMore(false);
    }
  }, [transactionsHasMore, transactionsLoadingMore, mergeTransactions]);

  const refreshTransactions = loadTransactions;

  const loadFlags = useCallback(async () => {
    setFlagsLoading(true);
    try {
      const page = await getFlags({
        limit: FLAGS_PAGE_SIZE,
        offset: 0,
      });
      setFlags(page.items);
      setFlagsHasMore(page.has_more);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load flags");
    } finally {
      setFlagsLoading(false);
    }
  }, []);

  const loadMoreFlags = useCallback(async () => {
    if (!flagsHasMore || flagsLoadingMore) return;
    setFlagsLoadingMore(true);
    const offset = flagsRef.current.length;
    try {
      const page = await getFlags({
        limit: FLAGS_PAGE_SIZE,
        offset,
      });
      setFlags((prev) => mergeFlags(prev, page.items));
      setFlagsHasMore(page.has_more);
    } finally {
      setFlagsLoadingMore(false);
    }
  }, [flagsHasMore, flagsLoadingMore, mergeFlags]);

  const refreshFlags = loadFlags;

  const loadReports = useCallback(async () => {
    setReportsLoading(true);
    try {
      const page = await getReports({
        limit: REPORTS_PAGE_SIZE,
        offset: 0,
      });
      setReports(page.items);
      setReportsHasMore(page.has_more);
      setReportsTotalCount(
        typeof page.total_count === "number" ? page.total_count : null
      );
    } finally {
      setReportsLoading(false);
    }
  }, []);

  const loadMoreReports = useCallback(async () => {
    if (!reportsHasMore || reportsLoadingMore) return;
    setReportsLoadingMore(true);
    const offset = reportsRef.current.length;
    try {
      const page = await getReports({
        limit: REPORTS_PAGE_SIZE,
        offset,
      });
      setReports((prev) => mergeReports(prev, page.items));
      setReportsHasMore(page.has_more);
      if (typeof page.total_count === "number") {
        setReportsTotalCount(page.total_count);
      }
    } finally {
      setReportsLoadingMore(false);
    }
  }, [reportsHasMore, reportsLoadingMore, mergeReports]);

  const refreshReports = loadReports;

  const loadApprovals = useCallback(async () => {
    setApprovalsLoading(true);
    try {
      const page = await getApprovals({
        limit: APPROVALS_PAGE_SIZE,
        offset: 0,
      });
      setApprovals(page.items);
      setApprovalsHasMore(page.has_more);
      setPendingApprovalsCount(page.pending_count);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load approvals");
    } finally {
      setApprovalsLoading(false);
    }
  }, []);

  const loadMoreApprovals = useCallback(async () => {
    if (!approvalsHasMore || approvalsLoadingMore) return;
    setApprovalsLoadingMore(true);
    const offset = approvalsRef.current.length;
    try {
      const page = await getApprovals({
        limit: APPROVALS_PAGE_SIZE,
        offset,
      });
      setApprovals((prev) => mergeApprovals(prev, page.items));
      setApprovalsHasMore(page.has_more);
      setPendingApprovalsCount(page.pending_count);
    } finally {
      setApprovalsLoadingMore(false);
    }
  }, [approvalsHasMore, approvalsLoadingMore, mergeApprovals]);

  const refreshApprovals = loadApprovals;

  const refreshPolicies = useCallback(async () => {
    const data = await getPolicies();
    setPolicies(data);
  }, []);

  const refreshNotifications = useCallback(async () => {
    const data = await getNotifications();
    setNotifications(data);
  }, []);

  const refreshAll = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      await Promise.all([
        loadFlags(),
        loadApprovals(),
        refreshPolicies(),
        refreshNotifications(),
      ]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load data");
    } finally {
      setIsLoading(false);
    }
  }, [
    loadFlags,
    loadApprovals,
    refreshPolicies,
    refreshNotifications,
  ]);

  useEffect(() => {
    void refreshAll();
  }, [refreshAll]);

  const unreadNotificationsCount = useMemo(
    () => notifications.filter((n) => !n.read).length,
    [notifications]
  );

  const activePoliciesCount = useMemo(
    () => policies.filter((p) => p.active).length,
    [policies]
  );

  const afterPolicyChange = useCallback(async () => {
    await Promise.all([
      refreshFlags(),
      refreshTransactions(),
      refreshNotifications(),
    ]);
    toast.success("Rules updated — compliance rescan complete");
  }, [refreshFlags, refreshTransactions, refreshNotifications]);

  const togglePolicy = useCallback(
    async (id: string) => {
      const policy = policies.find((p) => p.id === id);
      if (!policy) return;
      const updated = await updatePolicy(id, { active: !policy.active });
      setPolicies((prev) =>
        prev.map((p) => (p.id === id ? { ...p, ...updated } : p))
      );
      await afterPolicyChange();
    },
    [policies, afterPolicyChange]
  );

  const deletePolicy = useCallback(async (id: string) => {
    await deletePolicyApi(id);
    setPolicies((prev) => prev.filter((p) => p.id !== id));
    await afterPolicyChange();
  }, [afterPolicyChange]);

  const addPolicy = useCallback(
    async (data: {
      policy_name: string;
      policy_requirements: PolicyRequirements;
      effective_date?: string;
    }) => {
      const created = await createPolicy(data);
      setPolicies((prev) => [created, ...prev]);
      await afterPolicyChange();
    },
    [afterPolicyChange]
  );

  const editPolicy = useCallback(
    async (
      id: string,
      data: Partial<{
        policy_name: string;
        policy_requirements: PolicyRequirements;
        effective_date: string;
        active: boolean;
      }>
    ) => {
      const updated = await updatePolicy(id, data);
      setPolicies((prev) => prev.map((p) => (p.id === id ? updated : p)));
      await afterPolicyChange();
    },
    [afterPolicyChange]
  );

  const importPolicies = useCallback(async (drafts: PolicyImportDraft[]) => {
    const result = await confirmPolicyImport(drafts);
    setPolicies((prev) => [...result.policies, ...prev]);
    await afterPolicyChange();
  }, [afterPolicyChange]);

  const analyzeImport = useCallback(
    async (input: { content?: string; pdf_base64?: string }) => {
      const result = await importPoliciesPreview(input);
      return result.policies;
    },
    []
  );

  const decideApproval = useCallback(
    async (id: string, status: ApprovalStatus) => {
      await decideApprovalApi(id, { status });
      await Promise.all([
        refreshApprovals(),
        refreshTransactions(),
        refreshNotifications(),
      ]);
    },
    [refreshApprovals, refreshTransactions, refreshNotifications]
  );

  const runComplianceScan = useCallback(async () => {
    await runComplianceScanApi();
    await Promise.all([
      refreshFlags(),
      refreshTransactions(),
      refreshNotifications(),
    ]);
  }, [refreshFlags, refreshTransactions, refreshNotifications]);

  const analyzeForFlags = useCallback(
    async (
      onProgress?: (progress: {
        current: number;
        total: number;
        flagsFound: number;
      }) => void
    ) => {
      const roster = await getEmployees();
      const queue = roster.filter((e) => e.map_transaction_count > 0);
      let flagsFound = 0;

      for (let i = 0; i < queue.length; i++) {
        const result = await runComplianceScanApi({ employee_id: queue[i].id });
        flagsFound += result.flag_count;
        await refreshFlags();
        onProgress?.({ current: i + 1, total: queue.length, flagsFound });
      }

      await Promise.all([refreshTransactions(), refreshNotifications()]);
      return { flagsFound, employeesScanned: queue.length };
    },
    [refreshFlags, refreshTransactions, refreshNotifications]
  );

  const runApprovalsPipeline = useCallback(async () => {
    await runApprovalsPipelineApi({ send: false });
    await Promise.all([refreshApprovals(), refreshNotifications()]);
  }, [refreshApprovals, refreshNotifications]);

  const generateReports = useCallback(async () => {
    await generateReportsApi({});
    await refreshReports();
  }, [refreshReports]);

  const markNotificationRead = useCallback(async (id: string) => {
    await markNotificationReadApi(id);
    setNotifications((prev) =>
      prev.map((n) => (n.id === id ? { ...n, read: true } : n))
    );
  }, []);

  const runAssistantStream = useCallback(
    async (
      assistantId: string,
      question: string,
      historyMessages: AssistantMessage[]
    ) => {
      const stream = createAssistantStreamHandler(
        assistantId,
        assistant.patchAssistantMessage
      );

      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 60000);

      try {
        await askAssistantStream(
          question,
          assistant.buildHistory(historyMessages),
          stream.handler,
          controller.signal
        );
      } catch {
        stream.setErrorText(
          stream.getAccumulated() ||
            "La requête a expiré. Réessayez ou reformulez votre question."
        );
      } finally {
        clearTimeout(timeout);
        stream.finalizeUnsettled();
      }
    },
    [assistant]
  );

  const sendAssistantMessage = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || assistant.isSending) return;

      assistant.setIsSending(true);
      const historyMessages = assistant.session.messages;
      assistant.appendUserMessage(trimmed);
      const assistantId = assistant.beginAssistantMessage({
        sourceQuestion: trimmed,
      });

      await runAssistantStream(assistantId, trimmed, historyMessages);
      assistant.setIsSending(false);
    },
    [assistant, runAssistantStream]
  );

  const value: MockStore = {
    policies,
    approvals,
    approvalsHasMore,
    approvalsLoading,
    approvalsLoadingMore,
    flags,
    flagsHasMore,
    flagsLoading,
    flagsLoadingMore,
    transactions,
    transactionsHasMore,
    transactionsLoading,
    transactionsLoadingMore,
    reports,
    reportsHasMore,
    reportsLoading,
    reportsLoadingMore,
    reportsTotalCount,
    notifications,
    assistantMessages: assistant.session.messages,
    assistantSession: assistant.session,
    assistantActiveVisualization: assistant.activeVisualization,
    assistantLatestVisualization: assistant.latestVisualization,
    assistantVisualizationHistory: assistant.visualizationHistory,
    assistantIsSending: assistant.isSending,
    assistantVizFullscreenOpen: assistant.vizFullscreenOpen,
    setAssistantVizFullscreenOpen: assistant.setVizFullscreenOpen,
    clearAssistantChat: assistant.clearChat,
    selectAssistantVisualization: assistant.selectVisualization,
    searchQuery,
    companySpend,
    workspaceUser,
    isLoading,
    error,
    pendingApprovalsCount,
    unreadNotificationsCount,
    activePoliciesCount,
    setSearchQuery,
    loadTransactions,
    loadMoreTransactions,
    refreshTransactions,
    loadFlags,
    loadMoreFlags,
    refreshFlags,
    loadReports,
    loadMoreReports,
    loadApprovals,
    loadMoreApprovals,
    refreshApprovals,
    refreshReports,
    refreshPolicies,
    refreshNotifications,
    refreshAll,
    togglePolicy,
    deletePolicy,
    addPolicy,
    editPolicy,
    importPolicies,
    analyzeImport,
    decideApproval,
  markNotificationRead,
    sendAssistantMessage,
    runComplianceScan,
    analyzeForFlags,
    runApprovalsPipeline,
    generateReports,
  };

  return (
    <MockStoreContext.Provider value={value}>
      {children}
    </MockStoreContext.Provider>
  );
}

export function useMockStore() {
  const context = useContext(MockStoreContext);
  if (!context) {
    throw new Error("useMockStore must be used within MockStoreProvider");
  }
  return context;
}

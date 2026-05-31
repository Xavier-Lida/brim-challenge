export type PolicyRequirements = {
  approval_threshold_cad?: number;
  category_limits_cad?: Record<string, number>;
  restricted_categories?: string[];
  restricted_merchants?: string[];
  notes?: string;
};

export type Policy = {
  id: string;
  policy_name: string;
  policy_requirements: PolicyRequirements;
  effective_date: string;
  active: boolean;
};

/** Policy row returned by import preview (no id yet). */
export type PolicyImportDraft = Omit<Policy, "id"> & { id?: string };

export type Employee = {
  id: string;
  first_name: string;
  last_name: string;
  department_id: string;
  department_name: string;
};

/** Full roster from GET /api/employees (map UI, future assistant pickers). */
export type EmployeeRosterEntry = {
  id: string;
  name: string;
  department: string;
  map_transaction_count: number;
};

export type TransactionStatus = "pending" | "approved" | "denied" | "flagged";

export type Transaction = {
  id: string;
  employee_id: string;
  employee_name: string;
  date: string;
  amount: number;
  merchant_name: string;
  merchant_category: string;
  city: string;
  status: TransactionStatus;
  flag_count: number;
};

export type TransactionFlag = {
  id: string;
  transaction_id: string;
  warning_message: string;
  weight: number;
  reviewed: boolean;
  policy_id?: string;
  policy_name?: string;
  incident_id?: string;
  related_transaction_ids?: string[];
  related_transactions?: Transaction[];
  transaction?: Transaction;
  employee_name?: string;
};

export type ApprovalStatus = "pending" | "approved" | "denied";

export type AiRecommendation = "approve" | "review" | "deny";

export type PolicyCheckStatus = "passed" | "failed";

export type PolicyCheck = {
  policy_id: string;
  policy_name: string;
  status: PolicyCheckStatus;
  message?: string;
};

export type ApprovalFlag = {
  warning_message: string;
  weight: number;
  policy_id?: string | null;
  policy_name?: string | null;
  incident_id?: string | null;
};

export type ApprovalRequest = {
  id: string;
  transaction_id: string;
  employee_id: string;
  employee_name: string;
  department_name: string;
  amount: number;
  merchant_name?: string;
  transaction_date?: string;
  merchant_category?: string;
  city?: string;
  reason: string;
  ai_recommendation: AiRecommendation;
  ai_reasoning: string;
  status: ApprovalStatus;
  department_budget_remaining: number;
  recent_expenses: { date: string; merchant: string; amount: number }[];
  policy_checks?: PolicyCheck[];
  policy_violation_summary?: string;
  flags?: ApprovalFlag[];
  incident_id?: string | null;
  policy_id?: string | null;
};

export type Notification = {
  id: string;
  type: "flag" | "approval" | "decision";
  reference_id: string;
  message: string;
  read: boolean;
  created_at: string;
};

export type VisualizationType = "bar" | "line" | "pie" | "table" | "kpi";

export type SeriesPoint = { name: string; value: number };

// Canonical, server-authoritative shapes. The backend owns column selection so
// the frontend only renders. Normalizers stay tolerant of legacy payloads.
export type Visualization =
  | { type: "bar" | "line"; title: string; data: { series: SeriesPoint[] } }
  | { type: "pie"; title: string; data: { segments: SeriesPoint[] } }
  | { type: "table"; title: string; data: { columns: string[]; rows: string[][] } }
  | {
      type: "kpi";
      title: string;
      data: { value: string; label: string; change?: string };
    };

export type AssistantProgressStep = {
  id: string;
  label: string;
  status: "pending" | "active" | "done";
};

/** Legacy chip text or structured follow-up from the assistant API. */
export type FollowUpSuggestion =
  | string
  | {
      label: string;
      prompt: string;
      hint?: string;
    };

export type VisualizationHistoryEntry = {
  messageId: string;
  visualization: Visualization;
  createdAt: string;
  sourceQuestion: string;
};

export type AssistantMessage = {
  id: string;
  role: "user" | "assistant";
  text: string;
  activity?: string;
  visualization?: Visualization;
  followUpSuggestions?: FollowUpSuggestion[];
  progressSteps?: AssistantProgressStep[];
  sourceQuestion?: string;
  sql?: string;
  streaming?: boolean;
  created_at: string;
};

export type AssistantLayoutMode = "centered" | "split";

export type AssistantSessionState = {
  messages: AssistantMessage[];
  layoutMode: AssistantLayoutMode;
  activeVisualizationId?: string;
};

export type WorkspaceUser = {
  name: string;
  role: string;
  email: string;
};

export type CompanySpend = {
  period: string;
  spent: number;
  budget: number;
};

/** A single line item shown on a report card and in the exported PDF. */
export type ReportTransaction = {
  date: string;
  merchant_name: string;
  merchant_category: string;
  city: string;
  amount: number;
};

export type ExpenseReport = {
  id: string;
  employee_id: string;
  event_group_id: string;
  title: string;
  date_from: string;
  date_to: string;
  total_amount: number;
  status: string;
  pdf_url: string | null;
  ai_recommendation: AiRecommendation;
  ai_reasoning: string;
  created_at?: string;
  // Optional context the backend may provide so the card and PDF read clearly
  // for a finance manager. All optional so existing payloads still render.
  employee_name?: string;
  department_name?: string;
  currency?: string;
  transaction_count?: number;
  transactions?: ReportTransaction[];
};

export type FlagsPage = {
  items: TransactionFlag[];
  has_more: boolean;
  limit: number;
  offset: number;
  unread_count: number;
};

export type ReportsPage = {
  items: ExpenseReport[];
  has_more: boolean;
  limit: number;
  offset: number;
  total_count?: number;
};

export type ApprovalsPage = {
  items: ApprovalRequest[];
  has_more: boolean;
  limit: number;
  offset: number;
  pending_count: number;
};

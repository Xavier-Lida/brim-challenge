import type { FollowUpSuggestion } from "@/lib/types/brim";
import type { Icon } from "@phosphor-icons/react";
import {
  ChartBarIcon,
  ChartLineUpIcon,
  CurrencyDollarIcon,
  MapPinIcon,
  ScalesIcon,
  StorefrontIcon,
  UsersIcon,
  WarningIcon,
} from "@phosphor-icons/react";

export type FollowUpCategory = "Spend" | "Compliance" | "Budget";

export type FollowUpCatalogEntry = {
  id: string;
  chip: string;
  prompt: string;
  category: FollowUpCategory;
  description: string;
  icon: Icon;
};

export type FollowUpResolveContext = {
  lastQuestion?: string;
  vizType?: string;
};

/** Resolved choice for compact UI (label + tooltip hint). */
export type FollowUpChoice = {
  id: string;
  chip: string;
  prompt: string;
  label: string;
  hint: string;
};

const CATEGORY_ICONS: Record<FollowUpCategory, Icon> = {
  Spend: ChartBarIcon,
  Compliance: WarningIcon,
  Budget: CurrencyDollarIcon,
};

const SPEND_IDS = new Set([
  "spend_by_dept_cat",
  "spend_by_department",
  "spend_by_category",
  "spend_by_city",
  "total_spend",
  "top_employees",
  "compare_depts",
  "compare_employees",
  "top_merchants",
  "spend_trend",
]);

const COMPLIANCE_IDS = new Set([
  "most_flagged",
  "repeat_offenders",
  "split_attempts",
]);

export const FOLLOW_UP_CATALOG: FollowUpCatalogEntry[] = [
  {
    id: "spend_by_dept_cat",
    chip: "Spend by department & category",
    prompt: "Show spend by department and category this quarter",
    category: "Spend",
    description: "Break down spend across departments and expense categories for the current period.",
    icon: ChartBarIcon,
  },
  {
    id: "spend_by_department",
    chip: "Spend by department",
    prompt: "Show spend by department this quarter",
    category: "Spend",
    description: "Compare total spend across departments in the current period.",
    icon: ChartBarIcon,
  },
  {
    id: "spend_by_category",
    chip: "Spend by category",
    prompt: "Show spend by category this quarter",
    category: "Spend",
    description: "See how spend splits across Brim expense categories.",
    icon: ChartBarIcon,
  },
  {
    id: "spend_by_city",
    chip: "Spend by city",
    prompt: "Show spend by city",
    category: "Spend",
    description: "Rank cities by total spend in the current period.",
    icon: MapPinIcon,
  },
  {
    id: "total_spend",
    chip: "Total company spend",
    prompt: "What is total company spend this quarter?",
    category: "Spend",
    description: "Single KPI for overall spend in the filtered period.",
    icon: CurrencyDollarIcon,
  },
  {
    id: "top_employees",
    chip: "Top employee spenders",
    prompt: "Top 10 employee spenders",
    category: "Spend",
    description: "Rank employees by total spend in the current period.",
    icon: UsersIcon,
  },
  {
    id: "compare_depts",
    chip: "Compare two departments",
    prompt: "Compare spend between Engineering and Sales this quarter",
    category: "Spend",
    description: "Side-by-side totals for two departments in the current period.",
    icon: ScalesIcon,
  },
  {
    id: "compare_employees",
    chip: "Compare two employees",
    prompt: "Compare spend between two employees this quarter",
    category: "Spend",
    description: "See how two employees' spend stacks up for the period.",
    icon: UsersIcon,
  },
  {
    id: "top_merchants",
    chip: "Top merchants",
    prompt: "Show top merchants by spend this quarter",
    category: "Spend",
    description: "Rank vendors by total spend and transaction count.",
    icon: StorefrontIcon,
  },
  {
    id: "spend_trend",
    chip: "Monthly spend trend",
    prompt: "Show monthly spend trend this year",
    category: "Spend",
    description: "Track how company spend changes month over month.",
    icon: ChartLineUpIcon,
  },
  {
    id: "budget_status",
    chip: "Departments over budget",
    prompt: "Which departments are over budget this quarter?",
    category: "Budget",
    description: "Highlight departments that exceeded their allocated budget.",
    icon: CurrencyDollarIcon,
  },
  {
    id: "most_flagged",
    chip: "Employees with the most flags",
    prompt: "Which employees have the most compliance flags?",
    category: "Compliance",
    description: "Find team members with the highest flag counts.",
    icon: WarningIcon,
  },
  {
    id: "repeat_offenders",
    chip: "Repeat offenders (2+ strikes)",
    prompt: "Show employees with two or more strikes",
    category: "Compliance",
    description: "List repeat policy violators and strike totals.",
    icon: WarningIcon,
  },
  {
    id: "split_attempts",
    chip: "Split-purchase attempts",
    prompt: "Show split-purchase attempts this quarter",
    category: "Compliance",
    description: "Surface transactions that may circumvent approval limits.",
    icon: WarningIcon,
  },
];

const catalogByChip = new Map(
  FOLLOW_UP_CATALOG.map((entry) => [entry.chip.toLowerCase(), entry])
);

const catalogById = new Map(FOLLOW_UP_CATALOG.map((entry) => [entry.id, entry]));

function lookupCatalogEntry(chip: string): FollowUpCatalogEntry | undefined {
  const trimmed = chip.trim();
  if (!trimmed) return undefined;

  const byChip = catalogByChip.get(trimmed.toLowerCase());
  if (byChip) return byChip;

  const byId = catalogById.get(trimmed);
  if (byId) return byId;

  const normalized = trimmed.toLowerCase();
  for (const entry of FOLLOW_UP_CATALOG) {
    const entryChip = entry.chip.toLowerCase();
    if (entryChip === normalized) return entry;
    if (entryChip.includes(normalized) || normalized.includes(entryChip)) {
      return entry;
    }
  }
  return undefined;
}

function contextualDescription(
  entry: FollowUpCatalogEntry,
  ctx?: FollowUpResolveContext
): string {
  if (!ctx?.lastQuestion && !ctx?.vizType) return entry.description;

  const q = ctx.lastQuestion?.toLowerCase() ?? "";
  if (SPEND_IDS.has(entry.id) && (q.includes("spend") || ctx.vizType === "bar")) {
    return `Follow up on your spend breakdown — ${entry.description.charAt(0).toLowerCase()}${entry.description.slice(1)}`;
  }
  if (COMPLIANCE_IDS.has(entry.id) && (q.includes("flag") || q.includes("strike"))) {
    return `Dig deeper into compliance — ${entry.description.charAt(0).toLowerCase()}${entry.description.slice(1)}`;
  }
  if (entry.id === "budget_status" && (q.includes("budget") || q.includes("department"))) {
    return `Connect spend to budgets — ${entry.description.charAt(0).toLowerCase()}${entry.description.slice(1)}`;
  }
  if (entry.id === "top_merchants" && ctx.vizType === "table") {
    return "You just saw a ranked list — explore merchants from another angle.";
  }
  return entry.description;
}

function followUpLabel(
  entry: FollowUpCatalogEntry,
  ctx?: FollowUpResolveContext
): string {
  const hint = contextualDescription(entry, ctx);
  if (hint === entry.description) return entry.chip;

  const dash = hint.indexOf(" — ");
  if (dash > 0 && dash <= 52) return hint.slice(0, dash);

  if (hint.length <= 48) return hint;
  return entry.chip;
}

export function resolveFollowUpEntry(
  chip: string,
  ctx?: FollowUpResolveContext
): FollowUpCatalogEntry {
  const known = lookupCatalogEntry(chip);
  const base =
    known ??
    ({
      id: chip.trim().toLowerCase().replace(/\s+/g, "_").slice(0, 40),
      chip: chip.trim(),
      prompt: chip.trim(),
      category: "Spend" as const,
      description: `Explore: ${chip.trim()}`,
      icon: CATEGORY_ICONS.Spend,
    } satisfies FollowUpCatalogEntry);

  return {
    ...base,
    description: contextualDescription(base, ctx),
  };
}

function isStructuredSuggestion(
  item: FollowUpSuggestion
): item is { label: string; prompt: string; hint?: string } {
  return typeof item === "object" && item !== null && "prompt" in item;
}

export function resolveFollowUpChoices(
  suggestions: FollowUpSuggestion[],
  ctx?: FollowUpResolveContext
): FollowUpChoice[] {
  return suggestions.map((item, index) => {
    if (isStructuredSuggestion(item)) {
      const label = item.label.trim() || item.prompt.trim();
      const prompt = item.prompt.trim();
      const hint =
        item.hint?.trim() ||
        (ctx?.lastQuestion
          ? `Follow up on: ${ctx.lastQuestion.slice(0, 80)}`
          : prompt);
      return {
        id: `follow-up-${index}-${label.slice(0, 24).replace(/\s+/g, "-").toLowerCase()}`,
        chip: label,
        prompt,
        label,
        hint,
      };
    }

    const chip = String(item).trim();
    const entry = resolveFollowUpEntry(chip, ctx);
    const hint = contextualDescription(entry, ctx);
    return {
      id: entry.id,
      chip: entry.chip,
      prompt: entry.prompt,
      label: followUpLabel(entry, ctx),
      hint,
    };
  });
}

export function catalogEntryById(id: string): FollowUpCatalogEntry | undefined {
  return catalogById.get(id);
}

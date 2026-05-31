import { initialApprovals, initialTransactions } from "@/lib/mocks/fixtures";

export const ASSISTANT_DEPARTMENTS = [
  "Engineering",
  "Sales",
  "Marketing",
  "Product",
  "Finance",
] as const;

const US_STATE_CODES = [
  "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL",
  "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT",
  "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI",
  "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC",
] as const;

const US_STATE_NAMES = [
  "Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado",
  "Connecticut", "Delaware", "Florida", "Georgia", "Hawaii", "Idaho", "Illinois",
  "Indiana", "Iowa", "Kansas", "Kentucky", "Louisiana", "Maine", "Maryland",
  "Massachusetts", "Michigan", "Minnesota", "Mississippi", "Missouri", "Montana",
  "Nebraska", "Nevada", "New Hampshire", "New Jersey", "New Mexico", "New York",
  "North Carolina", "North Dakota", "Ohio", "Oklahoma", "Oregon", "Pennsylvania",
  "Rhode Island", "South Carolina", "South Dakota", "Tennessee", "Texas", "Utah",
  "Vermont", "Virginia", "Washington", "West Virginia", "Wisconsin", "Wyoming",
] as const;

const COUNTRIES = [
  "Canada", "United States", "USA", "US", "Mexico", "France", "United Kingdom",
  "UK", "Germany", "Spain", "Italy", "Japan", "Australia",
] as const;

function uniqueNonEmpty(values: (string | undefined)[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const v of values) {
    const trimmed = v?.trim();
    if (!trimmed || trimmed.length < 2) continue;
    const key = trimmed.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(trimmed);
  }
  return out.sort((a, b) => b.length - a.length);
}

export const STATIC_ENTITY_VOCABULARY = uniqueNonEmpty([
  ...ASSISTANT_DEPARTMENTS,
  "Northwind Labs",
  ...US_STATE_CODES,
  ...US_STATE_NAMES,
  ...COUNTRIES,
  ...initialTransactions.map((t) => t.merchant_name),
  ...initialTransactions.map((t) => t.employee_name),
  ...initialTransactions.map((t) => t.city),
  ...initialApprovals.map((a) => a.department_name),
  ...initialApprovals.map((a) => a.employee_name),
]);

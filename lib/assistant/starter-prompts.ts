export const ASSISTANT_STARTER_PROMPTS = [
  {
    title: "Spend by department",
    prompt: "Show spend by department this quarter",
    category: "Spend",
  },
  {
    title: "Top employee spenders",
    prompt: "Top 10 employee spenders",
    category: "Spend",
  },
  {
    title: "Spend by city",
    prompt: "Show spend by city",
    category: "Spend",
  },
  {
    title: "Active flags",
    prompt: "How many flags this month?",
    category: "Compliance",
  },
  {
    title: "Meal violations",
    prompt: "Which meals exceeded policy limits?",
    category: "Policy",
  },
  {
    title: "Pending approvals",
    prompt: "Summarize pending approval requests",
    category: "Approvals",
  },
  {
    title: "Travel spend",
    prompt: "Show weekly travel spend trend",
    category: "Spend",
  },
  {
    title: "Flagged transactions",
    prompt: "List recent flagged transactions",
    category: "Compliance",
  },
] as const;

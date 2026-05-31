export const BRIM_CATEGORIES = [
  "Repas Client",
  "Repas Personnel",
  "Voyage",
  "Transport Local",
  "Logiciel / IT",
  "Carburant",
  "Fournitures de bureau",
  "Télécommunications",
  "Autre",
] as const;

export type BrimCategory = (typeof BRIM_CATEGORIES)[number];

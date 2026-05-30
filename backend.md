# Brim Financial × MPC Hacks — Contexte Backend

## Stack

Next.js 14 API Routes, Supabase (DB + Auth + Realtime), Google Gemini API, Resend (emails). Moteur de rapports (Feature 4) en Python : pandas + LangChain (`langchain-google-genai`) + pydantic (voir `feature4.py`).

---

## Tables Supabase


| Table               | Attributs                                                                                                          |
| ------------------- | ------------------------------------------------------------------------------------------------------------------ |
| `departments`       | id, department_name                                                                                                |
| `employees`         | id, first_name, last_name, department_id                                                                           |
| `policies`          | id, effective_date, policy_name, policy_requirements                                                               |
| `employee_strikes`  | employee_id, strike_description, strike_date, amount_cheated                                                       |
| `transaction_flags` | transaction_id, warning_message, weight                                                                            |
| `transactions`      | id, employee_id, date, amount, merchant_name, merchant_category, city, latitude, longitude, event_group_id, status |
| `approval_requests` | id, transaction_id, employee_id, amount, reason, ai_recommendation, ai_reasoning, status, approver_id, decided_at  |
| `expense_reports`   | id, employee_id, event_group_id, title, date_from, date_to, total_amount, status, pdf_url, ai_recommendation, ai_reasoning |
| `notifications`     | id, type, reference_id, message, read, created_at                                                                  |


---

## API Routes

### `POST /api/assistant`

Point d'entrée du Brim Assistant. Reçoit l'historique complet de la conversation + un contexte optionnel (plage de dates, départements). Avant d'appeler Gemini, interroge Supabase pour récupérer les transactions pertinentes, les policies actives, et les informations des employés concernés, puis les injecte dans le system prompt. Gemini retourne un objet structuré `{ text, visualization: { type, title, data }, followUpSuggestions }`. Le type de visualisation (bar, line, pie, table, kpi) est choisi par Gemini selon la nature de la question.

### `POST /api/compliance/scan`

Appelé automatiquement via le webhook à chaque nouvelle transaction, ou manuellement pour un batch. Charge toutes les policies actives depuis Supabase et les envoie à Gemini avec la transaction et son contexte (historique de l'employé, transactions récentes similaires). Gemini raisonne en contexte — il détecte par exemple un achat splitté pour contourner un seuil, ou compare un repas solo vs équipe. Si un flag est détecté, il est inséré dans `transaction_flags` avec un `weight` (1–5) et un `warning_message` explicatif. Une entrée est créée dans `notifications`. Si `weight >= 3`, un email est envoyé au company approver via Resend avec un lien direct vers le flag.

### `POST /api/policies/import`

Reçoit un PDF (base64) ou du texte brut. Gemini analyse le document et extrait les règles de politique sous forme structurée (nom de la règle, conditions, seuils, départements concernés). Retourne une preview JSON pour que l'UI puisse afficher la modale de confirmation. Sur confirmation de l'utilisateur, les règles sont insérées dans la table `policies` avec leur date de mise en vigueur.

### `GET /api/policies` · `PATCH /api/policies/[id]` · `DELETE /api/policies/[id]`

CRUD standard sur les policies. Le PATCH permet de modifier les `policy_requirements` directement depuis la modale UI. Le DELETE désactive une règle sans la supprimer (soft delete via un champ `active`).

### `GET /api/approvals` · `PATCH /api/approvals/[id]`

GET retourne les demandes d'approbation en attente avec le détail de l'employé, le budget restant de son département, et son historique de dépenses récent. PATCH traite la décision (approve/deny) : met à jour `approval_requests`, met à jour le statut de la transaction dans `transactions`, et envoie un email de confirmation à l'employé via Resend.

### `POST /api/reports/generate`

Deux modes, tous deux servis par le **moteur Feature 4** (`feature4.py`, voir plus bas) :

- **Single** — reçoit un `event_group_id`. Récupère toutes les transactions du groupe depuis Supabase, jointes avec les données employé et les flags éventuels. Gemini génère un résumé narratif du voyage/événement, vérifie la conformité aux policies actives, identifie les anomalies, et produit une **recommandation d'approbation** (`approve` / `review` / `deny`). Le rapport est mis en forme en PDF, uploadé dans Supabase Storage, et une entrée est créée dans `expense_reports` (avec `pdf_url`, `ai_recommendation`, `ai_reasoning`, `status = ready_for_approval`).
- **Batch** — sans `event_group_id`, le moteur regroupe lui-même les transactions récentes non assignées en événements, met à jour `transactions.event_group_id`, et crée un `expense_reports` par événement. C'est le scénario « Sarah à San Diego » : 10 transactions proches → un rapport, lié aux spend categories, prêt pour le CFO avec sa recommandation de politique.

### `POST /api/webhooks/supabase`

Déclenché par un trigger Supabase à chaque INSERT dans `transactions`. Lance en parallèle : le scan compliance, la vérification du seuil d'approbation (si `amount` dépasse le seuil défini dans les policies, crée une entrée dans `approval_requests` et notifie l'approver), et la logique de groupement (assigne un `event_group_id` basé sur la proximité temporelle, la localisation, et l'employé). Le groupement et la génération de rapport sont délégués au moteur Feature 4 ci-dessous.

---

## Feature 4 — Moteur de génération de rapports (`feature4.py`)

Pipeline batch autonome (pandas + LangChain · Gemini, défaut `gemini-2.5-flash` configurable via `GEMINI_MODEL` / `--model`) qui transforme des `transactions` en `expense_reports` prêts à approuver. Il parle directement le schéma Supabase via des CSV en entrée (`transactions` + `mcc_codes` requis ; `transaction_flags`, `employee_strikes`, `employees`, `departments` optionnels) et émet du JSON réinjectable :

```
{
  "transaction_event_groups": [ {transaction_id, event_group_id} ],   // -> UPDATE transactions
  "expense_reports":          [ {id, employee_id, event_group_id, title, date_from,
                                 date_to, total_amount, status, pdf_url,
                                 ai_recommendation, ai_reasoning} ]    // -> INSERT expense_reports
}
```

**Étapes**

1. **MCC → spend category Brim.** `mcc_codes.csv` + overrides explicites + règles par mots-clés sur la description + plage `3000–3999` → `Voyage`, fallback `Autre`.
2. **Groupement en événements (spatiotemporel).** Par employé : tri par date, nouveau cluster dès qu'un écart dépasse `GROUP_GAP_DAYS = 4` jours — mais si les deux transactions sont au **même endroit** (même ville, ou coordonnées GPS à moins de `GEO_SAME_KM = 50` km), on tolère `SAME_PLACE_GAP_BONUS = 3` jours de plus. Ainsi un voyage (ex. la conférence à San Diego) reste groupé malgré un week-end, sans fusionner des événements distincts. Clustering *déterministe* ; le LLM ne fait que **nommer** les clusters multi-transactions (titre + raison, batché). Chaque cluster reçoit un `event_group_id` (uuid).
3. **Contexte politique.** Jointure des `transaction_flags` (message + `weight`) et agrégation des `employee_strikes` (count, total fraudé, descriptions).
4. **Un `expense_report` par événement** : titre, `date_from`/`date_to`, `total_amount`, répartition par catégorie, `status = ready_for_approval`.
5. **Recommandation d'approbation IA** (`approve` / `review` / `deny`) pour le CFO, raisonnant sur les flags + l'historique de strikes. Auto-approbation des rapports triviaux (1 item ≤ 100 CAD, sans flag ni strike) ; le reste est jugé par Gemini (par lots de `RECO_BATCH_SIZE = 40`), avec un **fallback déterministe** (poids max ≥ 0.66 ou ≥ 2 strikes → `deny` ; flag présent ou montant > 500 → `review` ; sinon `approve`).
6. **Tolérance aux pannes** : toute erreur LLM dégrade vers le chemin déterministe/mock — jamais d'échec dur.

```
py feature4.py --transactions transactions.csv --flags transaction_flags.csv \
    --strikes employee_strikes.csv --employees employees.csv --departments departments.csv \
    --out feature4_output.json
py feature4.py --transactions transactions.csv --mock-llm   # aucun appel API
```

---

## Flux principal

```
Nouvelle transaction
  → webhook
    → scan compliance (Gemini) → transaction_flags + notifications + email si weight ≥ 3
    → montant > seuil policy   → approval_requests + email approver
    → groupement logique       → event_group_id assigné sur la transaction

Import policy
  → Gemini extrait les règles → preview UI → confirmation → INSERT policies
  → ces policies sont chargées à chaque appel de /api/compliance/scan

Assistant
  → messages + contexte → données Supabase injectées dans le prompt → Gemini
  → { text, visualization, followUpSuggestions } retourné au frontend
```

---

## Realtime

Supabase Realtime écoute les INSERTs sur `transaction_flags` et `notifications` pour pousser les mises à jour au client sans polling — ce qui alimente le badge de la sidebar et la liste des flags en temps réel.
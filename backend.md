# Brim Financial × MPC Hacks — Contexte Backend

## Stack

**FastAPI** (Python) + **Uvicorn**, Supabase (Postgres), Google Gemini API (`langchain-google-genai`), Resend (emails). Frontend : **Next.js** (`brim-frontend`) consomme l'API REST sur `NEXT_PUBLIC_API_URL` (défaut `http://127.0.0.1:8000`). Moteurs Python (features 1–4) : pandas + LangChain + pydantic, plus DuckDB pour le text-to-SQL de Feature 1 (voir `feature1.py`, `feature2.py`, `feature3.py`, `feature4.py`).

**Lancer le backend :** `uvicorn main:app --reload --port 8000` (variables dans `.env.example`).

**Routes implémentées (FastAPI) :**

| Route | Statut |
| ----- | ------ |
| `GET /health` | OK |
| `GET /api/transactions` | OK |
| `GET /api/flags`, `PATCH /api/flags/{id}/reviewed` | OK |
| `GET /api/approvals`, `POST /api/approvals/run`, `PATCH /api/approvals/{id}` | OK |
| `GET /api/reports`, `POST /api/reports/generate` | OK |
| `POST /api/compliance/scan` | OK |
| `POST /api/assistant` | OK |
| `GET/POST/PATCH/DELETE /api/policies`, `POST /api/policies/import`, `POST /api/policies/import/confirm` | OK |
| `GET /api/notifications`, `PATCH /api/notifications/{id}/read` | OK |
| `POST /api/webhooks/supabase` | OK (trigger SQL dans `supabase/triggers.sql`) |

---

## Tables Supabase


| Table               | Attributs                                                                                                          |
| ------------------- | ------------------------------------------------------------------------------------------------------------------ |
| `departments`       | id, department_name                                                                                                |
| `employees`         | id, first_name, last_name, department_id                                                                           |
| `budgets`           | id, department_id, budget, quarter ('Q1'–'Q4'), year, UNIQUE(department_id, quarter, year)                          |
| `policies`          | id, effective_date, policy_name, policy_requirements **(JSONB)**, active                                            |
| `employee_strikes`  | id, employee_id, strike_description, strike_date, amount_cheated                                                   |
| `transaction_flags` | id, transaction_id, warning_message, weight **(SMALLINT 1–5)**, created_at                                          |
| `transactions`      | id, employee_id, date, amount, merchant_name, merchant_category, city, zipcode, latitude, longitude, event_group_id, status |
| `approval_requests` | id, transaction_id, employee_id, amount, reason, ai_recommendation, ai_reasoning, status, approver_id, decided_at  |
| `expense_reports`   | id, employee_id, event_group_id, title, date_from, date_to, total_amount, status, pdf_url, ai_recommendation, ai_reasoning |
| `notifications`     | id, type **('flag' \| 'approval' \| 'decision')**, reference_id, message, read, created_at                                        |

> Schéma canonique : [`supabase/schema.sql`](supabase/schema.sql) (DDL). Notes clés : `transaction_flags.weight` est un **entier 1–5** (contrainte CHECK) — l'échelle de sévérité partagée par tout le pipeline ; `policies.policy_requirements` est du **JSONB** structuré (`approval_threshold_cad`, `category_limits_cad`, `restricted_categories`, `restricted_merchants`, `notes`) — source de vérité pour Features 2 et 3 ; `notifications.type` ∈ {`flag`, `approval`, `decision`}. La table `budgets` (budget trimestriel par département) alimente le statut budgétaire de Feature 3.


---

## API Routes

### `POST /api/assistant`

Point d'entrée du Brim Assistant, servi par le **moteur Feature 1** (`feature1.py`, voir plus bas). Reçoit l'historique de la conversation + un contexte optionnel. Plutôt que d'injecter les transactions dans le prompt (qui ne passe pas à l'échelle sur des milliers de lignes), Gemini **génère une requête SQL** que le serveur exécute en lecture seule contre les données (DuckDB en local / Supabase en prod), s'auto-corrige en cas d'erreur, puis rédige la réponse. Retourne `{ text, visualization: { type, title, data }, followUpSuggestions, sql }`. Le type de visualisation (bar, line, pie, table, kpi) suit la forme du résultat ; les `followUpSuggestions` proviennent d'un registre de capacités testées (puces toujours répondables), la saisie restant libre.

### `POST /api/compliance/scan`

Appelé automatiquement via le webhook à chaque nouvelle transaction, ou manuellement pour un batch. Servi par le **moteur Feature 2** (`feature2.py`, voir plus bas). Charge toutes les policies actives depuis Supabase et les envoie à Gemini avec la transaction et son contexte (historique de l'employé, transactions récentes similaires). Gemini raisonne en contexte — il détecte par exemple un achat splitté pour contourner un seuil, ou compare un repas solo vs équipe. Si un flag est détecté, il est inséré dans `transaction_flags` avec un `weight` (entier 1–5, sévérité ; même échelle que celle lue par Feature 4) et un `warning_message` explicatif. Une entrée est créée dans `notifications` (`type='flag'`), et les violations sérieuses (`weight >= 4`) génèrent un `employee_strikes` pour faire ressortir les récidivistes. Si `weight >= 3`, un email est envoyé au company approver via Resend avec un lien direct vers le flag.

### `POST /api/policies/import`

Reçoit un PDF (base64) ou du texte brut. Le moteur [`api/policy_import.py`](api/policy_import.py) découpe le document par sections, appelle Gemini par fragments (ou fallback regex multi-règles si `mock_llm=true` / pas de `GOOGLE_API_KEY`), et retourne **plusieurs** policies JSONB structurées (une par thème : repas, seuil d'approbation, marchands interdits, etc.) — jamais une seule policy avec le PDF entier dans `notes`. Query `mock_llm=true` pour le fallback sans API. Preview → `POST /api/policies/import/confirm` insère dans `policies`.

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

## Feature 1 — Assistant « Talk to Your Data » (`feature1.py`)

Moteur de Q&R **agentique text-to-SQL**. Même stack/conventions que F2/F4 (réutilise les loaders + le mapping MCC de `feature4.py`), `--mock-llm` + dégradation gracieuse (jamais d'échec dur). Les chiffres viennent d'une **vraie agrégation SQL**, pas du LLM.

**Modèle d'interaction.** Texte libre à tout moment. Les *choix* de suivi (`followUpSuggestions`) proviennent d'un **registre de capacités battle-tested** — chaque puce mappe une requête connue-bonne, donc une puce suggérée est toujours répondable, tandis que la saisie reste libre.

**Pipeline** (la « profondeur IA » — pas un wrapper mono-prompt) :
1. **PLAN** — Gemini → `{sql, chart, title}` (sortie structurée) depuis la question + l'historique + le schéma.
2. **GUARD** — rejette tout sauf un unique `SELECT`/`WITH` lecture seule ; injecte un `LIMIT`.
3. **EXECUTE** — DuckDB sur `tx` (transactions enrichies : `employee_name`, `department`, `brim_category`) ⋈ `budget`, `flags`, `strikes`.
4. **REPAIR** — sur erreur SQL, renvoie l'erreur à Gemini (jusqu'à 2 fois) → boucle agentique auto-correctrice.
5. **NARRATE** — Gemini transforme les lignes en réponse 1–3 phrases ; la viz (`bar|line|pie|table|kpi`) suit la forme du résultat.

Sortie = le contrat `/api/assistant` : `{ text, visualization{type,title,data}, followUpSuggestions, sql }` (`sql` renvoyé pour la transparence). Le moteur ne décrit au LLM que les tables **présentes**, donc l'assistant couvre aussi bien les dépenses que la **surveillance / fraude** (« qui a le plus de flags ? », « récidivistes », « tentatives de split ») — sans dupliquer de détection (c'est le rôle de Feature 2 ; F1 ne fait qu'interroger ses sorties `flags`/`strikes`).

```
py feature1.py --transactions transactions.csv --employees employees.csv \
    --departments departments.csv --budgets budgets.csv --flags transaction_flags.csv \
    --strikes employee_strikes.csv --question "Qu'a dépensé Marketing en logiciel le trimestre dernier ?"
py feature1.py --transactions transactions.csv --question "Top merchants this month" --mock-llm
```

---

## Feature 2 — Moteur de conformité (`feature2.py`)

Moteur batch autonome (même stack que Feature 4 : pandas + LangChain · Gemini) qui scanne les `transactions` contre la politique de dépenses et **produit les artefacts que Feature 4 consomme** (`transaction_flags` + `employee_strikes`). Architecture identique à Feature 4 : un cœur déterministe calcule des signaux structurés (« concerns »), le LLM ne fait que le jugement *contextuel* sur les candidats remontés. Ne plante jamais : toute erreur LLM dégrade vers un verdict déterministe. Réutilise les loaders / le mapping MCC de `feature4.py` (source unique).

```
{
  "transaction_flags": [ {transaction_id, warning_message, weight} ],                // -> INSERT (weight 1–5)
  "employee_strikes":  [ {employee_id, strike_description, strike_date, amount_cheated} ], // -> INSERT
  "notifications":     [ {id, type: "flag", reference_id, message, read} ],          // -> INSERT
  "summary": { by_severity, repeat_offenders (rangés), policy }
}
```

**Étapes**

1. **MCC → spend category** (via `feature4.load_transactions`), pour distinguer repas solo (`Repas Personnel`) vs client/équipe (`Repas Client`).
2. **Détecteurs déterministes** (chacun produit un *concern* {code, message, weight, montant} ; `weight` est un **entier 1–5**) :
   - **Achat splitté** : ≥ 2 charges au même marchand par un employé dans une fenêtre de `SPLIT_WINDOW_DAYS = 2` jours, chacune sous le seuil mais dont la somme l'atteint → contournement du seuil d'approbation (`weight 5`). *(le cas « 2× 300 \$ pour esquiver 500 \$ »)*
   - **Doublon** : même employé + marchand + montant à `DUPLICATE_WINDOW_DAYS = 1` jour (`3`).
   - **Seuil d'approbation** : montant ≥ `approval_threshold_cad` (défaut 500) et statut non approuvé (`3`).
   - **Limite par catégorie** : ex. repas solo > 75 \$ (`2`) — encode la nuance solo vs équipe.
   - **Marchand / catégorie restreint** (`4`), **montant rond** (`1`, booster seul ignoré).
3. **Scan LLM contextuel** (uniquement les candidats, par lots de `SCAN_BATCH_SIZE = 25`) : reçoit la police, la transaction, les concerns et l'historique de dépenses de l'employé, et renvoie `{is_violation, warning_message, weight (1–5), policy}`. Fallback déterministe sinon.
4. **Agrégation** : violations rangées par sévérité (`>= 4` haute, `>= 3` alerte l'approbateur), récidivistes remontés, chaque violation sérieuse (`weight >= 4`) → un `employee_strikes` (montant = montant propre de la transaction, pour ne pas double-compter les splits côté Feature 4).

**Source des policies.** La source de vérité est la table Supabase `policies` (`id, effective_date, policy_name, policy_requirements` **JSONB**, `active`). En production, `/api/compliance/scan` interroge Supabase et passe les policies actives au moteur ; en batch, le moteur lit un mirror CSV de cette table (même convention que toutes les tables côté `feature*.py`). Le **JSONB `policy_requirements`** (règles extraites des PDF par `/api/policies/import`) est parsé : les clés structurées — `approval_threshold_cad`, `category_limits_cad`, `restricted_categories`, `restricted_merchants` — pilotent directement les **seuils déterministes** (option 1), tandis que tout texte libre `notes` est passé au LLM pour le raisonnement contextuel. Les lignes `active = false` sont ignorées ; à défaut de policies, des défauts intégrés s'appliquent.

```
py feature2.py --transactions transactions.csv --policies policies.csv \
    --employees employees.csv --departments departments.csv --out feature2_output.json
py feature2.py --transactions transactions.csv --mock-llm   # aucun appel API
```

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
2. **Groupement en événements (spatiotemporel).** Par employé : tri par date, nouveau cluster dès qu'un écart dépasse `GROUP_GAP_DAYS = 4` jours — mais si les deux transactions sont au **même endroit** (priorité : même ville → même code postal → coordonnées GPS à moins de `GEO_SAME_KM = 50` km), on tolère `SAME_PLACE_GAP_BONUS = 3` jours de plus. Ainsi un voyage (ex. la conférence à San Diego) reste groupé malgré un week-end, sans fusionner des événements distincts. Clustering *déterministe* ; le LLM ne fait que **nommer** les clusters multi-transactions (titre + raison, batché). Chaque cluster reçoit un `event_group_id` (uuid).
3. **Contexte politique.** Jointure des `transaction_flags` (message + `weight`) et agrégation des `employee_strikes` (count, total fraudé, descriptions).
4. **Un `expense_report` par événement** : titre, `date_from`/`date_to`, `total_amount`, répartition par catégorie, `status = ready_for_approval`.
5. **Recommandation d'approbation IA** (`approve` / `review` / `deny`) pour le CFO, raisonnant sur les flags + l'historique de strikes. Auto-approbation des rapports triviaux (1 item ≤ 100 CAD, sans flag ni strike) ; le reste est jugé par Gemini (par lots de `RECO_BATCH_SIZE = 40`), avec un **fallback déterministe** (poids max ≥ 4 ou ≥ 2 strikes → `deny` ; flag présent ou montant > 500 → `review` ; sinon `approve`).
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
    → scan compliance (Gemini) → transaction_flags + employee_strikes + notifications + email si weight ≥ 3
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
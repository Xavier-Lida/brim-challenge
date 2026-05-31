# Prompt frontend — roster employés (carte, chat)

Contexte : le backend Brim expose maintenant le roster complet des employés.

## Endpoints

- `GET /api/employees`
  - Réponse : `[{ id, name, department, map_transaction_count }]`
- `GET /api/map/employees` (contrat carte inchangé, liste enrichie)
  - Réponse : `[{ id, name, transaction_count }]` — `transaction_count` === `map_transaction_count`

## Règles UI carte (Reports)

1. Charger les employés via `GET /api/map/employees` (ou `/api/employees` si un seul appel suffit).
2. Afficher **tous** les noms dans le sélecteur multi-employés.
3. Désactiver ou griser les entrées où `transaction_count` (ou `map_transaction_count`) === 0, avec tooltip « Aucun achat géolocalisé ».
4. Ne sélectionner par défaut que des employés avec `count > 0`.
5. Appeler `GET /api/map/purchases?employee_ids=...` uniquement pour les IDs sélectionnés avec `count > 0`.

## Chat / assistant

- Pas de changement d’API `POST /api/assistant`.
- Si un picker employé ou autocomplétion existe, préférer `GET /api/employees` pour le roster (`name` + `department`).

## Configuration

`NEXT_PUBLIC_API_URL` (ou proxy BFF) doit pointer vers le backend FastAPI.

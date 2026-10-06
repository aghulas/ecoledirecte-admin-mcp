---
name: "maintenance-connecteur-ecoledirecte"
description: "Modifier, tester, pousser et documenter le connecteur MCP EcoleDirecte (dépôt ~/dev/ecoledirecte-admin-mcp) : branche, tests, commit, push, déploiement Azure, OpenAPI, spec du projet."
---

# Maintenance du connecteur MCP EcoleDirecte

À utiliser pour toute évolution des serveurs `ecoledirecte-admin` / `ecoledirecte-perso` : nouvel outil, correctif, régénération du catalogue des paramètres, mise à jour de la doc OpenAPI.

## Où et comment travailler

- Dépôt sur le Mac de Rémi : `/Users/remi/dev/ecoledirecte-admin-mcp` (venv `.venv`, installation éditable), qui contient les deux paquets `ecoledirecte_admin_mcp` et `ecoledirecte_perso_mcp`. Travailler sur place (Desktop Commander / terminal du Mac), jamais sur une copie dans le cloud.
- Commencer par `git fetch` + `git status -sb` : Rémi ou un autre outil a pu pousser entre-temps (fusion, jamais de force-push).
- Créer une branche pour un changement non trivial.
- Jamais de données d'élèves ou de familles dans un fichier versionné (lectures manuelles sous `~/Charlemagne/`). Dépôt public : aucun chemin de serveur propre à l'école (valeurs par défaut génériques, chemins réels dans la configuration locale). Aucun jeton dans les remotes (`git remote -v` masqué).
- Le connecteur ne manipule jamais de mot de passe, d'IBAN ni de BIC.

## Messagerie perso (écriture)

- `ed_perso_message_ecrire` : simulation par défaut, `ED_PERSO_MESSAGERIE_ACTIF=1`, brouillon (`mode="brouillon"`) à privilégier — l'envoi est fait à la main depuis la boîte du secrétariat.
- Pièces jointes : `client.televerser_piece_jointe` (`POST v3/televersement.awp?verbe=post`, multipart `file` → `{unc, libelle}`), puis `files: [{id:"0", libelle, displayText, unc}]` dans le message ; fichiers sous `ED_PERSO_PJ_RACINES` (défaut `~/Charlemagne`), 5 au plus, 20 Mo, documents bancaires refusés.
- Plafonds : `ED_PERSO_MESSAGERIE_MAX_DEST` (30) pour un envoi, `ED_PERSO_MESSAGERIE_MAX_DEST_BROUILLON` (150) pour un brouillon via `plafond_destinataires`.
- Validation réelle : uniquement en brouillon, relu (`ed_perso_message_lire`, `boite="draft"`), jamais envoyé sans accord explicite de Rémi.

## Tests

- `.venv/bin/python -m pytest -q` : tous verts avant tout commit ; ajouter des tests sans réseau (respx, faux client) pour chaque garde-fou.
- Vérifier en réel en lecture seule (`.venv/bin/python -` avec le client) quand c'est utile ; jamais d'écriture réelle sans accord explicite de Rémi.

## Catalogue des paramètres admin

- `tools/extraire_parametres.py` (télécharge le bundle `scripts/scripts.*.js` du front admin, httpx) → `ecoledirecte_admin_mcp/data/parametres_front.json`.
- Après régénération : contrôler le nombre de libellés, l'absence de faux paramètres (options de listes, textes avec espaces/parenthèses), relancer les tests.
- Intitulés lisibles : dictionnaire `INTITULES` de `parametres_catalogue.py`.

## Commit, push, déploiement

- Commit et push **uniquement quand Rémi le demande**. Message en français sans accents dans le titre, corps listant les changements et la validation réelle, puis :
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: <lien de la session>
  ```
  (reprendre les lignes d'attribution indiquées par la session courante).
- Version dans `pyproject.toml` incrémentée pour un nouvel outil ou paramètre.
- Fusion `--ff-only` dans `main`, push, suppression de la branche.
- Le push déclenche deux workflows GitHub Actions (déploiement Azure admin et perso) : suivre avec `gh run list --limit 2` (depuis le Mac) jusqu'à `success` (plusieurs minutes). Les écritures restent désactivées sur Azure.
- Rappeler à Rémi de **redémarrer complètement Claude Desktop** : les outils d'une conversation déjà ouverte gardent l'ancienne version.
- Toute édition de `claude_desktop_config.json` : sauvegarde horodatée avant, validation JSON après.

## Documentation à tenir à jour

- `README.md` du dépôt (tableau des outils, sections dédiées), version dans `pyproject.toml`, `package-data` si nouveaux fichiers de données.
- `openapi/ecoledirecte-wrapper.openapi.yaml` (Swagger 2.0 pour Copilot Studio) : aligner les opérations, ajouter les `definitions`, incrémenter la version, valider avec `openapi-spec-validator` (attention aux virgules dans les descriptions en style `{ … }` : les mettre entre guillemets). Supervision, dépôts, demandes, documents et messagerie restent hors de ce contrat.
- Spec du projet `claude/spec-connecteur-mcp-ecoledirecte.md` : lire, modifier, réécrire en entier (`project_write`) — statut et dernier commit en tête, tableaux d'outils (§3/§4), écritures (§5), limites (§8), incidents et enseignements (§9).

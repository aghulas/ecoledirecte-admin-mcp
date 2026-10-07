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
- Découvrir un endpoint : lire le JavaScript public du front (`www.ecoledirecte.com` → `chunk-*.js`, `main-*.js`), téléchargé sur le Mac dans un dossier temporaire hors dépôt (le cloud n'atteint pas ecoledirecte.com), supprimé après usage. API classique : `api.ecoledirecte.com/v3/….awp` (corps `data=<JSON>`) ; API REST du front (`withRestApi`) : `api.ecoledirecte.com/restv3/ws/…` (corps JSON).

## Messagerie perso (écriture)

- `ed_perso_message_ecrire` : simulation par défaut, `ED_PERSO_MESSAGERIE_ACTIF=1`, brouillon (`mode="brouillon"`) à privilégier — l'utilisateur envoie lui-même depuis sa boîte.
- Pièces jointes : `client.televerser_piece_jointe` (`POST v3/televersement.awp?verbe=post`, multipart `file` → `{unc, libelle}`), puis `files: [{id:"0", libelle, displayText, unc}]` dans le message ; fichiers sous `ED_PERSO_PJ_RACINES` (défaut `~/Charlemagne`), 5 au plus, 20 Mo, documents bancaires refusés.
- Plafonds : `ED_PERSO_MESSAGERIE_MAX_DEST` (30) pour un envoi, `ED_PERSO_MESSAGERIE_MAX_DEST_BROUILLON` (150) pour un brouillon via `plafond_destinataires`.
- Validation réelle : uniquement en brouillon, relu (`ed_perso_message_lire`, `boite="draft"`), jamais envoyé sans accord explicite de Rémi.
- **Jamais de message écrit au nom d'un autre compte par la supervision admin** : EcoleDirecte désactive l'envoi et les brouillons en mode supervision (décision du 01/10/2026, rappelée le 07/10) ; l'écriture se fait uniquement avec les identifiants du compte lui-même.

## Compte perso et authentification

- Compte du connecteur perso : **le compte personnel de chaque utilisateur** (depuis le 07/10/2026 ; avant, le compte partagé du secrétariat) — quand le connecteur est diffusé, chacun configure ses propres identifiants. Identifiant dans `~/.ecoledirecte-perso-mcp/config.json`, mot de passe dans le Trousseau (service `ecoledirecte-perso-mcp`), jetons dans `session.json` (token, et `cn`/`cv` de double authentification).
- Changer de compte ou de mot de passe : sauvegarder ces fichiers, puis l'utilisateur lance lui-même dans Terminal `cd ~/dev/ecoledirecte-admin-mcp`, `.venv/bin/python -m ecoledirecte_perso_mcp.auth setup` puis `… auth login`, et relance Claude Desktop. Erreur « Identifiant ou mot de passe invalide (505) » répétée = mot de passe changé.
- **Double authentification** : le login renvoie le code 250 et un jeton dans l'en-tête de réponse `2FA-Token`. Deux formes, gérées par `auth login` (v0.9.2, 07/10/2026) :
  - QCM (question secrète) : `connexion/doubleauth.awp` get/post ;
  - **code TOTP** si l'utilisateur a activé la validation par application d'authentification dans son compte (`data.totp = true`) : `POST restv3/ws/auth/totp`, JSON `{codeVerification}`, en-tête `2FA-Token`, 403 = code refusé — la commande demande le code à 6 chiffres.
  Dans les deux cas `cn`/`cv` sont mémorisés et la reconnexion automatique se fait ensuite sans code (`doubleAuthMemorisee: true` dans `ed_perso_session_info`). Symptôme dans Claude : « Le compte demande une double authentification » → l'utilisateur relance `auth login` dans Terminal, puis redémarre Claude Desktop (le serveur garde l'ancienne session en mémoire). Sur une version antérieure à 0.9.2, « Double auth (get) refusée (code 520/550) » = compte en TOTP.
- Vérifier une reconnexion sans code : script temporaire `PersoAuth()`, `session.token = ""`, `await auth.login(client)` — n'afficher que le compte et la présence de `cn`.

## Espace Documents (admin)

- Les documents sont publiés **compte par compte** (chaque parent a son espace ; le même document peut avoir un id différent chez chacun, un mandat SEPA peut n'exister que chez un parent). `documents.py` lit tous les comptes rattachés à l'élève et fusionne (`visible_pour`, `seulement_pour`, `ids_par_compte`) ; le téléchargement cherche l'id dans chaque compte (v0.9.1, 07/10/2026). Toute nouvelle lecture par supervision famille doit faire de même.

## Lire la messagerie du secrétariat

- Le connecteur perso ne lit que la boîte du compte connecté. La boîte EcoleDirecte du secrétariat se consulte par les notifications qu'EcoleDirecte envoie à secretariat@ (Outlook partagé, connecteur Microsoft 365 : `mailboxOwnerEmail=secretariat@…`, `sender=information@ecoledirecte.fr`) : objet et texte complet du message, mais pas les pièces jointes (« les N pièce(s) jointe(s) » à ouvrir dans EcoleDirecte).

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
- Version dans `pyproject.toml` incrémentée pour un nouvel outil ou paramètre (numéro de correctif pour un correctif).
- Fusion `--ff-only` dans `main`, push, suppression de la branche.
- Le push déclenche deux workflows GitHub Actions (déploiement Azure admin et perso) : suivre avec `gh run list --limit 2` (depuis le Mac) jusqu'à `success` (plusieurs minutes). Les écritures restent désactivées sur Azure.
- Rappeler à Rémi de **redémarrer complètement Claude Desktop** : les outils d'une conversation déjà ouverte gardent l'ancienne version.
- Toute édition de `claude_desktop_config.json` : sauvegarde horodatée avant, validation JSON après.

## Documentation à tenir à jour

- `README.md` du dépôt (tableau des outils, sections dédiées), version dans `pyproject.toml`, `package-data` si nouveaux fichiers de données.
- `openapi/ecoledirecte-wrapper.openapi.yaml` (Swagger 2.0 pour Copilot Studio) : aligner les opérations, ajouter les `definitions`, incrémenter la version, valider avec `openapi-spec-validator` (attention aux virgules dans les descriptions en style `{ … }` : les mettre entre guillemets). Supervision, dépôts, demandes, documents et messagerie restent hors de ce contrat.
- Spec du projet `claude/spec-connecteur-mcp-ecoledirecte.md` : lire, modifier, réécrire en entier (`project_write`) — statut et dernier commit en tête, authentification (§2), tableaux d'outils (§3/§4), écritures (§5), limites (§8), incidents et enseignements (§9).
- Si l'usage change, mettre à jour aussi la skill `ecoledirecte-communication-familles`.

## Skills et GitHub

Chaque skill chargée dans Claude a sa source dans le dossier `skills/` d'un dépôt :
- `edumoov-mcp` (public) : edumoov-communication-familles, edumoov-controle-rentree, maintenance-connecteur-edumoov ;
- `ecoledirecte-admin-mcp` (public) : ecoledirecte-communication-familles, ecoledirecte-identifiants-familles, ecoledirecte-parametrage, maintenance-connecteur-ecoledirecte ;
- `charlemagne-mcp` (public) : charlemagne-affectation-photos, charlemagne-import-infos-complementaires, charlemagne-import-mail-telephone ;
- `charlemagne-tools` (privé, skills nominatives) : charlemagne-facturation, charlemagne-import-emploi-du-temps, charlemagne-serveur-aplim, charlemagne-personnel-annuaire, ecoledirecte-appel-primaire, edumoov-appel, fiches-forfaits-rentree, scans-documents-eleves.

Une skill se modifie par une carte de proposition ; une fois qu'elle est enregistrée par Rémi, recopier le SKILL.md enregistré (copie synchronisée de la session) dans le dépôt, commiter et pousser, puis vérifier que les deux versions sont identiques (empreinte du corps). Une skill avec des données nominatives ou des chemins de serveur de l'école va dans `charlemagne-tools`, jamais dans un dépôt public. Vers le Mac : Desktop Commander `write_file` (créer le dossier avant ; mode `rewrite` pour remplacer un fichier existant).

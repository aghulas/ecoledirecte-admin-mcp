---
name: maintenance-connecteur-ecoledirecte
description: Modifier, tester, pousser et documenter le connecteur MCP EcoleDirecte (dépôt ~/dev/ecoledirecte-admin-mcp) : branche, tests, commit, push, déploiement Azure, OpenAPI, spec du projet.
---

# Maintenance du connecteur MCP EcoleDirecte

> Skill générique livrée avec le connecteur. Adaptez les chemins, les instances de comptes et la documentation à votre installation.

À utiliser pour toute évolution des serveurs `ecoledirecte-admin` / `ecoledirecte-perso` : nouvel outil, correctif, régénération du catalogue des paramètres, mise à jour de la doc OpenAPI.

## Où et comment travailler

- Dépôt local : `~/dev/ecoledirecte-admin-mcp` (venv `.venv`, installation éditable), qui contient les deux paquets `ecoledirecte_admin_mcp` et `ecoledirecte_perso_mcp`. Travailler sur place (Desktop Commander / terminal du Mac), jamais sur une copie dans le cloud.
- Commencer par `git fetch` + `git status -sb` : un autre poste ou outil a pu pousser entre-temps (fusion, jamais de force-push).
- Créer une branche pour un changement non trivial.
- Jamais de données d'élèves ou de familles dans un fichier versionné (lectures manuelles sous `~/Charlemagne/`). Dépôt public : aucun chemin de serveur propre à l'école (valeurs par défaut génériques, chemins réels dans la configuration locale). Aucun jeton dans les remotes (`git remote -v` masqué).
- Le connecteur ne manipule jamais de mot de passe, d'IBAN ni de BIC.
- Découvrir un endpoint : lire le JavaScript public du front (`www.ecoledirecte.com` → `chunk-*.js`, `main-*.js`, et l'admin `admin.ecoledirecte.com` → `scripts/scripts.*.js`), téléchargé sur le Mac dans un dossier temporaire hors dépôt (le cloud n'atteint pas ecoledirecte.com), supprimé après usage. API classique : `api.ecoledirecte.com/v3/….awp` (corps `data=<JSON>`) ; API REST du front (`withRestApi`) : `api.ecoledirecte.com/restv3/ws/…` (corps JSON).

## Messagerie perso (écriture)

- `ed_perso_message_ecrire` : simulation par défaut, `ED_PERSO_MESSAGERIE_ACTIF=1`, brouillon (`mode="brouillon"`) à privilégier — l'utilisateur envoie lui-même depuis sa boîte.
- Pièces jointes : `client.televerser_piece_jointe` (`POST v3/televersement.awp?verbe=post`, multipart `file` → `{unc, libelle}`), puis `files: [{id:"0", libelle, displayText, unc}]` dans le message ; fichiers sous `ED_PERSO_PJ_RACINES` (défaut `~/Charlemagne`), 5 au plus, 20 Mo, documents bancaires refusés.
- Plafonds : `ED_PERSO_MESSAGERIE_MAX_DEST` (30) pour un envoi, `ED_PERSO_MESSAGERIE_MAX_DEST_BROUILLON` (150) pour un brouillon via `plafond_destinataires`.
- Validation réelle : uniquement en brouillon, relu (`ed_perso_message_lire`, `boite="draft"`), jamais envoyé sans accord explicite de l'utilisateur.
- Modifier un brouillon (`ed_perso_brouillon_modifier`, v0.10.0) : le front réenregistre par le même POST avec **`id` ET `draftId`** = n° du brouillon (sans `id` : nouveau brouillon créé) et les **contacts complets** de l'annuaire (familles par `responsable.id`, personnels par `id`) — réenregistrer les contacts réduits de `to` **vide les destinataires**. Toujours relire après écriture : nombre de destinataires et texte.
- Supprimer un brouillon (`ed_perso_brouillon_supprimer`, v0.11.0) : `POST messages.awp?verbe=delete`, `{action: "supprimer", ids: [id], idDossier: -5, anneeMessages}` ; seule suppression autorisée par `_appel_messagerie` (dossier -5, un id) ; le test « aucune méthode publique d'écriture » garde une exception explicite (`supprimer_brouillon_brut`).
- **Jamais de message écrit au nom d'un autre compte par la supervision admin** : EcoleDirecte désactive l'envoi et les brouillons en mode supervision ; l'écriture se fait uniquement avec les identifiants du compte lui-même.

## Compte perso et authentification

- **Une instance du serveur perso par compte**, chacune avec son dossier `ED_PERSO_HOME` (config.json = identifiant, session.json = token et `cn`/`cv`, journal) ; mot de passe dans le Trousseau (service `ecoledirecte-perso-mcp`, rangé par identifiant). Exemple : `ecoledirecte-perso` (compte personnel, `~/.ecoledirecte-perso-mcp`) et `ecoledirecte-secretariat` (compte du secrétariat, `~/.ecoledirecte-secretariat-mcp`), même `command` dans `claude_desktop_config.json`. Quand le connecteur est diffusé, chacun configure ses propres identifiants.
- Changer de compte ou de mot de passe : sauvegarder ces fichiers, puis l'utilisateur lance lui-même dans Terminal `cd ~/dev/ecoledirecte-admin-mcp`, `ED_PERSO_HOME=<dossier du compte> .venv/bin/python -m ecoledirecte_perso_mcp.auth setup` puis `… auth login` (sans le préfixe, c'est le compte par défaut qui change), et relance Claude Desktop. Erreur « Identifiant ou mot de passe invalide (505) » répétée = mot de passe changé.
- Tester un compte hors Claude : script temporaire lancé avec `ED_PERSO_HOME=…` (les `SETTINGS` sont lus à l'import : un processus par compte).
- **Double authentification** : le login renvoie le code 250 et un jeton dans l'en-tête de réponse `2FA-Token`. Deux formes, gérées par `auth login` (v0.9.2) :
  - QCM (question secrète) : `connexion/doubleauth.awp` get/post ;
  - **code TOTP** si l'utilisateur a activé la validation par application d'authentification dans son compte (`data.totp = true`) : `POST restv3/ws/auth/totp`, JSON `{codeVerification}`, en-tête `2FA-Token`, 403 = code refusé — la commande demande le code à 6 chiffres.
  Dans les deux cas `cn`/`cv` sont mémorisés et la reconnexion automatique se fait ensuite sans code (`doubleAuthMemorisee: true` dans `ed_perso_session_info`). Symptôme dans Claude : « Le compte demande une double authentification » → l'utilisateur relance `auth login` dans Terminal, puis redémarre Claude Desktop (le serveur garde l'ancienne session en mémoire). Sur une version antérieure à 0.9.2, « Double auth (get) refusée (code 520/550) » = compte en TOTP.
- Vérifier une reconnexion sans code : script temporaire `PersoAuth()`, `session.token = ""`, `await auth.login(client)` — n'afficher que le compte et la présence de `cn`.

## Espace Documents (admin)

- Les documents sont publiés **compte par compte** (chaque parent a son espace ; le même document peut avoir un id différent chez chacun, un mandat SEPA peut n'exister que chez un parent). `documents.py` lit tous les comptes rattachés à l'élève et fusionne (`visible_pour`, `seulement_pour`, `ids_par_compte`) ; le téléchargement cherche l'id dans chaque compte (v0.9.1). Toute nouvelle lecture par supervision famille doit faire de même.

## Annuaire des familles et fiches anonymisées

- **Pas d'annuaire complet** dans l'admin EcoleDirecte : un compte ne se trouve que par une recherche d'au moins deux caractères (réponse d'Aplim).
- Les comptes **« XXXXXXXXXX »** (nom et prénom) sont des **fiches anonymisées** à la demande de l'école : option « Ne pas transmettre » de la rubrique « Mot de passe EcoleDirecte » de la fiche famille Charlemagne. Normaux, **à ne pas supprimer** ; la famille garde son vrai nom dans Charlemagne (pas de champ correspondant identifié dans l'export).
- La liste complète et **toute recherche composée uniquement de « x »** (de « x » à « xxxxxxxxxx ») renvoient le **code 550** : blocage **volontaire** d'Aplim pour protéger ces fiches, pas une panne. Le client reconstitue l'annuaire lettre par lettre (`_reconstituer_annuaire`, la lettre « x » est signalée et ignorée) et lève `RechercheBloqueeError` (message explicatif) sur une recherche en « x » (v0.12.2). Ne jamais signaler ces comptes à Aplim comme anomalie.

## Pièces à verser déposées par les familles

- Lecture : `ed_admin_pieces_etat` (état, verrouillé = récupéré par Charlemagne), `ed_admin_piece_telecharger` (contenu, même verrouillé : `telechargement.awp`, type `LISTE_PIECE`, `fichierId` = libellé du dépôt, ids dans le corps).
- **Collision d'identifiants** : ids d'élèves et de responsables se recouvrent, et `familledocuments` renvoie aussi des dépôts d'autres familles. Toujours filtrer `idPersonne in liste.personnes` (fait dans `documents._depots_correspondants`, v0.12.1) ; tout nouveau code sur `televersements` doit faire de même.
- Dépôt : `ed_admin_deposer_piece` (simulation vérifiée, ne remplace jamais une case remplie : déposer sur le compte de l'autre parent si la case est prise).
- **Suppression : jamais par EcoleDirecte.** `POST listePiece/<liste>/<personne>/<pièce>.awp?verbe=delete` (bouton du site famille) a renvoyé **403 avec avertissement de sécurité** sur une pièce verrouillée : ne pas retenter, ne pas recoder. Une pièce se supprime dans Charlemagne (Tables › Gestion des pièces de dossier › Liste de pièces : « refuser la pièce » ou Gestion des documents › Supprimer) ; l'effet est immédiat dans EcoleDirecte (sans attendre la synchro).

## Comptes de connexion (phase d'activation des familles, v0.14.0)

- Quatre outils admin pour une famille/un personnel qui n'arrive pas à activer son espace (`codes_connexion.py`), calqués sur la console (service `IdentifiantsUtilisateursService`) : `ed_admin_codes_connexion_lire` (`GET compteOrigineED/{type}/{id}` → `edNomUtilisateurOrigine`, `edMotDePasseOrigine`, jeton QR `at`, lecture seule), `ed_admin_codes_connexion_regenerer` (`DELETE compteOrigineED` = `reaffecteCompteOrigineED`, puis relecture), `ed_admin_compte_debloquer` (`GET` puis `DELETE blockingState`), `ed_admin_demander_changement_mdp` (`PUT compteOrigineED` = `forceUpdateMdpLogin`).
- **Type court** par `Utils.translateType` du front : élève=E, responsable=1, conjoint=2, personnel=A, professeur=P. Le paramètre d'outil `role` accepte le mot (eleve/responsable/conjoint/personnel/professeur) ou le code court.
- **`compteOrigineED` et `blockingState` restent bloqués par la route générique** (`check_allowed`, `_FORBIDDEN_PATH_PREFIXES`) : seules les méthodes dédiées du client (`lire_codes_connexion`, `regenerer_codes_connexion`, `etat_blocage_compte`, `debloquer_compte`, `demander_changement_mdp`) y accèdent, par un chemin séparé (`_appel_compte_raw`), comme `set_parametre`. Le test `test_client_exposes_no_write_helpers` recense ces écritures ; `test_forbidden_endpoints_blocked_even_in_get` doit continuer à bloquer ces endpoints par la route générique.
- **Les codes de première connexion ne transitent jamais en clair** : ni renvoyés par l'outil, ni journalisés, ni affichés dans la conversation — écrits dans un fichier local 0600 sous `ED_ADMIN_CODES_DIR` (absent sur Azure → outils inactifs). La réponse ne donne que le chemin et la présence des champs. Pour préparer un mail avec les codes : tout faire **en local sur le Mac** (script qui lit le fichier des codes et écrit le mail / la PJ PDF — `cupsfilter` sur macOS — / un `.eml`), jamais via un connecteur (le connecteur Outlook n'a d'ailleurs pas d'outil de pièce jointe, et y faire passer un code le mettrait dans l'appel et les journaux).
- Garde-fous : `ED_ADMIN_COMPTES_ACTIF=1` (jamais sur Azure) ; simulation par défaut pour les écritures (`confirm=True` après accord explicite). **La régénération supprime les associations de comptes et réinitialise identifiant + mot de passe** : à réserver aux comptes jamais activés ; ne jamais la lancer sur un compte déjà actif (dont le compte admin du connecteur). Pour un compte déjà activé : lecture des codes ou demande de changement de mot de passe.
- Le formulaire **public « mot de passe oublié »** (`api.ecoledirecte.com/mot-de-passe-oublie.awp`) envoie un lien à l'adresse/au téléphone enregistré mais est protégé par un **CAPTCHA** image (champ « Code de sécurité », `WD_ACTION_=IMAGE`) : non automatisable, écarté. Aucun envoi mail/SMS des codes côté admin (la console les affiche seulement).

## Lire la messagerie du secrétariat

- Directement : serveur `ecoledirecte-secretariat` (instance du serveur perso sur le compte du secrétariat) — `ed_perso_messages_list` (ne marque rien lu), `ed_perso_message_lire` (remet en non lu par défaut), pièces jointes listées.
- Secours : les notifications qu'EcoleDirecte envoie à la boîte mail du secrétariat (`sender=information@ecoledirecte.fr`) — objet et texte, sans les pièces jointes.

## Tests

- `.venv/bin/python -m pytest -q` : tous verts avant tout commit ; ajouter des tests sans réseau (respx, faux client) pour chaque garde-fou.
- Vérifier en réel en lecture seule (`.venv/bin/python -` avec le client) quand c'est utile ; jamais d'écriture réelle sans accord explicite de l'utilisateur.

## Catalogue des paramètres admin

- `tools/extraire_parametres.py` (télécharge le bundle `scripts/scripts.*.js` du front admin, httpx) → `ecoledirecte_admin_mcp/data/parametres_front.json`.
- Après régénération : contrôler le nombre de libellés, l'absence de faux paramètres (options de listes, textes avec espaces/parenthèses), relancer les tests.
- Intitulés lisibles : dictionnaire `INTITULES` de `parametres_catalogue.py`.

## Commit, push, déploiement

- Commit et push **uniquement quand l'utilisateur le demande**. Message en français sans accents dans le titre, corps listant les changements et la validation réelle, puis :
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: <lien de la session>
  ```
  (reprendre les lignes d'attribution indiquées par la session courante).
- Depuis une VM Cowork (dossier `~/dev` monté), git ne peut pas effacer ses fichiers temporaires sans
  l'autorisation de suppression du dossier : il laisse `.git/index.lock`, `HEAD.lock`, `tmp_obj_*` et le
  commit suivant échoue. Demander l'autorisation (`device_request_delete_permission`) ou committer et
  pousser depuis le Mac (Desktop Commander), qui a aussi les identifiants GitHub.
- Commit depuis le Mac (Desktop Commander) : l'outil peut refuser une commande dont le message de commit est écrit dedans (« Command not allowed », par exemple avec un message en heredoc contenant des balises `<div>`) — écrire le message dans un fichier temporaire (`write_file`), puis `git commit -F <fichier>`, et supprimer le fichier.
- Version dans `pyproject.toml` incrémentée pour un nouvel outil ou paramètre (numéro de correctif pour un correctif).
- Fusion `--ff-only` dans `main`, push, suppression de la branche.
- Le push déclenche deux workflows GitHub Actions (déploiement Azure admin et perso) : suivre avec `gh run list --limit 2` (depuis le Mac, sans `sleep` long : l'appel est coupé au bout de 60 s) jusqu'à `success` (plusieurs minutes). Les écritures restent désactivées sur Azure (les variables d'activation, dont `ED_ADMIN_COMPTES_ACTIF` et `ED_ADMIN_CODES_DIR`, n'y sont pas posées).
- Rappeler à l'utilisateur de **redémarrer complètement Claude Desktop** : les outils d'une conversation déjà ouverte gardent l'ancienne version.
- Toute édition de `claude_desktop_config.json` : sauvegarde horodatée avant, validation JSON après.

## Documentation à tenir à jour

- `README.md` du dépôt (tableau des outils, sections dédiées), version dans `pyproject.toml`, `package-data` si nouveaux fichiers de données.
- `openapi/ecoledirecte-wrapper.openapi.yaml` (Swagger 2.0 pour Copilot Studio) : aligner les opérations, ajouter les `definitions`, incrémenter la version, valider avec `openapi-spec-validator` (attention aux virgules dans les descriptions en style `{ … }` : les mettre entre guillemets). Supervision, dépôts, demandes, documents, messagerie et comptes de connexion restent hors de ce contrat.
- Spec du connecteur, si vous en tenez : statut et dernier commit en tête, authentification (§2), tableaux d'outils (§3/§4), écritures (§5), limites (§8), incidents et enseignements (§9).
- Si l'usage change, mettre à jour aussi la skill `ecoledirecte-communication-familles`.

## Skills

Les skills livrées avec le connecteur sont dans le dossier `skills/` du dépôt ; ce sont des éditions génériques. Une école qui les adapte (noms, adresses, comptes, chiffres de ses campagnes) range sa version dans un dépôt privé et charge celle-là dans Claude ; le dépôt public ne reçoit jamais de donnée propre à une école.

Avant tout commit, rechercher les noms d'élèves et de familles réels (liste tirée de la base, `git grep -w -F -f`), y compris dans les **tests** : des données de test doivent être inventées.

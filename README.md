# ecoledirecte-mcp (prototype)

Deux serveurs MCP vers EcoleDirecte (génériques, réutilisables pour tout établissement), APIs
internes non documentées, **en lecture seule à une exception près**
(`ed_admin_parametre_set`, voir plus bas) :

- **`ecoledirecte-admin`** — console admin (`admin.ecoledirecte.com`) :
  annuaire des comptes, classes, paramétrages, stats, synchros Charlemagne.
  Voir [`docs/cartographie-api-admin.md`](docs/cartographie-api-admin.md).
- **`ecoledirecte-perso`** — espace personnel (`www.ecoledirecte.com`) du compte
  personnel de chaque utilisateur : consultation des élèves par classe, coordonnées détaillées des
  responsables (adresse/téléphones/emails), messagerie (liste seule), agenda, RDV,
  documents, post-it. Voir
  [`docs/cartographie-api-personnel.md`](docs/cartographie-api-personnel.md).

---

## Serveur admin

Basé sur l'API interne `api.ecoledirecte.com/v3/admin/`.

**Périmètre réel** : annuaire des comptes (familles↔enfants↔classe, élèves,
profs, personnels), classes, paramétrages, statistiques de connexion, état des
synchros Charlemagne. **Pas** de factures, notes ni messages : l'API admin ne les
contient pas (voir cartographie §1 et §5).

**⚠️ Écriture** : `ed_admin_parametre_set` peut modifier UN paramètre
établissement — c'est la seule exception à la lecture seule, dans tout le
connecteur (les deux serveurs). Voir la section dédiée plus bas.

## Installation

```bash
cd ~/dev/ecoledirecte-admin-mcp
python3 -m venv .venv
./.venv/bin/pip install -e ".[dev]"
```

## Authentification (login automatique + Trousseau)

Une seule fois, dans le Terminal :

```bash
./.venv/bin/python -m ecoledirecte_admin_mcp.auth setup   # identifiant + mot de passe (saisie masquée → Trousseau)
./.venv/bin/python -m ecoledirecte_admin_mcp.auth check   # vrai login, affiche l'établissement
```

- Mot de passe : Trousseau macOS, service `ecoledirecte-admin-mcp`, jamais sur disque ni dans la config Claude.
- Identifiant : `~/.ecoledirecte-admin-mcp/config.json` (ou variable `ED_ADMIN_IDENTIFIANT`).
- Dernier token : `~/.ecoledirecte-admin-mcp/session.json` (600). Le token tourne à
  chaque appel ; si la session expire (codes 520/525) le serveur se reconnecte seul.
- Re-login automatique vérifié en réel le 16/09/2026 (token invalide → 1 reconnexion transparente).
- Si l'établissement active un jour le 3DSecure admin, le login échouera avec un
  message explicite (non géré).

## Claude Desktop

```json
"ecoledirecte-admin": {
  "command": "<chemin_vers_le_repo>/.venv/bin/ecoledirecte-admin-mcp"
}
```

## Outils (v0.2)

| Outil | Rôle |
|---|---|
| `ed_admin_session_info` | compte connecté, établissement, année scolaire |
| `ed_admin_classes_list` | niveaux et classes |
| `ed_admin_familles_search(nom)` | responsables/conjoints + enfants et classe |
| `ed_admin_eleves_search(nom)` | élèves + classe |
| `ed_admin_professeurs_list`, `ed_admin_personnels_list` | comptes profs / personnels |
| `ed_admin_entreprises_search(nom)` | tuteurs/entreprises |
| `ed_admin_parametres_get(libelles, hors_catalogue?)` | valeurs de paramètres avec intitulé, menu et rubrique (secrets masqués, base64 décodé) ; libellé inconnu du catalogue refusé avec suggestions |
| `ed_admin_parametres_catalogue(menu?, rubrique?, recherche?)` | catalogue hors ligne des ~650 paramètres de l'admin (sommaire sans filtre) |
| `ed_admin_parametrage_lire(menu, rubrique?)` | valeurs actuelles de toute une rubrique ou tout un menu de l'admin, d'un coup |
| `ed_admin_stats_connexions` | connexions par profil et période |
| `ed_admin_synchros_etat` | derniers transferts Charlemagne → ED |
| `ed_admin_emploi_du_temps(enseignant, date_debut, date_fin?)` | emploi du temps d'un enseignant tel qu'EcoleDirecte l'affiche (supervision en lecture, `ED_ADMIN_EDT_ACTIF=1`) — vérification d'un import Charlemagne |
| `ed_admin_connecteurs_list(actifs_seulement?, recherche?, code?)` | applis partenaires (« Mes Applis ») : état réel par public lu dans les paramètres (`isActifEtab` de l'API n'est pas fiable), activée par défaut, adaptée à l'école, données transmises à l'éditeur, contraintes ; `code` = détail |
| `ed_admin_connecteur_activer(code, actif, publics?, confirm?)` | **ÉCRITURE** — (dés)active une appli partenaire pour tous ses publics ou certains ; simulation par défaut |
| `ed_admin_activites_list` | activités de suivi (cantine, étude…) |
| `ed_admin_referentiels_get` | sanctions, catégories de suivi, tags CDT, salles… |
| `ed_admin_activation_comptes(classe?, inclure_noms?)` | activation des comptes par classe : élèves sans aucun parent connecté, responsables jamais connectés, taux |
| `ed_admin_parametre_set(libelle, valeur, confirm?)` | **ÉCRITURE** — modifie un paramètre établissement. Sans `confirm=True` : aperçu seulement, rien n'est écrit |
| `ed_admin_deposer_piece(id_eleve, fichier, confirm?, piece?, compte_id?)` | **ÉCRITURE** — dépose un PDF dans une liste de pièces à verser, au nom de la famille (supervision). `compte_id` : compte parent précis |
| `ed_admin_pieces_etat(id_eleve, compte_id?)` | état des pièces à verser d'une famille : déposé ou non, date, verrouillé (récupéré par Charlemagne), liste autorisée ou non |
| `ed_admin_documents_famille(id_eleve, compte_id?, archive?)` | documents publiés dans l'espace « Documents » d'une famille (factures, administratifs, notes, vie scolaire…) : rubrique, intitulé, date, signature demandée — supervision en lecture seule, rien n'est téléchargé ; les documents étant publiés **compte par compte**, tous les comptes de la famille sont lus et fusionnés (`visible_pour`, `seulement_pour`, `ids_par_compte`) sauf `compte_id` précisé |
| `ed_admin_documents_ecole(classe?, archive?)` | documents publiés par l'école dans l'espace Documents, regroupés par intitulé/date avec les classes où ils sont visibles (une famille sans fratrie interrogée par classe, tous ses comptes) — pour retrouver une circulaire publiée **sans notification** |
| `ed_admin_document_telecharger(id_eleve, document_id, compte_id?, archive?)` | télécharge en PDF un document publié dans l'espace Documents d'une famille vers `ED_ADMIN_DOCUMENTS_DIR` (droits 600, jamais écrasé ; cherche le document dans chaque compte de la famille) ; refuse les documents bancaires (mandat SEPA, RIB) |
| `ed_admin_demande_activites(id_eleve, activites?, regime?, confirm?)` | **ÉCRITURE** — demande de modification des activités (jours L/M/J/V) et/ou du régime, validée ensuite dans Charlemagne |
| `ed_admin_demande_telephones(compte_id, confirm?)` | **ÉCRITURE** — reformate les téléphones d'une famille (« 06 12 34 56 78 ») par demande de modification des coordonnées |

## Garde-fous (testés, `pytest`)

- Seul `verbe=get` peut partir du client, **sauf `set_parametre`** (la seule
  méthode d'écriture, explicitement isolée — voir ci-dessous).
- Bloqués même en lecture : `compteOrigineED`, `supervisionmobile`, `supervision`
  (identifiants d'autres utilisateurs / usurpation de session), gestion des logins,
  `banques`, fichiers.
- `badge` et `photo` retirés des fiches par défaut (`include_sensitive_fields=True` pour les obtenir).
- Paramètres ressemblant à des secrets (clés, certificats, mots de passe, IBAN…) masqués.
- Aucun token ni mot de passe dans les messages d'erreur.

### ⚠️ Écriture : six outils seulement

| Outil | Depuis | Activation | Détails |
|---|---|---|---|
| `ed_admin_parametre_set` | 16/09/2026 | toujours `confirm=True` | ci-dessous et `docs/cartographie-api-admin.md` §7 |
| `ed_admin_deposer_piece` | 23/09/2026 | `ED_ADMIN_DEPOT_ACTIF=1` | §8 ; listes : `ED_ADMIN_DEPOT_LISTES` (libellés, débuts de libellés ≥ 6 lettres et/ou numéros, ex. `1|2|7` ou `Fiches Rentrée|Justificatifs`) ; simulation vérifiée en lecture seule (`verifier=True`) |
| `ed_admin_demande_activites` | 30/09/2026 | `ED_ADMIN_DEMANDES_ACTIF=1` | §9 ; types : `ED_ADMIN_DEMANDES_TYPES` ; codes : `ED_ADMIN_DEMANDES_ACTIVITES` |
| `ed_admin_demande_telephones` | 30/09/2026 | `ED_ADMIN_DEMANDES_ACTIF=1` | §9 |
| `ed_admin_connecteur_activer` | 02/10/2026 | `ED_ADMIN_CONNECTEURS_ACTIF=1` | §10 ; seulement les applis « universelles » ; écrit `Sites/Connecteur/…/Actif` (et le RNE d'une appli CAS) comme l'écran Connecteurs ; refuse l'activation si clé d'API, activation par classe ou paramètres complémentaires |
| `ed_admin_demande_coordonnees` | 30/09/2026 | `ED_ADMIN_DEMANDES_ACTIF=1` | §9 ; type `coordonnees` : adresse, et pour chaque parent nom, mails, téléphones, profession, société, CSP ; jamais la banque |

Communs aux six : simulation par défaut, `confirm=True` seulement après accord explicite en
conversation, activation par variable d'environnement (jamais sur Azure), journal local.
**Aucun outil MCP** ne touche au mode de règlement ni aux coordonnées bancaires : l'assistant ne
doit jamais voir ni saisir un IBAN.

### Mode de règlement / RIB : commande à lancer soi-même (30/09/2026)

```bash
.venv/bin/python -m ecoledirecte_admin_mcp.rib --compte <id> --etat          # mode actuel, IBAN masqué
.venv/bin/python -m ecoledirecte_admin_mcp.rib --compte <id> --rib RIB.pdf   # passage / changement de prélèvement
.venv/bin/python -m ecoledirecte_admin_mcp.rib --compte <id> --cheque        # passage au chèque
```

À lancer à la main dans un Terminal (refusée sinon) : l'IBAN (saisi deux fois, clé contrôlée) et
le BIC sont tapés par la personne ; tout ce qui est affiché ou journalisé
(`~/.ecoledirecte-admin-mcp/demandes_mode_reglement.csv`) est masqué (`FR76 •••• •••• 189`).
Un nouvel IBAN exige le RIB (PDF/JPEG/PNG ≤ 5 Mo), comme sur le site. Récapitulatif, puis envoi en
tapant `ENVOYER`. La demande est validée par le secrétariat dans Charlemagne (mandat SEPA pour un
passage au prélèvement). Protocole : `docs/cartographie-api-admin.md` §9.

#### Catalogue des paramètres (v0.5)

`GET parametres` renvoie « 0 » **sans erreur** pour un libellé qui n'existe pas
(vérifié le 30/09/2026 : `Zzz/Inexistant/Actif` → `"0"`). Une faute de frappe ou
un accent manquant donne donc une valeur plausible mais fausse. Le catalogue
`ecoledirecte_admin_mcp/data/parametres_front.json` (~650 libellés + 26 motifs
dynamiques), relevé dans le JavaScript public du front admin, sert à :

- refuser en lecture (`ed_admin_parametres_get`) et en écriture
  (`ed_admin_parametre_set`, avant tout appel réseau) les libellés inconnus, avec
  suggestions (`Sites/Eleves/Actif` → `Sites/Elèves/Actif`) ;
- donner à chaque paramètre un intitulé et son emplacement dans l'admin
  (menu « Paramétrages généraux / familles / élèves / professeurs / personnels /
  entreprises » › rubrique), pour lire une rubrique entière
  (`ed_admin_parametrage_lire`) ;
- décoder / encoder les valeurs stockées en base64 (adresse et présentation de la
  page contact, textes des pré-inscriptions).

`certain: false` marque les libellés que le front construit pour plusieurs
profils (`"Sites/" + realTypeUser + ...`) : ils peuvent ne pas exister pour l'un
d'eux. Les indices d'établissement sont ramenés à `Etablissement_0`.
Constaté le 30/09/2026 : le serveur semble ignorer les accents dans les libellés
(`Sites/Eleves/Actif` suit `Sites/Elèves/Actif`) ; le catalogue garde
l'orthographe du front.

Régénérer après une évolution de l'admin EcoleDirecte :

```bash
./.venv/bin/python tools/extraire_parametres.py            # télécharge le bundle courant
./.venv/bin/python tools/extraire_parametres.py --bundle scripts.js
```

#### `ed_admin_parametre_set`

- Modifie UN paramètre établissement (`POST parametres.awp?verbe=post`, même
  endpoint que l'interface admin elle-même). Détails techniques et méthode de
  cartographie (lecture statique du JS du front, aucun appel d'écriture
  déclenché avant l'implémentation) : voir `docs/cartographie-api-admin.md` §7.
- **Sans `confirm=True` : aperçu seulement**, rien n'est écrit — valeur actuelle
  vs proposée. Il faut rappeler explicitement avec `confirm=True` pour écrire
  pour de vrai ; l'outil relit alors immédiatement le paramètre pour confirmer
  que le changement a pris.
- Refusé d'office (avant tout appel réseau) pour les paramètres secrets ou pour
  ceux que l'interface admin elle-même exclut de l'édition générique (banque,
  connecteurs partenaires, délais réglementaires…).
- Règle de fonctionnement (pas seulement garde-fou logiciel) : Claude demande
  toujours l'accord explicite de la personne responsable du connecteur en
  conversation avant un appel réel avec
  `confirm=True`.
- Aucun environnement de test séparé utilisé (décision explicite) : premiers
  essais à faire directement sur l'établissement réel, sur un paramètre à
  faible impact et réversible.

```bash
./.venv/bin/pytest
```

---

## Serveur espace personnel (`ecoledirecte-perso`)

Chaque utilisateur configure **son propre compte personnel** EcoleDirecte (personnel
administratif ou enseignant) : identifiant dans `~/.ecoledirecte-perso-mcp/config.json`,
mot de passe dans le Trousseau macOS. Les messages partent sous son nom et ses brouillons
sont dans sa boîte. Ne pas utiliser le compte d'une autre personne.
API `apip.ecoledirecte.com/v3/` (site www.ecoledirecte.com).

### Connexion (login interactif, une fois)

La double authentification EcoleDirecte pose une **question secrète** : impossible
à résoudre par un serveur sans intervention. On la fait une fois en interactif, les
jetons `cn`/`cv` sont mémorisés, puis le serveur se reconnecte seul.

```bash
cd ~/dev/ecoledirecte-admin-mcp
./.venv/bin/python -m ecoledirecte_perso_mcp.auth login
```

- Demande l'identifiant, puis le mot de passe (Trousseau, saisie masquée), puis
  la question de sécurité si EcoleDirecte la pose (réponds au numéro proposé).
- Mot de passe : Trousseau macOS, service `ecoledirecte-perso-mcp`.
- Jetons + `cn`/`cv` : `~/.ecoledirecte-perso-mcp/session.json` (600).
- Pour changer de compte ou après un changement de mot de passe : mettre de côté
  `config.json` et `session.json` de `~/.ecoledirecte-perso-mcp/`, lancer
  `auth setup` (identifiant + mot de passe) puis `auth login`, et redémarrer le
  client MCP. Une erreur « identifiant ou mot de passe invalide (505) » répétée
  signale un mot de passe changé.

### Précautions importantes

- **Son propre compte uniquement** : chaque utilisateur du connecteur utilise ses
  propres identifiants ; jamais le compte d'un tiers.
- **Jeton tournant** : une session EcoleDirecte ouverte dans un navigateur sur le
  même compte au même moment casse les jetons de l'autre côté. Éviter l'usage
  simultané.
- **Aucune ouverture de message** : les outils listent la messagerie mais
  n'ouvrent jamais un message (ce qui le marquerait « lu » chez le destinataire) —
  bloqué dans `client.py`, testé.
- **`ed_perso_eleve_coordonnees_famille`** renvoie des données personnelles
  directement identifiantes sur des tiers (adresse/téléphone/email de parents) :
  à réserver à un besoin de contact légitime, jamais à de la collecte systématique.

### Outils (`ecoledirecte-perso`)

| Outil | Rôle |
|---|---|
| `ed_perso_session_info` | compte connecté, double auth mémorisée ? |
| `ed_perso_classe_eleves(id_classe)` | élèves d'une classe (identité, régime, responsables **sans** coordonnées à ce niveau) |
| `ed_perso_eleve_coordonnees_famille(id_eleve)` | **coordonnées des responsables** d'un élève : adresse, téléphones, emails |
| `ed_perso_niveaux_list` | référentiel niveaux/classes |
| `ed_perso_professeurs_list` | annuaire enseignants |
| `ed_perso_messages_list(boite)` | messagerie en liste (received/sent/archived) |
| `ed_perso_message_lire(id_message, boite?, remettre_non_lu?)` | ouvre UN message (objet, correspondants, texte, pièces jointes listées) — uniquement à la demande explicite ; remis en « non lu » s'il l'était |
| `ed_perso_contacts_rechercher(type, nom?)` | annuaire de la messagerie : familles (par nom d'élève, une ligne par parent) ou personnels |
| `ed_perso_message_ecrire(sujet, texte, destinataires, mode?, confirm?, pieces_jointes?, plafond_destinataires?)` | **ÉCRITURE** — brouillon (`mode="brouillon"`, à privilégier) ou envoi ; simulation par défaut, `ED_PERSO_MESSAGERIE_ACTIF=1`, plafond `ED_PERSO_MESSAGERIE_MAX_DEST` (30) ; en brouillon, `plafond_destinataires` jusqu'à `ED_PERSO_MESSAGERIE_MAX_DEST_BROUILLON` (150) ; responsables d'une fratrie comptés une fois ; `pieces_jointes` : 5 fichiers au plus (pdf, png, jpg, docx ; 20 Mo) sous `ED_PERSO_PJ_RACINES` (défaut ~/Charlemagne), documents bancaires refusés, téléversés via `televersement.awp` puis référencés dans `files` |
| `ed_perso_agenda` | événements agenda |
| `ed_perso_carnet_liaison_non_lus` | compteurs non lus du cahier de liaison |
| `ed_perso_rendez_vous` | sessions et RDV individuels |
| `ed_perso_documents(archive?)` | documents de l'établissement |
| `ed_perso_postits` | post-it / tableau d'affichage |

### Claude Desktop

```json
"ecoledirecte-perso": {
  "command": "<chemin_vers_le_repo>/.venv/bin/ecoledirecte-perso-mcp"
}
```

## Déploiement Azure (streamable-http)

Les deux serveurs vivent dans **ce même dépôt** (deux packages Python distincts,
`ecoledirecte_admin_mcp` et `ecoledirecte_perso_mcp` — voir `pyproject.toml`) mais
sont déployés comme **deux Web Apps Azure séparées**, chacune avec sa propre
authentification Entra ID (scopes `EcoleDirecteAdmin.Read` / `EcoleDirectePerso.Read`,
jamais partagés). Le Deployment Center des deux Web Apps pointe donc vers le même
dépôt/branche — c'est le Startup Command qui choisit le module à lancer.

Variables d'environnement nécessaires (voir le dépôt partagé `mcp-entra-auth`) :
`MCP_ENTRA_TENANT_ID`, `MCP_ENTRA_APP_ID_URI`, et optionnellement
`MCP_ENTRA_ALLOWED_GROUP_ID` / `MCP_ENTRA_PUBLIC_URL`.

| Web App Azure | Module | Port | Startup Command (Configuration → Stack settings) |
|---|---|---|---|
| `ecoledirecte-admin-mcp-fontainebleau` | `ecoledirecte_admin_mcp` | `8001` (`WEBSITES_PORT=8001`) | `python -m ecoledirecte_admin_mcp --transport streamable-http --host 0.0.0.0 --port 8001` |
| `ecoledirecte-perso-mcp-fontainebleau` | `ecoledirecte_perso_mcp` | `8002` (`WEBSITES_PORT=8002`) | `python -m ecoledirecte_perso_mcp --transport streamable-http --host 0.0.0.0 --port 8002` |

Ports fixés dans le code (`argparse --port` de chaque `__main__.py`), pas dans cette
doc — en cas de doute, le code fait foi.


### 10. Applications partenaires (« Mes Applis », 02/10/2026)

Relevé dans le front (`ConnecteurDetailDirectiveCtrl`) : l'activation d'une appli n'a pas
d'endpoint propre, ce sont des paramètres établissement écrits par le POST `parametres`.
Clé = format fourni par l'API pour chaque appli (`formatCleParametreSansCible`,
`formatCleParametreMultiCible`, `formatCleParametreSpecifique`, avec `%CODE%`, `%IDETAB%`,
`%CIBLECOURT%`) + `Actif` ; un paramètre par public (F, E, P, A) si l'appli s'active par
public, par établissement si elle s'active par établissement (sinon établissement 0). Pour
une appli CAS activée par établissement, le front renseigne aussi `…/RNE`. Le champ
`isActifEtab` est faux pour toutes les applis : l'état réel est dans les paramètres. Beaucoup
d'applis sont activées par défaut par Aplim (`activerParDefaut`). Les applis non
« universelles » (ESIDOC, CATER, SACOCHE, VOLTAIRE, ALISE, ARD, SCOLACONCEPT) ont un écran
codé en dur : hors périmètre.

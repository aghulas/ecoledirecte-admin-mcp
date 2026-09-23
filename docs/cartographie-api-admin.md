# Cartographie — API admin EcoleDirecte (admin.ecoledirecte.com)

Relevé du 15/09/2026, compte admin d'un établissement de test (RNE 0000000A),
front admin v3.8.4-105. Méthode : lecture du JavaScript public du
front (`/scripts/scripts.41ac2ecf.js`, AngularJS) + observation des appels réels
dans le navigateur de Claude, session ouverte par la personne responsable du
connecteur. Aucune écriture effectuée.

## 1. Ce que la console admin est (et n'est pas)

La console admin sert à **paramétrer** EcoleDirecte et à **superviser les comptes**.
Les données métier (factures, notes, absences, messages) viennent de Charlemagne
par synchronisation et sont consultées sur www.ecoledirecte.com, pas ici.

| Besoin initial | Disponible dans l'API admin ? |
|---|---|
| Élèves & familles | Oui, annuaire des comptes : nom, prénom, civilité, responsable/conjoint, enfants + classe, état de connexion. **Pas** d'email, téléphone ni adresse. |
| Facturation / compta | Non. Seulement des paramètres (`Sites/Familles/Comptabilité/Actif` = 0 : la compta n'est même pas affichée côté familles). Source réelle : Charlemagne. |
| Notes | Non. Seulement les paramètres d'affichage des notes. |
| Messagerie | Non. Seulement les paramètres (qui peut écrire à qui, notifications). |

## 2. Protocole

- Base : `https://api.ecoledirecte.com/v3/admin/`
- L'intercepteur `ProcessRequestInterceptor` réécrit **tous** les appels :
  `POST <base><chemin>.awp?verbe=<get|post|put|delete>&<query>`
- `Content-Type: application/x-www-form-urlencoded`, corps `data=<JSON>` (le JSON
  contient aussi `"token"`), header `x-token: <token>`.
- Réponse : `{"code": 200, "token": "<nouveau>", "host": "HTTPxxx", "data": {...}}`.
- **Le token tourne** : chaque réponse en fournit un nouveau (`updateToken`).
- Codes : 520/525 = session expirée, 403 = interdit, ≥ 400 = erreur.
- Encodage URL complet du corps accepté (testé), même si le front n'échappe que `% & +`.
- Autres hôtes vus dans le code : `api13.ecoledirecte.com` (dev/staging), `wstest.ecoledirecte.com` (futur).

## 3. Authentification

- `POST v3/admin/login.awp` avec `data={"identifiant","motdepasse","codeSecure"}`.
- 200 → `token` + `data` {codeOgec, email, portable, type, etablissements[{id, code, RNE, libelle, typeetb}], parametragesRNE{anneeScolaireDebut/Fin, dateServeurAujourdhui...}, isModeRestreint, parametrageMultiEtab}.
- 202 → étape 3DSecure (`POST login/3DSecure.awp`), 505 → identifiants invalides, 506 → code invalide.
- Paramètres sécurité de l'établissement au 15/09/2026 : `Sites/Admin/3DSecure/Actif` = 0,
  `Connexion/Auth2FactorFE/Actif` = 0, `Sites/2FATOTP/A/Actif` = 0, `Sites/2FATOTP/P/Actif` = 0
  → login automatique possible (mot de passe dans le Trousseau).

## 4. Endpoints relevés

Confirmés en lecture sur données réelles (✅) ou vus seulement dans le code (📄).

| Chemin (verbe) | Contenu | Statut |
|---|---|---|
| `classes` (get) | établissement → niveaux → classes {id, code, libelle, idGroupe} | ✅ |
| `utilisateurs/{familles\|eleves\|professeurs\|personnels\|entreprises}?filterSearch=` (get) | annuaire (voir §1) ; familles : enfants[{nom, prenom, idClasse, libelleClasse}] ; champs `badge`, `photo`, `otp`, `dejaConnecte`, `dateModifMdp` | ✅ |
| `parametres` (get, `data.parametres=[{libelle}]`) | valeurs `{libelle, valeur, encoded}` | ✅ |
| `stats/ecoledirecte` (get) | connexions par profil/mois/jour/heure | ✅ |
| `synchrosED/{codeOgec}` (get) | état des transferts Charlemagne par module | ✅ |
| `connecteurs` (get) | 76 applis partenaires, catégories, RGPD | ✅ |
| `activites/familles` (get) | activités de suivi (matin/après-midi) | ✅ |
| `portesMonnaie/commun` (get) | porte-monnaie | ✅ (vide) |
| `carnetCorrespondance/typesSanction`, `.../categoriesSuivi` (get) | référentiels | ✅ (vides) |
| `cahierDeTexte/tags` (get) | tags CDT | ✅ (vide) |
| `LSU/CompNumeriques/classes` (get) | classes/profs compétences numériques | ✅ (vide) |
| `salles` (get) | salles | ✅ (vide) |
| `ent` (get) | config ENT | ✅ code 225 (non activé) |
| `v3/Admin/0/espacestravail[...]` | espaces de travail ENT (get/put/delete) | 📄 |
| `aidesenligne/Admin`, `archivageCDT`, `connecteurEdunao/refresh`, `connecteurVoltaire/refresh`, `restv3/ws/montessori/referentiel` | divers | 📄 |

### Endpoints volontairement bloqués par le connecteur

| Chemin | Pourquoi |
|---|---|
| `compteOrigineED/{type}/{id}` (get) | renvoie **identifiant + mot de passe de première connexion** d'une famille/élève |
| `supervisionmobile?id=&type=` (post) | renvoie identifiant + mot de passe « supervision mobile » + jeton QR |
| `supervision.awp?id=&type=&n=&version=` (formulaire POST) | ouvre l'espace EcoleDirecte **à la place** d'une famille/élève |
| `loginsED/{type}` (put/delete), `blockingState/{type}/{id}` (get/delete), `logins/{codeOgec}` (put), `loginCreation`, `reinitLogin` | gestion des mots de passe / comptes |
| `banques`, `migrationPaiementv2` | coordonnées bancaires / paiements |
| `televersement.awp`, `telechargement.awp`, `purgerEnt`, `messagerieED` (delete/migrate) | fichiers, purges |

## 5. Constats sur données réelles (16/09/2026)

- `utilisateurs/familles` et `utilisateurs/eleves` avec `filterSearch` **vide** renvoient
  tout l'annuaire (529 comptes responsables, 403 élèves) — la contrainte « 2 caractères
  minimum » n'existe que dans le front. `%` donne le même résultat, `*` ne renvoie rien.
- Aucun compte famille ni élève ne s'est encore connecté (`dejaConnecte` = false partout,
  stats : uniquement des connexions « Personnel » les 14–15/09) ; 0 connecteur activé :
  déploiement EcoleDirecte tout récent.
- 1 élève sans classe (`idClasse` = 0). Tous les comptes famille sont de type `responsable`
  et rattachés à au moins un enfant ; ~2 comptes responsables par élève.
- `familles[].enfants` ne contient pas l'id de l'élève : rapprochement sur nom + prénom + classe.
- Re-login automatique vérifié (token invalide → reconnexion transparente).

## 6. Pistes pour étendre (notes, messagerie, factures)

1. **Compte personnel sur www.ecoledirecte.com** (profil `A`/personnel) : fait,
   voir cartographie-api-personnel.md et le serveur `ecoledirecte-perso`.
2. **Supervision** : techniquement possible (session ouverte en tant que famille)
   mais accès tracé, et lire un message peut le marquer « lu » chez la famille.
   Écartée pour la lecture (notes, messagerie). **Levée le 23/09/2026 pour un
   seul usage : le dépôt de pièces à verser** — voir §8.
3. **Factures** : la base Charlemagne consolidée existante reste la bonne source.

## 7. Écriture — exception n°1 : `set_parametre` (16/09/2026)

À la demande explicite de la personne responsable du connecteur, une SEULE capacité d'écriture a été ajoutée,
après cartographie statique du front (lecture du bundle JS admin, aucun appel
d'écriture réel déclenché avant l'implémentation) :

- Service Angular du front : `ParametresService` (module `edadminApp.Parametres`).
  - `getValueParam(tabParametres)` → `GET parametres` avec `data={parametres:[{libelle}]}`
    (= ce que fait déjà `get_parametres`).
  - `saveParams(tabParametres)` → **`POST parametres`** avec `data={parametres:[...]}`
    — **le tableau complet des entrées concernées**, avec le champ `valeur` modifié
    sur l'entrée ciblée. Pas d'endpoint dédié par paramètre : on relit l'entrée
    complète, on modifie `valeur`, on repost l'entrée telle quelle.
  - `enregistrerParametres(tabParametresForWebDev, tabParametres)` : fait ce
    rapprochement lecture→mutation→saveParams côté front ; on reproduit la même
    logique côté connecteur dans `EcoleDirecteAdminClient.set_parametre`.
  - `listeParametres` exclut elle-même de l'édition générique une liste de
    paramètres sensibles (réglements en ligne/banque, TPE, clés API de
    connecteurs partenaires — CATER, Esidoc, PearlTrees, EduMalin, Tabuleo —,
    délais réglementaires Notes/Moyennes/Appréciations/LSUN, validité mot de
    passe, nb de post-it/agenda, version API messagerie, droits ENT). Reprise à
    l'identique côté connecteur (`_FRONT_EXCLUDED_PARAM_MARKERS`), en plus du
    filtre `is_secret_param` déjà existant pour la lecture.

- Design du connecteur (`ed_admin_parametre_set(libelle, valeur, confirm=False)`) :
  - Refuse d'office (avant tout appel réseau d'écriture) les paramètres secrets
    ou exclus par le front lui-même.
  - Sans `confirm=True` : lecture seule, renvoie juste un aperçu (valeur actuelle
    vs proposée) — **rien n'est écrit**.
  - Avec `confirm=True` : écrit (`verbe=post`), puis **relit immédiatement** le
    paramètre pour confirmer que la valeur a bien changé (champ `coherent`).
  - C'est la SEULE méthode d'écriture de tout le client ; elle ne passe jamais
    par `check_allowed` (qui continue de bloquer tout non-GET pour toutes les
    autres méthodes).
  - Claude doit toujours redemander l'accord explicite de la personne
    responsable du connecteur en conversation
    avant tout appel réel avec `confirm=True`, quel que soit le contexte —
    règle de fonctionnement, pas seulement garde-fou logiciel.

- Pas d'environnement de test/staging utilisé (décision explicite de la personne
  responsable du connecteur) :
  premiers essais réels à faire directement sur l'établissement, sur un
  paramètre à faible impact et facilement réversible, avec relecture immédiate.

- 12 tests dédiés (respx, aucun réseau réel) : détection secrets/exclusions,
  aperçu sans écriture, forme exacte de l'écriture (verbe=post, jeton, corps),
  relecture de confirmation, code d'erreur d'écriture, garde-fou "pas d'autre
  méthode d'écriture" mis à jour pour n'autoriser que `set_parametre`.


## 8. Écriture — exception n°2 : dépôt de pièces à verser (23/09/2026)

**Besoin** : déposer dans EcoleDirecte les fiches papier « Choix des forfaits »
scannées par le secrétariat, une par élève, dans la liste de pièces à verser
« Fiches Rentrée ». Ces listes sont créées dans **Charlemagne Administratif**
(tables `COM_LISTE_PIECE`, `INS_PIECES_DOSSIER`, `COM_LIEN_PIECE_PERSONNE`) et
publiées sur EcoleDirecte ; **seul l'espace famille permet d'y téléverser**
(aucun écran admin ni personnel ne le permet). Les dépôts remontent ensuite dans
Charlemagne (`COM_PIECE_RECU` état « Reçue », fichier indexé en GED
`ADM_GED_INDEX`) — vérifié le 23/09/2026 : 31 dépôts → 31 lignes.

**Décision** : lever l'exclusion de la supervision (§6) *pour ce seul usage*,
à la demande explicite de la personne responsable du connecteur. Un dépôt de
document est une action attendue de la famille, sans lecture de sa messagerie
ni autre effet de bord. Chaque supervision reste tracée côté EcoleDirecte au
nom du compte admin.

**Flux** (relevé par lecture des fronts admin AngularJS et famille Angular) :

1. `POST v3/admin/supervision.awp?id=<compte>&type=<1 responsable|2 conjoint>&n=<NOM[:3]>&version=`
   — formulaire `token=<jeton admin>` (directive `webDevAffichePage`) →
   redirection `www.ecoledirecte.com/loginExterne?atoken=…&i=…`.
2. `POST v3/loginexterne.awp?verbe=post`, `data={"aToken":…,"i":…}` → en-têtes
   `X-Code: 200` et `X-Token` (jeton famille).
3. `POST v3/familledocuments.awp?archive=&verbe=get` → `data.listesPiecesAVerser`
   `{listesPieces, pieces, personnes, televersements}`.
4. `POST v3/televersement.awp?verbe=post&mode=DOCUMENTS` (multipart, en-tête
   `X-Token`) : `file` + `idListePiece`, `idPiece`, `idPersonne` **et** un champ
   `data` = JSON de ces trois paramètres (ajouté par `onSending` du composant
   Dropzone ; sans lui → code **512**). Limite du site : 10 Mo, PDF/JPEG/PNG.
5. Relecture de (3) : le dépôt doit apparaître dans `televersements`
   (`libelle` du type `1_<idEleve>_1_<n>.pdf`).

`idPersonne` = id élève EcoleDirecte = `IDELEVE` Charlemagne (identiques).
Une supervision peut invalider la session admin (session unique par compte) :
le module se reconnecte automatiquement via le Trousseau et réessaie une fois.

**Implémentation** : `depot_pieces.py` (outil MCP `ed_admin_deposer_piece`) et
`depot_lot.py` (dépôt par classe en ligne de commande). Chemin d'écriture
séparé : le client de lecture (`client.py`) bloque toujours `supervision`,
`televersement` et `telechargement`.

**Garde-fous** :
- simulation par défaut (`confirm=False`) : aucune supervision, aucun envoi ;
- écriture seulement si `ED_ADMIN_DEPOT_ACTIF=1` (jamais sur Azure) ;
- PDF réel (en-tête `%PDF-`) ≤ 10 Mo, situé sous `ED_ADMIN_DEPOT_RACINE` ;
- liste autorisée seulement (`ED_ADMIN_DEPOT_LISTES`, défaut « Fiches Rentrée ») ;
- ne remplace jamais un dépôt existant, ne supprime rien, ne signe rien,
  ne touche pas à la messagerie ;
- par lot : tout fichier non rapproché ou ambigu est signalé et jamais déposé ;
  relance idempotente ;
- journal local `~/.ecoledirecte-admin-mcp/depots_pieces.csv` (sans jeton) +
  bilan CSV par classe.

**Tests** : `tests/test_depot_pieces.py` (17 tests, aucun réseau) — fichier
hors racine / traversée / non-PDF / faux PDF / trop gros refusés, écriture
désactivée par défaut, liste non autorisée refusée, dépôt existant détecté,
rapprochement (ambiguïté, doublon, nom non conforme), simulation sans
supervision, `confirm=True` refusé si inactif.

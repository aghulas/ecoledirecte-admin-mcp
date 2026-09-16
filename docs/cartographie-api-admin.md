# Cartographie — API admin EcoleDirecte (admin.ecoledirecte.com)

Relevé du 15/09/2026, compte admin de l'établissement 0000000X (l'établissement,
[ville]), front admin v3.8.4-105. Méthode : lecture du JavaScript public du
front (`/scripts/scripts.41ac2ecf.js`, AngularJS) + observation des appels réels
dans le navigateur de Claude, session ouverte par [prénom]. Aucune écriture effectuée.

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

1. **Compte personnel sur www.ecoledirecte.com** (profil `A`/personnel) : l'API
   « classique » `v3/...` documentée par la communauté (EduWireApps/ecoledirecte-api-docs)
   — à cartographier avec un vrai compte personnel de l'école.
2. **Supervision** : techniquement possible (session ouverte en tant que famille)
   mais accès tracé, et lire un message peut le marquer « lu » chez la famille.
   Écartée pour l'instant.
3. **Factures** : la base Charlemagne consolidée existante reste la bonne source.

# Cartographie — API espace personnel (www.ecoledirecte.com)

Relevé du 16/09/2026, compte **personnel** (secrétariat) de l'école l'établissement,
`typeCompte = A`, id 18 (Mme A. COUTOULY). Méthode : connexion faite par la
personne dans le navigateur de Claude, puis observation des appels que l'app
émet elle-même (aucun mot de passe ni jeton lu ou affiché ; aucun message ouvert,
donc rien marqué « lu »).

## 1. Différences avec l'API admin

| | admin.ecoledirecte.com | www.ecoledirecte.com (perso) |
|---|---|---|
| Hôte API | `api.ecoledirecte.com/v3/admin/` | **`apip.ecoledirecte.com/v3/`** |
| Front | AngularJS (ancien) | Angular récent (SPA, chunks) |
| Chemin | `<action>.awp` | `<type>/<id>/<action>.awp` (ex. `personnels/18/…`) ou global |
| Contenu | annuaire + paramétrages | messagerie, agenda, RDV, documents, consultation élèves |

Point clé : la **consultation des élèves** (`classes/{id}/eleves`) donne les
coordonnées (parents, contacts) que l'API admin n'exposait pas.

## 2. Protocole (identique à l'admin, autre hôte)

- `POST https://apip.ecoledirecte.com/v3/<chemin>.awp?verbe=get&v=4.101.4&<params>`
- Headers : `Content-Type: application/x-www-form-urlencoded`, `X-Token: <token>`,
  `Accept: application/json`.
- Corps : `data=<JSON>` (souvent `{}` ou `{"anneeMessages":"2026-2027"}`).
- Réponse : `{code, token, data}`. **Le token tourne à chaque appel** — il faut
  toujours réutiliser le dernier reçu (un jeton déjà consommé → `code 520 "Token
  invalide"`). Contrainte forte : impossible de faire tourner en parallèle nos
  appels et ceux d'une session navigateur active sur le même compte.

## 3. Authentification (à implémenter — non capturée ici)

Connexion faite manuellement par la personne. Flux standard EcoleDirecte
(documenté par la communauté EduWireApps) :
1. `GET /v3/login.awp?gtk=1` → cookie `GTK`, à renvoyer en header `X-Gtk`.
2. `POST /v3/login.awp` `data={"identifiant","motdepasse","isReLogin":false,"uuid":""}`.
3. Si `code 250` → double authentification (QCM) : `GET/POST /v3/connexion/doubleauth.awp`
   (renvoie `cn`/`cv`, réutilisables), puis re-login avec `fa:[{cn,cv}]`.
4. Header `User-Agent` doit rester identique entre login et appels.

## 4. Endpoints relevés (compte personnel A, en lecture — `verbe=get`)

Tous sur `apip.ecoledirecte.com/v3/`. `{id}` = 18, `{cls}` = idClasse.

| Chemin | Contenu (clés `data`) | Écran |
|---|---|---|
| `personnels/{id}/messages.awp` | liste messagerie ; params `typeRecuperation=received\|sent`, `idClasseur`, `orderBy`, `order`, `page`, `itemsPerPage`, `onlyRead` ; corps `{anneeMessages}` | Messagerie |
| `signatureMessage.awp` | signature de l'utilisateur | Messagerie |
| `personnels/{id}/agendaEvenements.awp` | `{evenements}` | Agenda |
| `carnetCorrespondance/badgesNonLues.awp` | `{classes, groupes, eleves}` (compteurs non lus) | Cahier de liaison |
| `A/{id}/sessionsRdv.awp` | `{sessions, auteurs, invites, indisposInvites}` | Rendez-vous |
| `A/{id}/rdvi.awp` | `{rdvs, invites, personnes}` | Rendez-vous |
| `adultesDocuments.awp?archive=&listesPieces=1` | `{documents, listesPiecesAVerser, paramAdminDocumentsEntreprise}` | Documents |
| `A/{id}/postits.awp?administrable=o` | post-it / tableau d'affichage | Post-it |
| `A/{id}/espacestravail.awp?typeModule=espaceTravail` | espaces ENT (vide) | — |
| `niveauxListe.awp` | référentiel niveaux | Consultation |
| `classes/{cls}/eleves.awp` | **élèves d'une classe + coordonnées** | Consultation |
| `utilisateurs/professeurs.awp` | annuaire enseignants | Consultation |
| `salles.awp` | salles (vide) | Consultation |

À noter : ce compte **secrétariat n'a pas** l'accès notes/bulletins (réservé aux
comptes enseignant/famille) ni le conseil de classe rempli.

## 5. Effets de bord (importants pour un connecteur lecture seule)

- **Lister** les messages ne les marque PAS lus. **Ouvrir** un message (endpoint
  `messages/{id}.awp`) le marque lu → à exclure ou à protéger explicitement.
- Toute connexion mobilise le compte réel d'une personne (ici le secrétariat) :
  la « date de dernière connexion » et les stats bougent.

## 6. Décision de périmètre en attente

Implémenter côté MCP suppose de stocker le **mot de passe d'un compte personnel
d'un collègue** (secrétariat) — différent de l'admin, qui est le compte de [prénom].
À trancher avec [prénom] avant tout code (voir conversation).

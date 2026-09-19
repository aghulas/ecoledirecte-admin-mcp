# Cartographie — API espace personnel (www.ecoledirecte.com)

Relevé du 16/09/2026, compte **personnel** (secrétariat) d'un établissement de
test, `typeCompte = A`. Méthode : connexion faite par la
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

Point clé : la **consultation des élèves** (`classes/{id}/eleves`) donne la fiche
élève que l'API admin n'exposait pas, mais les **responsables n'y ont AUCUNE
coordonnée** (civilité, nom, prénom, rôle, id seulement) — seuls `email`/`portable`
**de l'élève** y figurent. Les vraies coordonnées des responsables (adresse,
téléphones, emails) sont sur un endpoint séparé, propre à chaque élève :
`eleves/{id}/coordonneesfamille` (capturé le 16/09/2026 en ouvrant la fiche
détaillée d'un élève depuis Consultation). Voir §4 et §7.

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

Tous sur `apip.ecoledirecte.com/v3/`. `{id}` = identifiant du compte personnel connecté, `{cls}` = idClasse.

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
| `classes/{cls}/eleves.awp` | `{entity, eleves[]}` — champs élève : `id, nom, prenom, sexe, dateNaissance, email, portable, regime, numeroBadge, dateEntree, dateSortie, dispense, dispositifs, photo, classeId, classeLibelle, responsables[{id, civilite, nom, prenom, role}]` (sur la classe testée) | Consultation |
| `eleves/{id}.awp` (corps `{"anneeScolaire":""}`) | fiche élève : `id, nom, particule, prenom, sexe, regime, dateDeNaissance, email, mobile, isPrimaire, isPP, photo, classeId, classeLibelle, classeEstNote, idEtablissement, dispositifs[]` — pas de champ santé/allergie observé | Consultation → fiche élève |
| `eleves/{id}/coordonneesfamille.awp` (corps `{}`) | **liste** d'entrées `{adresseLigne1-3, codePostal, ville, typeLien, typeLienLibelle, responsable{civilite, nom, nomSimple, prenom, codePays, telDomicile, telTravail, telMobile, mailTravail, mailPerso, profession, societe, csp{code,libelle}}, conjoint{...même forme...}}` — une entrée par responsable légal (`conjoint` optionnel). **C'est ici que sont les coordonnées des parents.** | Consultation → fiche élève → « Coordonnées des responsables familiaux » |
| `utilisateurs/professeurs.awp` | annuaire enseignants | Consultation |
| `salles.awp` | salles (vide) | Consultation |

À noter : ce compte **secrétariat n'a pas** l'accès notes/bulletins (réservé aux
comptes enseignant/famille) ni le conseil de classe rempli.

## 5. Effets de bord (importants pour un connecteur lecture seule)

- **Lister** les messages ne les marque PAS lus. **Ouvrir** un message (endpoint
  `messages/{id}.awp`) le marque lu → à exclure ou à protéger explicitement.
- Toute connexion mobilise le compte réel d'une personne (ici le secrétariat) :
  la « date de dernière connexion » et les stats bougent.

## 6. Décisions prises (16/09/2026)

- Compte utilisé : **secrétariat**, avec accord, **en attendant
  un compte dédié à la personne responsable du connecteur** en cours de création
  dans l'ERP de l'établissement (Charlemagne dans notre cas). Bascule = un
  simple `login` avec l'autre identifiant.
- Périmètre : **tout en lecture** ; jamais d'ouverture de message individuel.
- Double authentification : **non demandée** par l'établissement pour ce compte
  (paramètres 2FA à 0) — le login headless fonctionne sans cn/cv.
- Redaction par défaut sur les fiches élèves : `dateNaissance`, `numeroBadge`,
  `photo` (surchargeable avec `include_sensitive_fields=True`).
- Redaction par défaut sur `coordonneesfamille` : `profession`, `societe`, `csp`
  (catégorie socio-professionnelle) — hors périmètre « coordonnées », surchargeable
  pareil. Adresse/téléphones/emails, eux, sont le but de l'outil et toujours renvoyés.
  Outil dédié (`ed_perso_eleve_coordonnees_famille`) explicitement documenté comme
  réservé à un besoin de contact légitime, pas à de la collecte systématique.

## 7. Coordonnées des responsables — résolu (16/09/2026)

Capturé en observant les appels réels de l'app (hooks `fetch`/`XMLHttpRequest`,
aucune valeur réelle lue manuellement au-delà de ce qui s'affichait déjà dans le
navigateur de la personne connectée) lors de l'ouverture de la fiche d'un élève
depuis Consultation → classe → clic sur un élève → « Coordonnées des responsables
familiaux ». Deux appels enchaînés :
1. `eleves/{id}.awp` (corps `{"anneeScolaire":""}`) — fiche élève basique.
2. `eleves/{id}/coordonneesfamille.awp` (corps `{}`) — la vraie cible : liste de
   responsables avec adresse postale, téléphones (domicile/travail/mobile),
   emails (perso/travail), et éventuellement le conjoint.

Aucun effet de bord constaté (contrairement à l'ouverture d'un message) : ce n'est
qu'une consultation. Pas de champ santé/allergie/handicap observé sur ces deux
endpoints. Implémenté dans `ed_perso_eleve_coordonnees_famille`, avec redaction par
défaut de `profession`/`societe`/`csp` (cf. §6).


## 8. Cantine / étude / garderie — pas trouvé côté EcoleDirecte (16/09/2026)

Cherché à la demande de la personne responsable du connecteur si les inscriptions cantine/étude du soir/garderie
du matin par élève sont consultables. Négatif, sur tout ce qui a été exploré :

- `activites/familles` (API admin) : référentiel des types d'activités de suivi
  pour l'école — seulement `MIDI` (Restauration du midi) et `SOIR` (Restauration
  du soir) configurés. Pas d'étude ni de garderie définies. Et c'est un
  référentiel de types, pas une liste d'inscriptions par élève.
- Vie scolaire (classe et élève, `/C/{cls}/VieScolaire` et fiche élève) :
  absences/retards, sanctions/punitions/incidents, suivi du comportement
  hebdomadaire. Rien sur les repas/activités périscolaires.
- Connecteurs partenaires (API admin, `connecteurs`) : deux applis de
  restauration scolaire existent au catalogue EcoleDirecte (**ALISE**,
  **SKOLENGO RESTAURATION** anciennement Cater) mais **aucune n'est activée**
  pour l'établissement (`isActifEtab: false`) — donc pas de module cantine
  intégré à EcoleDirecte pour cet établissement actuellement.

Conclusion provisoire : cette donnée ne semble pas être dans EcoleDirecte pour
cette école. Piste la plus probable : le module périscolaire de **Charlemagne**
(projet séparé de base consolidée déjà en cours). À confirmer avec la
secrétariat/direction — il est possible que ce suivi soit géré ailleurs encore
(tableur, prestataire externe).

**Complément (doc communautaire EduWireApps/ecoledirecte-api-docs, 16/09/2026)** :
la doc non-officielle liste des endpoints EcoleDirecte natifs de restauration,
absents de ce qu'on avait observé par le navigateur (l'app ne les appelle
peut-être pas si le module n'est pas activé) :
- `menusRestaurationScolaire.awp` — menus de la semaine. **Testé en réel : `200`,
  liste vide** (rien publié pour l'instant, pas forcément désactivé).
- `E/{id}/commandesPassage.awp` — réservation/commande de repas à l'unité
  (« click & collect »), par élève. **Testé en réel : `403` refusé** pour le
  compte secrétariat (`A`) — réservé aux comptes famille/élève, ou non activé.
- `eleves/{id}/viescolaire.awp` — **testé en réel : `210` « Aucune donnée à
  afficher »**, cohérent avec l'écran Vie scolaire vu dans le navigateur.

Aucun de ces trois ne donne une liste d'inscriptions récurrentes (jours fixes de
cantine/étude/garderie par élève) — `commandesPassage` est un système de
réservation à l'unité (repas par repas), pas un forfait hebdomadaire, et de
toute façon inaccessible depuis ce compte. Ça ne change pas la conclusion :
priorité à vérifier du côté Charlemagne.

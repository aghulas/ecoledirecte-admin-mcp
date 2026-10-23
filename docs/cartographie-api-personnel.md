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


## Messagerie : lecture d'un message, brouillon et envoi (01/10/2026)

Relevé dans le front (module messagerie, `messagerie-compose`) :
- dossiers : reçus −1, envoyés −2, archivés −3, brouillons −5 (`typeRecuperation` received / sent /
  archived / draft) ;
- lire : `POST <personnels>/<id>/messages/<idMessage>.awp?verbe=get&mode=destinataire|expediteur`,
  corps `{anneeMessages}` — **marque le message « lu »** (reçus) ; remettre en non lu :
  `POST <personnels>/<id>/messages.awp?verbe=put` `{action:"marquerCommeNonLu", ids:[id], anneeMessages}` ;
- annuaire : `POST messagerie/contacts/{familles|eleves|professeurs|personnels}.awp?verbe=get`
  (familles : `idClasse, idGroupe, idMatiere, codeMatiere, nom, recupAll, onlyPresents` ; une ligne
  par élève ET par responsable : `responsable{id, typeResp 1|2, contacts}`) ;
- brouillon / envoi : `POST <personnels>/<id>/messages.awp?verbe=post`,
  `{message:{subject, content=base64(escapeHTMLEncode(html)), groupesDestinataires:[{destinataires,
  selection:{type}}], files, transfertFiles, read, from:{role,id,read}, brouillon:true|false,
  draftId?}, anneeMessages:""}` ; destinataire = contact de l'annuaire + `to_cc_cci`
  (to|cc|cci), et `type="1"` pour une famille ; `escapeHTMLEncode` = caractères non ASCII en entités.
- **Supervision** : le front désactive « Envoyer », « Différer » et « Enregistrer en brouillon » en
  mode supervision (`isModeSupervision()`). Le connecteur admin ne rédige donc jamais de message pour
  un autre compte ; l'écriture ne se fait qu'avec les identifiants du compte lui-même.

Implémentation : `client.lire_message` / `poster_message` par un chemin dédié (`_appel_messagerie`)
qui n'accepte que ces trois opérations ; `check_allowed` continue de bloquer tout le reste.
Validé en réel le 01/10/2026 (brouillon n°12 adressé au compte lui-même, relu, accents intacts).


## Passage Web (Charlemagne Passage) — lecture et pointage (23/10/2026)

Relevé dans le front public (`PassageWebService`, `PassagesWebModule`, route `/PassageWeb`, garde
`T.PERSONNEL`, module `PASSAGEWEB`). Corrige le §8 pour les établissements qui ont paramétré Passage.

- Points du compte : au login, `accounts[0].modules[code=PASSAGEWEB].params.listePDP`
  = `id:libellé:HHMM:HHMM||…` (id = IDPDP Charlemagne). Désignation des adultes côté Charlemagne
  (point Passage Web, onglet adultes) puis envoi vers EcoleDirecte.
- `POST v3/PassageWeb/<pdp>/recupDesPassagesPrevus.awp?verbe=get` → élèves prévus du jour
  (`idEleve`, nom, prénom, classe, régime, `badge`, photo, date de naissance) d'après le suivi Vie
  scolaire rattaché au point ; `…/recupDesRestrictions` (classes / régimes exclus) ;
  `…/recupDesClasses`.
- `POST v3/PassageWeb/<pdp>/recupDesPassagesWeb/<AAAA-MM-JJ>.awp?verbe=get` → passages du jour
  (`idPassageWeb`, `idPassant`, `typePassant`, `date`, `heure` « HH:MM:SS », `dateTransmission`,
  `dateAcq` renseignée une fois intégré par Charlemagne).
- Pointage : même chemin en `verbe=post`, `data={"passageWeb": {idPassageWeb:0, idPassant,
  typePassant:"E", date:"AAAA-MM-JJ", heure:"HH:MM", idPDP, dateTransmission:"", dateAcq:"", nom,
  prenom, particule, dateNaissance:"", sexe, photo:"", badge}}` → `data.idPassageWeb`. **Le front
  fixe date et heure côté navigateur** ; une date passée est acceptée et conservée par
  Charlemagne à l'intégration (essai du 23/10/2026 : 6 passages au 22/10, puis 443 au 03/09).
- Suppression : `POST v3/PassageWeb/<idPassageWeb>.awp?verbe=delete`, `data={}`.
- Intégration : Charlemagne Passage › Passage Web › Intégration ; le prix est calculé à ce
  moment-là selon les coches **actuelles** de la fiche élève pour le jour de la semaine du passage.

Constats du rattrapage (23/10/2026, ~12 130 passages de septembre-octobre, 0 erreur au bilan) :

- **`listePDP` est figée au login** : un point créé ou attribué ensuite (« Retard Etude », n° 05,
  IDPDP 10) n'y figure pas, alors que l'API accepte lecture et pointage sur ce point. Le connecteur
  l'accepte désormais si `recupDesPassagesWeb` répond (`hors_liste_session: true`) ; une
  reconnexion (`auth login`, code TOTP) remet la liste à jour.
- **Suppression refusée** (`code 550`, « Une erreur est survenue lors de l'exécution du
  programme ») pour 3 passages non intégrés datés de septembre, avec exactement l'appel du front
  (`deletePassageWeb` : `POST PassageWeb/<id>` `{}` `verbe=delete`). `dateTransmission` est posée
  dès la création : ce n'est pas elle qui distingue. Motif inconnu (jour passé ?) ; le statut
  renvoyé le dit et oriente vers l'écran Passage Web ou l'annulation dans Charlemagne.
- **« Ajout impossible en dehors du créneau horaire » (`code 550`)** : 3 refus à 20 h 55 sur le
  point Étude pendant que Rémi en changeait les heures (06:00-20:00 → 16:30-22:00) ; le même envoi
  est passé à 21 h 01. Le contrôle porte sur le créneau du point, côté serveur.
- **Un passage = un article** : un point Passage Web ne valide qu'un article. Retard du soir sur
  un point distinct (article de type temps, pointage à la sortie : prix = quarts d'heure entre
  le début de l'article et l'heure du passage ; essai 18:30 → 20:42 = 9 × 15 € = 135 €).
- **Intégration refusée sans tarif à la date** : « Impossible d'importer le passage de l'article
  Retard Soir, en date du 25/09/2026 il n'existe pas de tarif » (tarif daté du 01/10) ; le passage
  reste en attente côté EcoleDirecte et revient à chaque intégration.
- Une intégration lancée pendant un envoi prend ce qui est arrivé ; le reste vient à la suivante.
  Les passages intégrés restent listés par `recupDesPassagesWeb` (reprise sans doublon possible).

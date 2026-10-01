---
name: "ecoledirecte-parametrage"
description: "Auditer ou modifier le paramétrage de la console admin EcoleDirecte de l'École Sainte-Marie (accès sites, messagerie, documents, vie scolaire, sécurité…) via le connecteur MCP, d'après le guide Aplim."
---

# Paramétrage EcoleDirecte — École Sainte-Marie

À utiliser dès que Rémi demande de vérifier, auditer, comparer au guide Aplim (« CED4 – Ecole Directe »), ou modifier un réglage de la console admin EcoleDirecte (admin.ecoledirecte.com), même sans dire « paramètre ».

## Usage retenu d'EcoleDirecte (décisions du 30/09/2026)

EcoleDirecte sert aux **échanges familles ↔ secrétariat** et aux **documents dans les deux sens** (documents de l'école/de l'enfant, pièces à verser par les familles). Le suivi pédagogique passe par d'autres outils (Edumoov).

- Ouverts : sites Familles, Professeurs, Personnels ; messagerie Familles ↔ Administratifs, Professeurs ↔ Administratifs, Professeurs ↔ Professeurs ; documents Administratifs + factures avec notification e-mail ; demandes de modification de coordonnées ; rendez-vous familles.
- Fermés volontairement : site Élèves, site Entreprises, messagerie Familles ↔ Professeurs, cahier journal, journal de classe, vie scolaire et cahier de textes côté familles, notes, règlement en ligne.
- Nom dans les notifications : « EcoleDirecte – École Sainte Marie ». Page contact : support@saintemarie-fontainebleau.fr. Alertes admin « erreurs » et « messages importants » par e-mail.
- Restent à décider par Rémi (ne pas trancher seul) : contenu des messages dans le mail de notification, justification d'absence en ligne, coordonnées familles visibles par tous les enseignants, créneau des demandes de modification élève (01/12–15/12), 3DSecure console admin (bloquerait le login automatique du connecteur), texte de présentation de la page contact.

Tout écart à cet état lors d'un audit = à signaler, pas à « corriger » d'office.

## Outils (serveur MCP `ecoledirecte-admin`)

- `ed_admin_parametres_catalogue` — sans appel réseau. Sans filtre : sommaire par menu/rubrique. Filtres `menu` (généraux, familles, élèves, professeurs, personnels, entreprises), `rubrique`, `recherche`.
- `ed_admin_parametrage_lire(menu, rubrique?, certains_seulement=True)` — lit une rubrique ou un menu entier, avec intitulés, base64 décodé.
- `ed_admin_parametres_get(libelles)` — lecture ciblée ; refuse un libellé hors catalogue avec suggestions.
- `ed_admin_parametre_set(libelle, valeur, confirm=False)` — écriture d'UN réglage.

**Piège fondamental** : l'API renvoie « 0 » sans erreur pour un libellé qui n'existe pas. Ne jamais deviner un libellé ni utiliser `hors_catalogue=True` pour conclure qu'un réglage est désactivé. Toujours passer par le catalogue. Le serveur semble ignorer les accents (`Sites/Eleves/Actif` ≡ `Sites/Elèves/Actif`).

Beaucoup de réglages familles (vie scolaire, cahier de textes, notes, journal de classe) sont `certain: false` : pour les auditer, relire la rubrique avec `certains_seulement=False`.

## Audit complet

1. `ed_admin_session_info`, `ed_admin_synchros_etat`, `ed_admin_activation_comptes` (contexte : année, transferts de la nuit, comptes familles activés).
2. `ed_admin_parametrage_lire` pour chaque menu : généraux, familles, professeurs, personnels, élèves ; puis familles › Vie scolaire / Cahier de textes / Notes / Journal de classe et généraux › Formulaires avec `certains_seulement=False`.
3. Comparer à l'usage retenu ci-dessus et au guide Aplim (sections 4.2 à 4.7). Présenter en trois blocs : **À corriger**, **À décider**, **Conforme**, en langage clair (nom de la case dans l'admin, pas le libellé technique). Signaler les incohérences (ex. affichage familles activé pour une saisie désactivée côté enseignants).
4. Ce qui n'est pas visible par l'API : fonctions des adultes dans Charlemagne (un secrétariat sans fonction n'apparaît pas comme destinataire des parents), profil administrateur (adresse des alertes).

## Modification

1. Retrouver le libellé exact dans le catalogue.
2. `ed_admin_parametre_set` sans `confirm` → montrer l'aperçu (valeur actuelle → proposée).
3. **Accord explicite de Rémi en conversation, réglage par réglage** (« corrige 1 et 2 » vaut accord pour les points listés, pas pour les autres).
4. `confirm=True`, vérifier `coherent: true`, puis relire quelques réglages voisins avec `ed_admin_parametres_get` pour s'assurer qu'aucun n'a bougé.
5. Refus attendus (ne pas contourner) : secrets, règlement en ligne, connecteurs partenaires, délais réglementaires notes/LSU, libellés hors catalogue. Les valeurs base64 (adresse, présentation de la page contact) s'écrivent en clair.
6. Consigner les écritures dans la spec du projet (`claude/spec-connecteur-mcp-ecoledirecte.md`, §5) et mettre à jour la section « usage retenu » de ce skill si une décision change.

## Si le catalogue semble faux

Un réglage absent ou un faux réglage (ex. options de liste prises pour des paramètres) : régénérer avec `tools/extraire_parametres.py` dans `~/dev/ecoledirecte-admin-mcp`, corriger l'extracteur si besoin, tests, puis suivre la procédure de maintenance du connecteur.
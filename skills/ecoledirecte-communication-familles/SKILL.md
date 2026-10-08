---
name: "ecoledirecte-communication-familles"
description: "Informer des familles de l'École Sainte-Marie par la messagerie EcoleDirecte (message à une classe, un niveau ou quelques familles, avec pièce jointe) — brouillon préparé dans la boîte EcoleDirecte de l'utilisateur ou du secrétariat, relu et envoyé par une personne, puis corrigé ou supprimé si besoin."
---

# Communication aux familles via EcoleDirecte

À utiliser quand Rémi veut que des familles reçoivent une information administrative ou un document (circulaire, invitation, rappel de pièces, facture…), ou quand une information a été « publiée » sans que les familles la voient.

## 1. Message, pas document

- **Un document publié dans l'espace Documents (depuis Charlemagne) n'envoie aucune notification.** Les parents ne le voient que s'ils vont le chercher (cas de l'invitation CM2 et du projet éducatif, fin septembre 2026). Toute information à faire lire passe par un **message**, avec le document en pièce jointe ; l'espace Documents ne sert qu'en complément, pour les documents de référence.
- Retrouver ce qui a déjà été publié : `ed_admin_documents_ecole` (vue école, une famille par classe) ou `ed_admin_documents_famille` (une famille, tous ses comptes) ; récupérer le PDF avec `ed_admin_document_telecharger` (dossier `~/Charlemagne/ecoledirecte_documents`). Les documents sont publiés **compte par compte** : un parent peut voir un document que l'autre ne voit pas.
- Côté Charlemagne, `journal_transferts_ecoledirecte` indique quand des PDF ont été envoyés (nombre seulement).
- Vie de classe, message des enseignants : Educartable (skill `edumoov-communication-familles`). Pour une information importante aux familles d'une classe, envoyer **les deux** (même texte), la signature seule changeant.

## 2. Choisir le compte expéditeur

Deux serveurs MCP, mêmes outils (`ed_perso_*`), un compte chacun — vérifier avec `ed_perso_session_info` :

| Serveur | Compte | Quand |
|---|---|---|
| `ecoledirecte-secretariat` | compte du **secrétariat** (secretariat@) | **par défaut** pour les messages administratifs aux familles (justificatifs, factures, relances) : les réponses arrivent dans la boîte du secrétariat |
| `ecoledirecte-perso` | compte personnel de Rémi | message que Rémi signe lui-même |

- Le message part sous le nom du compte connecté : écrire avec **le serveur du compte qui doit envoyer**, jamais par la supervision admin (EcoleDirecte bloque l'écriture en supervision).
- Les deux accès écrivent (`ED_PERSO_MESSAGERIE_ACTIF=1`) depuis le 08/10/2026. Lire la boîte du secrétariat : `ecoledirecte-secretariat` · `ed_perso_messages_list` (ne marque rien lu) ; `ed_perso_message_lire` remet en non lu par défaut.

## 3. Rédiger

- Vouvoiement, « Madame, Monsieur, », phrases courtes ; objet explicite (événement + date). `texte` en texte brut, paragraphes séparés par une ligne vide, signature comprise.
- Dates absolues ; lieu complet ; ce que la famille doit faire et avant quand. Citer les libellés EcoleDirecte (listes de pièces, rubriques) **exactement** comme les familles les voient (ex. « Justificatifs Frateries Enseignement Catholique Exterieur ») — les vérifier dans Charlemagne (`COM_LISTE_PIECE`) ou EcoleDirecte.
- Signature = expéditeur réel : « Le secrétariat – École Sainte Marie » depuis le compte du secrétariat ; « Rémi Poittevin, OGEC École Sainte Marie » depuis le compte de Rémi. Contact : répondre au message, ou support@saintemarie-fontainebleau.fr pour une difficulté de connexion.
- Pas de données d'autres familles dans un message collectif. Destinataires toujours en **copie cachée**.
- Ne pas promettre une décision non prise (ex. « facture rectificative », retrait d'une remise) : à faire valider par la direction.
- Montrer le texte à Rémi et l'ajuster avant toute préparation.

## 4. Préparer le brouillon

1. Destinataires : les élèves de la classe ou du niveau (`ed_perso_classe_eleves`, ou `ed_admin_eleves_search`), ou une liste ciblée calculée depuis Charlemagne (pièces non reçues, fiches forfaits…), puis une entrée par élève `{"type": "famille", "id_eleve": N, "responsable": "tous", "champ": "cci"}` ; un personnel : `{"type": "personnel", "id": N, "champ": …}` (ids : `ed_perso_contacts_rechercher`). Les responsables d'une fratrie ne sont comptés qu'une fois. Exclure les familles non concernées (ex. remise personnel ENS_SM/ENS_EC/SAL_* pour la fratrie).
2. Pièces jointes : fichiers sous `~/Charlemagne` (pdf, png, jpg, docx ; 5 au plus, 20 Mo). Documents bancaires refusés.
3. `ed_perso_message_ecrire(sujet, texte, destinataires, mode="brouillon", pieces_jointes=[…], plafond_destinataires=<n>)` : simulation d'abord (nombre de destinataires, liste en Cci), puis `confirm=True` après accord de Rémi. Un brouillon accepte jusqu'à 150 destinataires ; un envoi direct est plafonné à 30 et n'est pas la règle.
4. Relire le brouillon (`ed_perso_message_lire`, `boite="draft"`) : objet, texte, nombre de destinataires, champ `to_cc_cci` = `cci` partout, pièce jointe présente.

## 5. Corriger, déplacer ou supprimer un brouillon

- **Corriger** : `ed_perso_brouillon_modifier(id_message, sujet?, texte?, remplacements=[{"ancien","nouveau"}], destinataires?)` — remplacements exacts, mise en forme conservée ; destinataires et pièces jointes conservés (retrouvés dans l'annuaire ; un destinataire introuvable bloque) ou remplacés. Simulation, accord, `confirm=True`, puis relire : nombre de destinataires et texte.
- **Supprimer** : `ed_perso_brouillon_supprimer(id_message)` — un brouillon à la fois, refusé pour un message reçu ou envoyé ; simulation, accord, `confirm=True`.
- **Changer d'expéditeur** (ex. brouillon préparé sur le compte de Rémi, à envoyer par le secrétariat) : lire le brouillon (texte, objet), le recréer avec `ed_perso_message_ecrire` sur le serveur cible (mêmes destinataires, signature adaptée), relire le nouveau, **puis seulement** supprimer l'ancien. Fait le 08/10/2026 pour 3 brouillons (14, 66 et 2 destinataires).

## 6. Envoi

- C'est une personne qui relit et envoie le brouillon depuis EcoleDirecte (dossier Brouillons du compte expéditeur). Jamais d'envoi direct par le connecteur sans accord explicite de Rémi pour ce message.
- Après envoi, vérifier dans `ed_perso_messages_list(boite="sent")` du bon serveur.

## 7. Points d'attention

- Une session EcoleDirecte ouverte dans un navigateur sur le même compte peut casser le jeton (rotation à chaque appel). En cas d'erreur « Identifiant ou mot de passe invalide (505) » répétée, le mot de passe a probablement changé : l'utilisateur relance lui-même `auth setup` puis `auth login` avec le `ED_PERSO_HOME` du compte (voir skill `maintenance-connecteur-ecoledirecte`) ; le connecteur ne gère jamais les mots de passe.
- Si l'écriture est refusée (`ED_PERSO_MESSAGERIE_ACTIF` absent) : fournir le texte prêt à coller et la liste des destinataires (classes) pour une saisie manuelle.

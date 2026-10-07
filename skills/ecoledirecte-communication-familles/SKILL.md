---
name: "ecoledirecte-communication-familles"
description: "Informer des familles de l'École Sainte-Marie par la messagerie EcoleDirecte (message du secrétariat à une classe, un niveau ou quelques familles, avec pièce jointe) — brouillon dans la boîte du secrétariat, relu et envoyé par le secrétariat."
---

# Communication aux familles via EcoleDirecte

À utiliser quand Rémi veut que des familles reçoivent une information administrative ou un document (circulaire, invitation, rappel de pièces, facture…), ou quand une information a été « publiée » sans que les familles la voient.

## 1. Message, pas document

- **Un document publié dans l'espace Documents (depuis Charlemagne) n'envoie aucune notification.** Les parents ne le voient que s'ils vont le chercher (cas de l'invitation CM2 et du projet éducatif, fin septembre 2026). Toute information à faire lire passe par un **message**, avec le document en pièce jointe ; l'espace Documents ne sert qu'en complément, pour les documents de référence.
- Retrouver ce qui a déjà été publié : `ed_admin_documents_ecole` (vue école, une famille par classe) ou `ed_admin_documents_famille` (une famille, tous ses comptes) ; récupérer le PDF avec `ed_admin_document_telecharger` (dossier `~/Charlemagne/ecoledirecte_documents`). Les documents sont publiés **compte par compte** : un parent peut voir un document que l'autre ne voit pas.
- Côté Charlemagne, `journal_transferts_ecoledirecte` indique quand des PDF ont été envoyés (nombre seulement).
- Vie de classe, message des enseignants : Educartable (skill `edumoov-communication-familles`). Pour une information importante aux familles d'une classe, envoyer **les deux** (même texte), la signature seule changeant.

## 2. Rédiger

- Vouvoiement, « Madame, Monsieur, », phrases courtes ; objet explicite (événement + date). `texte` en texte brut, paragraphes séparés par une ligne vide, signature comprise.
- Dates absolues ; lieu complet ; ce que la famille doit faire et avant quand.
- Signature : « Le secrétariat – École Sainte Marie ». Contact : répondre au message, ou support@saintemarie-fontainebleau.fr pour une difficulté de connexion.
- Pas de données d'autres familles dans un message collectif. Destinataires toujours en **copie cachée**.
- Montrer le texte à Rémi et l'ajuster avant toute préparation.

## 3. Préparer le brouillon (serveur `ecoledirecte-perso`, compte du secrétariat)

1. Destinataires : les élèves de la classe ou du niveau (`ed_perso_classe_eleves`, ou `ed_admin_eleves_search`), puis une entrée par élève `{"type": "famille", "id_eleve": N, "responsable": "tous", "champ": "cci"}` ; un personnel : `{"type": "personnel", "id": N, "champ": …}` (ids : `ed_perso_contacts_rechercher`). Les responsables d'une fratrie ne sont comptés qu'une fois. Ex. du 06/10/2026 : deux classes de CM2 → 114 responsables.
2. Pièces jointes : fichiers sous `~/Charlemagne` (pdf, png, jpg, docx ; 5 au plus, 20 Mo) — par ex. le PDF récupéré dans l'espace Documents. Documents bancaires refusés.
3. `ed_perso_message_ecrire(sujet, texte, destinataires, mode="brouillon", pieces_jointes=[…], plafond_destinataires=<n>)` : simulation d'abord (aperçu : nombre de destinataires, pièces jointes), puis `confirm=True` après accord de Rémi. Un brouillon accepte jusqu'à 150 destinataires (`plafond_destinataires`) ; un envoi direct est plafonné à 30 et n'est pas la règle.
4. Relire le brouillon (`ed_perso_message_lire`, `boite="draft"`) : objet, destinataires en copie cachée, pièce jointe présente.

## 4. Envoi

- **C'est le secrétariat (Agnès Coutouly) qui relit et envoie** le brouillon depuis la boîte du secrétariat (dossier Brouillons). Préparer pour Rémi un mail à secretariat@ (et direction@ si besoin), en vouvoiement, indiquant l'objet du brouillon, le nombre de destinataires et la pièce jointe — brouillon Outlook que Rémi envoie lui-même.
- Jamais d'envoi direct par le connecteur sans accord explicite de Rémi pour ce message.
- Après envoi, vérifier dans `ed_perso_messages_list(boite="sent")`.

## 5. Points d'attention

- Le compte perso est celui du secrétariat : une session navigateur ouverte en même temps peut casser le jeton (rotation à chaque appel) ; en cas d’erreur « Identifiant ou mot de passe invalide (505) » répétée, le mot de passe du compte a probablement changé — Rémi met à jour le Trousseau macOS (`ecoledirecte-perso-mcp`) ; le connecteur ne gère jamais les mots de passe.
- Si `ED_PERSO_MESSAGERIE_ACTIF` n'est pas activé : fournir le texte prêt à coller et la liste des destinataires (classes) pour une saisie manuelle.

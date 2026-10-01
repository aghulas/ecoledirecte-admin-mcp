---
name: "ecoledirecte-identifiants-familles"
description: "Préparer et contrôler l'envoi des identifiants EcoleDirecte de première connexion aux familles (ou au personnel) de l'École Sainte-Marie depuis Charlemagne, puis suivre l'activation des comptes."
---

# Identifiants EcoleDirecte — École Sainte-Marie

À utiliser quand Rémi veut envoyer ou renvoyer les codes EcoleDirecte (nouvelles familles, rentrée, codes perdus, enseignants), ou savoir qui s'est connecté.

## Avant l'envoi : ce que le message promet doit exister

Vérifier (skill `ecoledirecte-parametrage`) : site Familles ouvert ; messagerie Familles → Administratifs ; documents Administratifs visibles avec notification ; page contact avec support@saintemarie-fontainebleau.fr. Dans Charlemagne, la secrétaire doit avoir une **fonction** (Administration › Adultes) sinon les parents ne la trouvent pas comme destinataire.

## Message (Charlemagne › Traitements › Messages › Emails)

Objet : `École Sainte Marie – Vos identifiants EcoleDirecte`. E-mail de réponse : `support@saintemarie-fontainebleau.fr`. Vouvoiement. Insérer les mots-clés avec le bouton **Mots-Clefs** (pas à la main) :

```
Madame, Monsieur,

L'École Sainte Marie utilise désormais EcoleDirecte pour échanger avec les familles. Votre espace vous permet :
- d'écrire au secrétariat et de recevoir ses messages ;
- de nous transmettre les documents demandés (justificatifs, attestations, fiches à retourner…) ;
- de consulter les documents de l'école et ceux qui concernent votre enfant.

Voici vos identifiants personnels de première connexion :
- Adresse du site : #SITE
- Identifiant : #LOGIN
- Mot de passe provisoire : #PASS

À votre première connexion, vous devrez choisir un nouvel identifiant et un nouveau mot de passe. Conservez-les précieusement : ce sont eux que vous utiliserez ensuite, sur le site comme sur l'application mobile « EcoleDirecte » (App Store et Google Play).

Ces identifiants sont personnels. Chaque parent reçoit les siens et peut suivre tous ses enfants inscrits à l'école avec un seul compte.

Pour toute difficulté de connexion, vous pouvez écrire à support@saintemarie-fontainebleau.fr.

Nous vous prions d'agréer, Madame, Monsieur, l'expression de nos salutations distinguées.

La Direction – École Sainte Marie
```

Adapter la liste des usages si le paramétrage change (ne jamais promettre une fonction désactivée : notes, vie scolaire, cahier de textes, élèves).

## Sélection des destinataires (mode avancé)

- Onglet Élèves : cocher **Aîné de la sélection** ; pour la 2e année et suivantes, ne prendre que les nouveaux via une **date de présence** couvrant la rentrée.
- Onglet Famille : **Tous les responsables légaux** (chaque parent reçoit ses codes).
- Préférence : e-mail personnel.
- Bouton « destinataires sans e-mail » → exporter sous Excel : ces familles reçoivent les codes sur **papier** (Traitements › Éditions › Documents), les SMS n'étant pas activés.

## Contrôles

- Tester d'abord sur une seule famille : des **étoiles** à la place des codes = le profil Charlemagne n'a pas « Visualiser les logins et mots de passe » (Fichier › Profils › Utilisateurs › Divers).
- Les mots de passe sont liés à l'année scolaire.
- Enseignants : Administration › Adultes › Édition (courrier « Mot de passe »), catégorie Personnel ou Personnel et Enseignant avec onglet EcoleDirecte activé.
- Code perdu : fiche famille › clés › réinitialiser / renvoyer par e-mail. Le connecteur ne gère jamais les mots de passe (endpoints bloqués).

## Suivi de l'activation

`ed_admin_activation_comptes` (sans classe = synthèse ; avec classe = listes nominatives, à ne restituer qu'au besoin). Refaire le point le lendemain de l'envoi puis chaque semaine ; proposer une relance ciblée des familles sans aucun parent connecté.
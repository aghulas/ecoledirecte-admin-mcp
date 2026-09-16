# ecoledirecte-mcp (prototype)

Deux serveurs MCP **en lecture seule** vers EcoleDirecte (école l'établissement,
[ville]), APIs internes non documentées :

- **`ecoledirecte-admin`** — console admin (`admin.ecoledirecte.com`) :
  annuaire des comptes, classes, paramétrages, stats, synchros Charlemagne.
  Voir [`docs/cartographie-api-admin.md`](docs/cartographie-api-admin.md).
- **`ecoledirecte-perso`** — espace personnel (`www.ecoledirecte.com`) d'un compte
  secrétariat : consultation des élèves par classe, coordonnées détaillées des
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
  "command": "/Users/remi/dev/ecoledirecte-admin-mcp/.venv/bin/ecoledirecte-admin-mcp"
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
| `ed_admin_parametres_get(libelles)` | valeurs de paramètres (secrets masqués) |
| `ed_admin_stats_connexions` | connexions par profil et période |
| `ed_admin_synchros_etat` | derniers transferts Charlemagne → ED |
| `ed_admin_connecteurs_list` | applis partenaires activées |
| `ed_admin_activites_list` | activités de suivi (cantine, étude…) |
| `ed_admin_referentiels_get` | sanctions, catégories de suivi, tags CDT, salles… |
| `ed_admin_activation_comptes(classe?, inclure_noms?)` | activation des comptes par classe : élèves sans aucun parent connecté, responsables jamais connectés, taux |

## Garde-fous (testés, `pytest`)

- Seul `verbe=get` peut partir du client : aucune écriture possible.
- Bloqués même en lecture : `compteOrigineED`, `supervisionmobile`, `supervision`
  (identifiants d'autres utilisateurs / usurpation de session), gestion des logins,
  `banques`, fichiers.
- `badge` et `photo` retirés des fiches par défaut (`include_sensitive_fields=True` pour les obtenir).
- Paramètres ressemblant à des secrets (clés, certificats, mots de passe, IBAN…) masqués.
- Aucun token ni mot de passe dans les messages d'erreur.

```bash
./.venv/bin/pytest
```

---

## Serveur espace personnel (`ecoledirecte-perso`)

Compte **personnel/secrétariat** de l'école, avec **l'accord de la personne**.
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
- Pour basculer sur un autre compte (ex. compte dédié une fois créé) : relancer
  `auth login` avec le nouvel identifiant, rien d'autre à changer.

### Précautions importantes

- **Compte d'un tiers** : n'utiliser qu'avec l'accord explicite de la personne.
- **Jeton tournant** : si cette personne (ou toi) est connectée sur EcoleDirecte
  dans un navigateur au même moment, les jetons se cassent mutuellement. Éviter
  l'usage simultané.
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
| `ed_perso_agenda` | événements agenda |
| `ed_perso_carnet_liaison_non_lus` | compteurs non lus du cahier de liaison |
| `ed_perso_rendez_vous` | sessions et RDV individuels |
| `ed_perso_documents(archive?)` | documents de l'établissement |
| `ed_perso_postits` | post-it / tableau d'affichage |

### Claude Desktop

```json
"ecoledirecte-perso": {
  "command": "/Users/remi/dev/ecoledirecte-admin-mcp/.venv/bin/ecoledirecte-perso-mcp"
}
```

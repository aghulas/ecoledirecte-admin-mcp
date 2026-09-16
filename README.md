# ecoledirecte-admin-mcp (prototype)

Serveur MCP **en lecture seule** vers la console admin EcoleDirecte
(admin.ecoledirecte.com) de l'école l'établissement, [ville]. Basé sur l'API
interne `api.ecoledirecte.com/v3/admin/`, non documentée — voir
[`docs/cartographie-api-admin.md`](docs/cartographie-api-admin.md).

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

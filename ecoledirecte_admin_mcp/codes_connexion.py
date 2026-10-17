"""Gestion des comptes de connexion EcoleDirecte (phase d'activation des familles).

Quatre gestes, calqués sur la console admin (service IdentifiantsUtilisateursService),
pour répondre à une famille/un personnel qui n'arrive pas à activer son espace :

  - lire les codes de première connexion (compte jamais activé) ;
  - régénérer ces codes (reset dur : casse les associations) ;
  - débloquer un compte verrouillé après trop d'essais ;
  - forcer le changement de mot de passe à la prochaine connexion.

GARDE-FOUS
  - Les endpoints `compteOrigineED` / `blockingState` restent interdits par la route
    générique du client ; seules les méthodes dédiées de EcoleDirecteAdminClient y
    accèdent (voir client.py).
  - Les codes (identifiant + mot de passe de première connexion) ne sont JAMAIS
    renvoyés dans la réponse de l'outil ni journalisés : ils sont écrits dans un
    fichier local (droits 0600, jamais écrasé) sous ED_ADMIN_CODES_DIR. Sans cette
    variable d'environnement, lire/régénérer sont refusés (donc inactifs sur Azure).
  - Les gestes d'écriture (régénérer, débloquer, forcer le changement) exigent
    `confirm=True` : sans lui, l'outil ne fait qu'un aperçu et n'appelle pas le réseau.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any

from mcp.server.mcpserver.exceptions import ToolError

# Rôle lisible → type court attendu par l'API (Utils.translateType du front admin).
TYPES = {
    "eleve": "E",
    "responsable": "1",
    "conjoint": "2",
    "personnel": "A",
    "professeur": "P",
}
_CLES_SECRETES = ("edNomUtilisateurOrigine", "edMotDePasseOrigine", "at")


def _type_court(role: str) -> str:
    r = (role or "").strip().lower()
    if r in TYPES:
        return TYPES[r]
    if role in TYPES.values():  # un code court est aussi accepté
        return role
    raise ToolError(
        f"role invalide : {role!r} — attendu parmi {sorted(TYPES)} "
        "(ou le code court E/1/2/A/P)."
    )


def _exiger_actif() -> None:
    """Garde-fou d'activation, jamais posé sur Azure (comme les autres écritures)."""
    if os.environ.get("ED_ADMIN_COMPTES_ACTIF", "") != "1":
        raise ToolError(
            "Gestion des comptes de connexion désactivée (ED_ADMIN_COMPTES_ACTIF≠1) — "
            "jamais activée sur Azure."
        )


def dossier_codes() -> Path:
    d = os.environ.get("ED_ADMIN_CODES_DIR")
    if not d:
        raise ToolError(
            "Lecture/régénération des codes désactivée : définir ED_ADMIN_CODES_DIR "
            "(dossier local où enregistrer les codes de connexion). Inactif sans ce "
            "dossier (par ex. sur un serveur distant)."
        )
    p = Path(d).expanduser()
    p.mkdir(parents=True, exist_ok=True)
    return p


def _ecrire_fichier(role: str, type_court: str, id_user: int, data: dict[str, Any],
                    regenere: bool) -> Path:
    """Écrit les codes dans un fichier local dédié, droits 0600, sans jamais écraser."""
    identifiant = data.get("edNomUtilisateurOrigine")
    motdepasse = data.get("edMotDePasseOrigine")
    jeton_qr = data.get("at")
    horodatage = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = f"codes_{role}_{type_court}{id_user}_{horodatage}"
    dossier = dossier_codes()
    lignes = [
        "Codes de connexion EcoleDirecte (confidentiel — à transmettre à l'intéressé, puis à détruire)",
        f"Généré le        : {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}",
        f"Rôle / type      : {role} ({type_court})",
        f"Identifiant interne : {id_user}",
        f"Action           : {'RÉGÉNÉRATION (nouveaux codes)' if regenere else 'lecture des codes existants'}",
        "",
        f"Identifiant      : {identifiant if identifiant else '(absent de la réponse)'}",
        f"Mot de passe     : {motdepasse if motdepasse else '(absent de la réponse)'}",
    ]
    if jeton_qr:
        lignes.append(f"Jeton QR (appli mobile) : {jeton_qr}")
    contenu = "\n".join(lignes) + "\n"
    for suffixe in ("", *(f"_{i}" for i in range(2, 50))):
        chemin = dossier / f"{base}{suffixe}.txt"
        try:
            fd = os.open(chemin, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(contenu)
        return chemin
    raise ToolError("Impossible de créer un fichier de codes unique (trop d'homonymes).")


def _reponse_codes(role: str, type_court: str, id_user: int, data: dict[str, Any],
                   regenere: bool) -> dict[str, Any]:
    """Construit la réponse SANS secret : chemin du fichier + présence des champs."""
    chemin = _ecrire_fichier(role, type_court, id_user, data, regenere)
    return {
        "compte": {"role": role, "type_court": type_court, "id": id_user},
        "action": "regeneration" if regenere else "lecture",
        "fichier_local": str(chemin),
        "identifiant_present": bool(data.get("edNomUtilisateurOrigine")),
        "mot_de_passe_present": bool(data.get("edMotDePasseOrigine")),
        "jeton_qr_present": bool(data.get("at")),
        "codes_dans_la_reponse": False,
        "message": (
            "Codes écrits dans le fichier local (droits 0600) ; ils ne sont PAS affichés "
            "ici. Ouvre le fichier pour les transmettre à l'intéressé, puis supprime-le."
        ),
    }


# --------------------------------------------------------------------------
# Gestes (appelés par les outils du serveur). `client` = EcoleDirecteAdminClient.
# --------------------------------------------------------------------------
async def lire_codes(client, role: str, id_user: int) -> dict[str, Any]:
    """Lecture seule des codes de première connexion (ne modifie rien)."""
    type_court = _type_court(role)
    _exiger_actif()
    dossier_codes()  # échoue tôt si ED_ADMIN_CODES_DIR absent
    data = await client.lire_codes_connexion(type_court, id_user)
    if not isinstance(data, dict):
        raise ToolError("Réponse inattendue de l'API (codes) — rien n'a été enregistré.")
    return _reponse_codes(role, type_court, int(id_user), data, regenere=False)


async def regenerer_codes(client, role: str, id_user: int, confirm: bool = False) -> dict[str, Any]:
    """Régénère les codes (reset dur) PUIS les relit. Aperçu sans confirm=True."""
    type_court = _type_court(role)
    dossier_codes()
    if not confirm:
        return {
            "compte": {"role": role, "type_court": type_court, "id": int(id_user)},
            "action": "regeneration",
            "ecriture_effectuee": False,
            "avertissement": (
                "ATTENTION : régénérer réinitialise l'identifiant ET le mot de passe sur "
                "EcoleDirecte et SUPPRIME les associations de comptes de l'utilisateur "
                "(liens parent↔enfants, compte partagé). À réserver aux comptes jamais "
                "activés. Pour un compte déjà activé, préférer « lire les codes » ou "
                "« demander le changement de mot de passe »."
            ),
            "message": "Aperçu seulement — rappelle avec confirm=True pour régénérer.",
        }
    _exiger_actif()
    data = await client.regenerer_codes_connexion(type_court, int(id_user))
    if not isinstance(data, dict):
        raise ToolError("Réponse inattendue de l'API après régénération.")
    out = _reponse_codes(role, type_court, int(id_user), data, regenere=True)
    out["ecriture_effectuee"] = True
    out["avertissement"] = "Associations de comptes supprimées lors de la régénération."
    return out


async def debloquer(client, role: str, id_user: int, confirm: bool = False) -> dict[str, Any]:
    """Débloque un compte verrouillé. Aperçu (état de blocage) sans confirm=True."""
    type_court = _type_court(role)
    etat = await client.etat_blocage_compte(type_court, int(id_user))
    bloque = etat.get("isBloque") if isinstance(etat, dict) else None
    if not confirm:
        return {
            "compte": {"role": role, "type_court": type_court, "id": int(id_user)},
            "action": "deblocage",
            "est_bloque": bloque,
            "ecriture_effectuee": False,
            "message": (
                "Aperçu seulement — rappelle avec confirm=True pour débloquer."
                if bloque else
                "Le compte n'apparaît pas bloqué ; confirm=True débloquera quand même si tu insistes."
            ),
        }
    _exiger_actif()
    await client.debloquer_compte(type_court, int(id_user))
    etat_apres = await client.etat_blocage_compte(type_court, int(id_user))
    return {
        "compte": {"role": role, "type_court": type_court, "id": int(id_user)},
        "action": "deblocage",
        "etait_bloque": bloque,
        "est_bloque": etat_apres.get("isBloque") if isinstance(etat_apres, dict) else None,
        "ecriture_effectuee": True,
    }


async def demander_changement_mdp(client, role: str, id_user: int, confirm: bool = False) -> dict[str, Any]:
    """Force le changement de mot de passe à la prochaine connexion. Aperçu sans confirm."""
    type_court = _type_court(role)
    if not confirm:
        return {
            "compte": {"role": role, "type_court": type_court, "id": int(id_user)},
            "action": "changement_mdp",
            "ecriture_effectuee": False,
            "message": (
                "Aperçu seulement — rappelle avec confirm=True pour forcer le changement. "
                "L'utilisateur verra un message à sa prochaine connexion et devra changer "
                "son mot de passe avant de continuer (ne casse pas les associations, "
                "n'expose aucun identifiant). Suppose qu'il peut déjà se connecter."
            ),
        }
    _exiger_actif()
    await client.demander_changement_mdp(type_court, int(id_user))
    return {
        "compte": {"role": role, "type_court": type_court, "id": int(id_user)},
        "action": "changement_mdp",
        "ecriture_effectuee": True,
        "message": "Changement de mot de passe demandé pour la prochaine connexion.",
    }

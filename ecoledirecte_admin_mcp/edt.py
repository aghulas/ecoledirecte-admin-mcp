"""Emploi du temps tel qu'EcoleDirecte l'affiche à un enseignant — LECTURE SEULE,
via la supervision admin (04/10/2026).

L'emploi du temps est en lecture seule dans EcoleDirecte : il vient de
Charlemagne Vie Scolaire (transfert du module VS). Cet outil sert à vérifier
qu'un import / une génération Charlemagne est bien arrivé côté EcoleDirecte
(cours, horaires, matières, salles, semaines A/B).

Flux :
  1. POST v3/admin/supervision.awp?id=<id enseignant>&type=P&n=<NOM[:3]>&version=
     (même mécanisme que depot_pieces.ouvrir_supervision, type « P ») ;
  2. POST v3/loginexterne.awp → jeton de l'espace enseignant ;
  3. POST v3/P/<id>/emploidutemps.awp?verbe=get
       data={"dateDebut": "AAAA-MM-JJ", "dateFin": "AAAA-MM-JJ", "avecTrous": false}

Garde-fous :
  - uniquement des appels verbe=get après l'ouverture de session ;
  - activé seulement si ED_ADMIN_EDT_ACTIF=1 (comme les autres usages de la
    supervision) ;
  - période limitée à 31 jours par appel.
"""
from __future__ import annotations

import os
import unicodedata
from collections import Counter
from datetime import date, timedelta
from typing import Any

from mcp.server.mcpserver.exceptions import ToolError

from .depot_pieces import ouvrir_supervision

MAX_JOURS = 31


def _actif() -> bool:
    return os.environ.get("ED_ADMIN_EDT_ACTIF", "") == "1"


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).upper().strip()


def _periode(date_debut: str, date_fin: str | None) -> tuple[str, str]:
    try:
        d1 = date.fromisoformat(date_debut)
        d2 = date.fromisoformat(date_fin) if date_fin else d1 + timedelta(days=6)
    except ValueError as exc:
        raise ToolError("Dates attendues au format AAAA-MM-JJ.") from exc
    if d2 < d1:
        raise ToolError("date_fin est avant date_debut.")
    if (d2 - d1).days > MAX_JOURS:
        raise ToolError(f"Période limitée à {MAX_JOURS} jours par appel.")
    return d1.isoformat(), d2.isoformat()


def choisir_enseignant(professeurs: list[dict[str, Any]], enseignant: str) -> dict[str, Any]:
    """Retrouve un enseignant par identifiant ou par nom (sans accents ni casse)."""
    e = str(enseignant).strip()
    if e.isdigit():
        for p in professeurs:
            if str(p.get("id")) == e:
                return p
    cible = _norm(e)
    trouves = [p for p in professeurs if _norm(p.get("nom", "")) == cible]
    if not trouves:
        trouves = [p for p in professeurs if cible in _norm(f"{p.get('nom', '')} {p.get('prenom', '')}")]
    if not trouves:
        raise ToolError(f"Enseignant introuvable dans EcoleDirecte : {enseignant}")
    if len(trouves) > 1:
        noms = ", ".join(f"{p.get('nom')} {p.get('prenom')} (id {p.get('id')})" for p in trouves)
        raise ToolError(f"Plusieurs enseignants correspondent : {noms}. Précise l'identifiant.")
    return trouves[0]


def resumer(cours: list[dict[str, Any]]) -> dict[str, Any]:
    """Met en forme les cours renvoyés par EcoleDirecte."""
    lignes = []
    for c in sorted(cours, key=lambda x: x.get("start_date", "")):
        sd, ed = c.get("start_date", ""), c.get("end_date", "")
        lignes.append({
            "date": sd[:10],
            "debut": sd[11:16],
            "fin": ed[11:16],
            "matiere": c.get("codeMatiere") or None,
            "matiere_libelle": c.get("matiere") or None,
            "classe": c.get("classe") or None,
            "salle": c.get("salle") or None,
            "enseignant": c.get("prof") or None,
            "type": c.get("typeCours"),
            "annule": bool(c.get("isAnnule")),
            "modifie": bool(c.get("isModifie")),
        })
    return {
        "nb_cours": len(lignes),
        "par_jour": dict(Counter(l["date"] for l in lignes)),
        "par_classe": dict(Counter(l["classe"] for l in lignes)),
        "nb_sans_matiere": sum(1 for l in lignes if not l["matiere"]),
        "cours": lignes,
    }


async def emploi_du_temps_enseignant(admin_client, enseignant: str, date_debut: str,
                                     date_fin: str | None = None) -> dict[str, Any]:
    if not _actif():
        raise ToolError("Lecture de l'emploi du temps désactivée (ED_ADMIN_EDT_ACTIF=1 requis).")
    d1, d2 = _periode(date_debut, date_fin)
    profs = await admin_client.list_utilisateurs("professeurs", "")
    prof = choisir_enseignant(profs if isinstance(profs, list) else [], enseignant)
    session = await ouvrir_supervision(
        admin_client, {"id": prof["id"], "nom": prof.get("nom", ""), "type_code": "P"}
    )
    try:
        payload = await session.appeler(
            f"P/{prof['id']}/emploidutemps", "get",
            {"dateDebut": d1, "dateFin": d2, "avecTrous": False},
        )
    finally:
        await session.http.aclose()
    if payload.get("code") != 200:
        raise ToolError(f"emploidutemps : code {payload.get('code')} {payload.get('message') or ''}".strip())
    res = resumer(payload.get("data") or [])
    res.update({
        "enseignant": {"id": prof["id"], "nom": prof.get("nom"), "prenom": prof.get("prenom")},
        "du": d1,
        "au": d2,
        "note": ("Emploi du temps tel qu'EcoleDirecte l'affiche (alimenté par le transfert Vie "
                 "scolaire de Charlemagne). Les vacances et jours fériés n'y apparaissent pas."),
    })
    return res

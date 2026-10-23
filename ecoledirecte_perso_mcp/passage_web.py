"""Passage Web (Charlemagne Passage via EcoleDirecte) : lecture et pointage (écriture, 23/10/2026).

Reproduit l'écran « Passage Web » du site (front relevé le 23/10/2026, PassageWebService) :
  points du compte     : paramètre `listePDP` du module PASSAGEWEB au login (« id:libellé:HHMM:HHMM||… »)
  prévus d'un point    : POST v3/PassageWeb/<pdp>/recupDesPassagesPrevus.awp?verbe=get
  passages d'un jour   : POST v3/PassageWeb/<pdp>/recupDesPassagesWeb/<AAAA-MM-JJ>.awp?verbe=get
  pointer un élève     : POST v3/PassageWeb/<pdp>/recupDesPassagesWeb/<AAAA-MM-JJ>.awp?verbe=post
                         data={"passageWeb": {idPassageWeb:0, idPassant:<idEleve>, typePassant:"E",
                               date:"AAAA-MM-JJ", heure:"HH:MM", idPDP, dateTransmission:"", dateAcq:"",
                               nom, prenom, particule, dateNaissance:"", sexe, photo:"", badge}}
                         → data.idPassageWeb
  supprimer un passage : POST v3/PassageWeb/<idPassageWeb>.awp?verbe=delete (data={})
Le front fixe lui-même date et heure (horloge du navigateur) ; Charlemagne intègre ensuite les
passages par Passage › Passage Web › Intégration et les valorise selon les coches de la fiche élève.

Garde-fous :
  - SIMULATION par défaut (élèves résolus, déjà pointés, inconnus) ; confirm=True après accord ;
  - écriture seulement si ED_PERSO_PASSAGEWEB_ACTIF=1 (jamais sur Azure) ;
  - point vérifié dans la liste du compte ; date au format AAAA-MM-JJ, jamais dans le futur,
    dans l'année scolaire ED_PERSO_ANNEE ; heure HH:MM ;
  - jamais deux passages pour le même élève, le même point et le même jour (relecture avant écriture) ;
  - plafond par appel ED_PERSO_PASSAGEWEB_MAX (défaut 80) ; une seconde entre deux envois ;
    arrêt après 3 erreurs consécutives ;
  - suppression seulement d'un passage relu sur ce point et ce jour, et pas encore intégré ;
  - aucune donnée sensible renvoyée (ni badge, ni photo, ni date de naissance) ;
  - journal local (identifiants seulement) : $ED_PERSO_HOME/passages_web.csv.
"""
from __future__ import annotations

import asyncio
import csv
import os
import re
from datetime import date as _date, datetime
from pathlib import Path
from typing import Any

from mcp.server.mcpserver.exceptions import ToolError

from .config import SETTINGS

JOURNAL = Path(os.environ.get("ED_PERSO_HOME", Path.home() / ".ecoledirecte-perso-mcp")) / "passages_web.csv"
PAUSE_SECONDES = 1.0


class PassageWebError(ToolError):
    """Erreur de préparation ou d'écriture Passage Web (message transmis tel quel)."""


def _actif() -> bool:
    return os.environ.get("ED_PERSO_PASSAGEWEB_ACTIF", "") == "1"


def _max() -> int:
    try:
        return int(os.environ.get("ED_PERSO_PASSAGEWEB_MAX", "80"))
    except ValueError:
        return 80


# ---------------------------------------------------------------- fonctions pures
def analyser_points(liste: str) -> list[dict[str, Any]]:
    """« 6:Garderie:0600:2000||7:Cantine:0600:2000 » → [{id, libelle, heureDebut, heureFin}]."""
    out = []
    for brut in (liste or "").split("||"):
        morceaux = brut.split(":")
        if len(morceaux) < 4 or not morceaux[0].strip().isdigit():
            continue
        hd, hf = morceaux[-2], morceaux[-1]
        out.append({"id": int(morceaux[0]), "libelle": ":".join(morceaux[1:-2]),
                    "heureDebut": f"{hd[:2]}:{hd[-2:]}", "heureFin": f"{hf[:2]}:{hf[-2:]}"})
    return out


def bornes_annee(annee: str | None = None) -> tuple[_date, _date]:
    """Année scolaire EcoleDirecte « 2026-2027 » → (2026-08-15, 2027-07-13)."""
    m = re.fullmatch(r"(\d{4})-(\d{4})", annee or SETTINGS.annee)
    if not m:
        raise PassageWebError(f"Année scolaire illisible : {annee or SETTINGS.annee!r}")
    return _date(int(m.group(1)), 8, 15), _date(int(m.group(2)), 7, 13)


def verifier_date(jour: str, aujourd_hui: _date | None = None) -> str:
    try:
        d = datetime.strptime(jour, "%Y-%m-%d").date()
    except (TypeError, ValueError) as exc:
        raise PassageWebError(f"Date attendue au format AAAA-MM-JJ : {jour!r}") from exc
    debut, fin = bornes_annee()
    if d > (aujourd_hui or _date.today()):
        raise PassageWebError(f"Date dans le futur refusée : {jour}")
    if not debut <= d <= fin:
        raise PassageWebError(f"Date hors de l'année scolaire {SETTINGS.annee} : {jour}")
    return jour


def verifier_heure(heure: str) -> str:
    if not isinstance(heure, str) or not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", heure):
        raise PassageWebError(f"Heure attendue au format HH:MM : {heure!r}")
    return heure


def construire_passage(id_pdp: int, jour: str, heure: str, eleve: dict[str, Any], badge: str = "") -> dict[str, Any]:
    """Objet `passageWeb` exactement comme le front (selectEleve → addPassageWebFromScanReponse)."""
    return {"idPassageWeb": 0, "idPassant": int(eleve["idEleve"]), "typePassant": "E",
            "date": jour, "heure": heure, "idPDP": int(id_pdp), "dateTransmission": "", "dateAcq": "",
            "nom": eleve.get("nom") or "", "prenom": eleve.get("prenom") or "",
            "particule": eleve.get("particule") or "", "dateNaissance": "",
            "sexe": eleve.get("sexe") or "", "photo": "", "badge": str(badge or "")}


def _public(e: dict[str, Any]) -> dict[str, Any]:
    return {"idEleve": e.get("idEleve"), "nom": e.get("nom"), "prenom": e.get("prenom"),
            "classe": e.get("classeCode") or e.get("classe"), "regime": e.get("regimeCode")}


def _passage_public(p: dict[str, Any]) -> dict[str, Any]:
    return {"idPassageWeb": p.get("idPassageWeb"), "idEleve": p.get("idPassant"),
            "typePassant": p.get("typePassant"), "nom": p.get("nom"), "prenom": p.get("prenom"),
            "date": p.get("date"), "heure": p.get("heure"),
            "integre": bool(p.get("dateAcq")), "dateTransmission": p.get("dateTransmission")}


# ---------------------------------------------------------------- lecture
def points(client) -> list[dict[str, Any]]:
    pts = analyser_points(client.points_passage_web())
    if not pts:
        raise PassageWebError("Aucun point Passage Web pour ce compte (fiche adulte non désignée, "
                              "envoi vers EcoleDirecte non fait, ou session à renouveler).")
    return pts


def _point(client, id_pdp: int) -> dict[str, Any]:
    for p in points(client):
        if p["id"] == int(id_pdp):
            return p
    raise PassageWebError(f"Point Passage Web {id_pdp} absent des points du compte.")


async def lister_points(client) -> list[dict[str, Any]]:
    await client.auth.ensure_session(client._http)
    return points(client)


async def prevus(client, id_pdp: int) -> dict[str, Any]:
    await client.auth.ensure_session(client._http)
    p = _point(client, id_pdp)
    data = await client.passage_web_prevus(p["id"])
    eleves = [_public(e) for e in (data or []) if isinstance(e, dict)]
    return {"point": p, "nombre": len(eleves), "eleves": eleves}


async def _passages_du_jour(client, id_pdp: int, jour: str) -> list[dict[str, Any]]:
    data = await client.passage_web_jour(int(id_pdp), jour)
    if isinstance(data, dict):
        data = data.get("listePassages") or []
    return [p for p in (data or []) if isinstance(p, dict)]


async def passages_du_jour(client, id_pdp: int, jour: str) -> dict[str, Any]:
    await client.auth.ensure_session(client._http)
    p = _point(client, id_pdp)
    try:
        d = datetime.strptime(jour, "%Y-%m-%d").date()
    except (TypeError, ValueError) as exc:
        raise PassageWebError(f"Date attendue au format AAAA-MM-JJ : {jour!r}") from exc
    lst = [_passage_public(x) for x in await _passages_du_jour(client, p["id"], d.isoformat())]
    return {"point": p, "date": jour, "nombre": len(lst),
            "integres": sum(x["integre"] for x in lst), "passages": lst}


async def _annuaire(client, ids: set[int]) -> dict[int, dict[str, Any]]:
    """Nom, prénom, classe et sexe des élèves non prévus, lus classe par classe."""
    trouves: dict[int, dict[str, Any]] = {}
    if not ids:
        return trouves
    niv = await client.niveaux()
    for etab in (niv or {}).get("etablissements") or []:
        for n in etab.get("niveaux") or []:
            for cl in n.get("classes") or []:
                data = await client.classe_eleves(str(cl.get("id")))
                for e in (data or {}).get("eleves") or []:
                    if isinstance(e, dict) and e.get("id") in ids:
                        trouves[int(e["id"])] = {"idEleve": int(e["id"]), "nom": e.get("nom"),
                                                 "prenom": e.get("prenom"), "particule": e.get("particule"),
                                                 "sexe": e.get("sexe"), "classeCode": cl.get("code")}
                if len(trouves) == len(ids):
                    return trouves
    return trouves


# ---------------------------------------------------------------- écriture
def _journaliser(action: str, id_pdp: int, jour: str, heure: str, id_eleve: Any, id_passage_web: Any,
                 statut: str) -> None:
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    neuf = not JOURNAL.exists()
    with JOURNAL.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        if neuf:
            w.writerow(["horodatage", "action", "point", "date", "heure", "idEleve", "idPassageWeb", "statut"])
        w.writerow([datetime.now().isoformat(timespec="seconds"), action, id_pdp, jour, heure,
                    id_eleve, id_passage_web, statut])


async def pointer(client, id_pdp: int, jour: str, heure: str, id_eleves: list[int],
                  badges: dict[str, str] | None = None, confirm: bool = False) -> dict[str, Any]:
    await client.auth.ensure_session(client._http)
    p = _point(client, id_pdp)
    verifier_date(jour)
    verifier_heure(heure)
    ids: list[int] = []
    for x in id_eleves or []:
        try:
            i = int(x)
        except (TypeError, ValueError) as exc:
            raise PassageWebError(f"Identifiant d'élève invalide : {x!r}") from exc
        if i not in ids:
            ids.append(i)
    if not ids:
        raise PassageWebError("Aucun élève à pointer.")
    if len(ids) > _max():
        raise PassageWebError(f"{len(ids)} élèves : {_max()} au plus par appel (ED_PERSO_PASSAGEWEB_MAX).")
    badges = {str(k): str(v) for k, v in (badges or {}).items()}

    deja = {int(x.get("idPassant")) for x in await _passages_du_jour(client, p["id"], jour)
            if str(x.get("typePassant") or "E") == "E" and x.get("idPassant") is not None}
    prev = {int(e["idEleve"]): e for e in (await client.passage_web_prevus(p["id"]) or [])
            if isinstance(e, dict) and e.get("idEleve") is not None}
    hors = await _annuaire(client, {i for i in ids if i not in prev and i not in deja})

    plan = []
    for i in ids:
        e = prev.get(i) or hors.get(i)
        ligne = {"idEleve": i, "nom": (e or {}).get("nom"), "prenom": (e or {}).get("prenom"),
                 "classe": (e or {}).get("classeCode"), "prevu": i in prev}
        if i in deja:
            ligne["statut"] = "déjà pointé"
        elif e is None:
            ligne["statut"] = "inconnu (pas dans les classes EcoleDirecte)"
        else:
            ligne["statut"] = "à pointer"
            ligne["_eleve"], ligne["_badge"] = e, (e.get("badge") if i in prev else badges.get(str(i), ""))
        plan.append(ligne)
    a_pointer = [x for x in plan if x["statut"] == "à pointer"]
    resume = {"point": p, "date": jour, "heure": heure, "demandes": len(ids), "a_pointer": len(a_pointer),
              "deja_pointes": sum(x["statut"] == "déjà pointé" for x in plan),
              "inconnus": sum(x["statut"].startswith("inconnu") for x in plan),
              "sans_badge": sum(not x.get("_badge") for x in a_pointer)}

    def _sans_prive(lst):
        return [{k: v for k, v in x.items() if not k.startswith("_")} for x in lst]

    if not confirm or not a_pointer:
        return {"mode": "simulation", **resume, "eleves": _sans_prive(plan),
                "ecriture_active": _actif(),
                "note": "Rien n'a été écrit. Montrer cette simulation et obtenir l'accord avant confirm=True."}
    if not _actif():
        raise PassageWebError("Écriture Passage Web désactivée : ED_PERSO_PASSAGEWEB_ACTIF≠1.")

    erreurs_suivies = 0
    for n, x in enumerate(a_pointer):
        if n:
            await asyncio.sleep(PAUSE_SECONDES)
        try:
            data = await client.ajouter_passage_web(construire_passage(p["id"], jour, heure, x["_eleve"], x["_badge"]))
            x["idPassageWeb"] = (data or {}).get("idPassageWeb") if isinstance(data, dict) else None
            x["statut"] = "pointé"
            erreurs_suivies = 0
        except ToolError as exc:
            x["statut"] = f"erreur : {exc}"
            erreurs_suivies += 1
        _journaliser("pointer", p["id"], jour, heure, x["idEleve"], x.get("idPassageWeb"), x["statut"])
        if erreurs_suivies >= 3:
            for y in a_pointer[n + 1:]:
                y["statut"] = "non tenté (arrêt après 3 erreurs)"
            break
    relu = await _passages_du_jour(client, p["id"], jour)
    return {"mode": "écriture", **resume, "pointes": sum(x["statut"] == "pointé" for x in plan),
            "erreurs": sum(x["statut"].startswith("erreur") for x in plan),
            "passages_du_jour_apres": len(relu), "eleves": _sans_prive(plan)}


async def supprimer(client, id_pdp: int, jour: str, ids_passage_web: list[int],
                    confirm: bool = False) -> dict[str, Any]:
    await client.auth.ensure_session(client._http)
    p = _point(client, id_pdp)
    verifier_date(jour)
    lus = {int(x["idPassageWeb"]): x for x in await _passages_du_jour(client, p["id"], jour)
           if x.get("idPassageWeb") is not None}
    plan = []
    for i in dict.fromkeys(int(v) for v in ids_passage_web or []):
        x = lus.get(i)
        if x is None:
            plan.append({"idPassageWeb": i, "statut": "introuvable sur ce point ce jour-là"})
        elif x.get("dateAcq"):
            plan.append({**_passage_public(x), "statut": "déjà intégré dans Charlemagne : à annuler dans Passage"})
        else:
            plan.append({**_passage_public(x), "statut": "à supprimer"})
    cibles = [x for x in plan if x["statut"] == "à supprimer"]
    if not confirm or not cibles:
        return {"mode": "simulation", "point": p, "date": jour, "a_supprimer": len(cibles), "passages": plan,
                "ecriture_active": _actif(), "note": "Rien n'a été supprimé."}
    if not _actif():
        raise PassageWebError("Écriture Passage Web désactivée : ED_PERSO_PASSAGEWEB_ACTIF≠1.")
    for n, x in enumerate(cibles):
        if n:
            await asyncio.sleep(PAUSE_SECONDES)
        try:
            await client.supprimer_passage_web(x["idPassageWeb"])
            x["statut"] = "supprimé"
        except ToolError as exc:
            x["statut"] = f"erreur : {exc}"
        _journaliser("supprimer", p["id"], jour, x.get("heure") or "", x.get("idEleve"), x["idPassageWeb"], x["statut"])
    return {"mode": "écriture", "point": p, "date": jour, "supprimes": sum(x["statut"] == "supprimé" for x in plan),
            "passages": plan}

"""Dépôt d'une pièce dans une « liste de pièces à verser » EcoleDirecte, AU NOM
D'UNE FAMILLE, via la supervision admin — ÉCRITURE, exception n°2 (23/09/2026).

Contexte : les listes de pièces à verser (ex. « Fiches Rentrée ») sont créées
dans Charlemagne Administratif et publiées sur EcoleDirecte ; seules les
familles peuvent y téléverser. L'établissement dépose donc les fiches papier
scannées en se plaçant dans l'espace de la famille (supervision), exactement
comme le fait l'interface admin (bouton « Supervision EcoleDirecte »).

Flux (relevé par lecture des fronts admin + famille le 23/09/2026, voir
docs/cartographie-api-admin.md §8) :
  1. POST v3/admin/supervision.awp?id=<compte>&type=1|2&n=<NOM[:3]>&version=
       formulaire `token=<jeton admin>` → redirection loginExterne?atoken=…&i=…
  2. POST v3/loginexterne.awp?verbe=post   data={"aToken":…, "i":…}
       → en-têtes X-Code (200) et X-Token (jeton famille)
  3. POST v3/familledocuments.awp?verbe=get → listesPiecesAVerser
       {listesPieces, pieces, personnes, televersements}
  4. POST v3/televersement.awp?verbe=post&mode=DOCUMENTS  (multipart)
       file + idListePiece + idPiece + idPersonne, en-tête X-Token
  5. relecture (3) pour confirmer que le dépôt apparaît.

Garde-fous :
  - sans confirm=True : SIMULATION, aucun appel réseau d'écriture ni supervision ;
  - écriture activée seulement si ED_ADMIN_DEPOT_ACTIF=1 (jamais sur Azure) ;
  - fichier : PDF uniquement, sous ED_ADMIN_DEPOT_RACINE, ≤ 10 Mo ;
  - liste : libellé dans ED_ADMIN_DEPOT_LISTES (défaut « Fiches Rentrée ») ;
  - ne remplace JAMAIS un dépôt existant, ne supprime rien, ne touche pas
    à la messagerie ;
  - chaque dépôt réel est journalisé (CSV local, sans jeton).
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

import httpx
from mcp.server.mcpserver.exceptions import ToolError

from .auth import encode_form_data
from .config import SETTINGS

WWW_API_BASE = os.environ.get("ED_WWW_API_BASE", "https://api.ecoledirecte.com/v3/")
WWW_API_VERSION = os.environ.get("ED_WWW_API_VERSION", "4.102.1")
MAX_BYTES = 10 * 1024 * 1024  # limite du site pour les pièces à verser
JOURNAL = SETTINGS.home_dir / "depots_pieces.csv"


class DepotError(ToolError):
    """Erreur de dépôt (message transmis tel quel, jamais de jeton dedans)."""


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return re.sub(r"[^A-Z]", "", "".join(c for c in s if not unicodedata.combining(c)).upper())


def _listes_autorisees() -> list[str]:
    raw = os.environ.get("ED_ADMIN_DEPOT_LISTES", "Fiches Rentrée")
    return [_norm(x) for x in raw.split("|") if x.strip()]


def _depot_actif() -> bool:
    return os.environ.get("ED_ADMIN_DEPOT_ACTIF", "") == "1"


def check_fichier(fichier: str) -> Path:
    racine = os.environ.get("ED_ADMIN_DEPOT_RACINE", "")
    if not racine:
        raise DepotError("ED_ADMIN_DEPOT_RACINE n'est pas défini : aucun dossier source autorisé.")
    p = Path(fichier).expanduser().resolve()
    r = Path(racine).expanduser().resolve()
    if r not in p.parents:
        raise DepotError(f"Fichier hors du dossier autorisé ({r}).")
    if p.suffix.lower() != ".pdf":
        raise DepotError("Seuls les fichiers PDF sont acceptés.")
    if not p.is_file():
        raise DepotError(f"Fichier introuvable : {p.name}")
    size = p.stat().st_size
    if size == 0 or size > MAX_BYTES:
        raise DepotError(f"Taille de fichier refusée ({size} octets).")
    with p.open("rb") as fh:
        if fh.read(5) != b"%PDF-":
            raise DepotError("Le fichier n'est pas un PDF valide (en-tête %PDF absent).")
    return p


def _journaliser(row: dict[str, Any]) -> None:
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    new = not JOURNAL.exists()
    with JOURNAL.open("a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(row.keys()))
        if new:
            w.writeheader()
        w.writerow(row)


# ----------------------------------------------------------------------
# Résolution élève → compte famille (lecture admin, sans supervision)
# ----------------------------------------------------------------------
async def resoudre_eleve_famille(admin_client, id_eleve: int, eleves: list | None = None,
                                 familles: list | None = None) -> dict[str, Any]:
    eleves = eleves if eleves is not None else await admin_client.list_utilisateurs("eleves", "")
    eleve = next((e for e in eleves if int(e.get("id", -1)) == int(id_eleve)), None)
    if not eleve:
        raise DepotError(f"Élève {id_eleve} introuvable dans EcoleDirecte.")
    familles = familles if familles is not None else await admin_client.list_utilisateurs("familles", "")
    cle = (_norm(eleve["nom"]), _norm(eleve["prenom"]), str(eleve.get("idClasse")))
    comptes = [
        f for f in familles
        if any((_norm(c.get("nom", "")), _norm(c.get("prenom", "")), str(c.get("idClasse"))) == cle
               for c in f.get("enfants", []))
    ]
    if not comptes:
        raise DepotError(f"Aucun compte famille rattaché à {eleve['nom']} {eleve['prenom']}.")
    comptes.sort(key=lambda f: (f.get("type") != "responsable", int(f.get("id", 0))))
    return {"eleve": eleve, "comptes": comptes, "compte": comptes[0]}


# ----------------------------------------------------------------------
# Session famille via supervision
# ----------------------------------------------------------------------
class SessionFamille:
    def __init__(self, http: httpx.AsyncClient, token: str, compte: dict[str, Any]):
        self.http, self.token, self.compte = http, token, compte

    def _headers(self) -> dict[str, str]:
        return {"X-Token": self.token, "User-Agent": SETTINGS.user_agent,
                "Accept": "application/json, text/plain, */*"}

    def _take_token(self, resp: httpx.Response, payload: dict[str, Any] | None) -> None:
        t = resp.headers.get("X-Token") or (payload or {}).get("token")
        if t:
            self.token = t

    async def documents(self) -> dict[str, Any]:
        url = f"{WWW_API_BASE}familledocuments.awp?archive=&verbe=get&v={WWW_API_VERSION}"
        resp = await self.http.post(url, content=encode_form_data({}),
                                    headers={**self._headers(),
                                             "Content-Type": "application/x-www-form-urlencoded"})
        payload = resp.json()
        self._take_token(resp, payload)
        if payload.get("code") != 200:
            raise DepotError(f"familledocuments : code {payload.get('code')}")
        return (payload.get("data") or {}).get("listesPiecesAVerser") or {}

    async def televerser(self, p: Path, id_liste: int, id_piece: int, id_personne: int) -> dict[str, Any]:
        url = f"{WWW_API_BASE}televersement.awp?verbe=post&mode=DOCUMENTS&v={WWW_API_VERSION}"
        files = {"file": (p.name, p.read_bytes(), "application/pdf")}
        # Reproduit exactement le composant Dropzone du site famille : les params
        # en champs séparés, PUIS un champ `data` = JSON des mêmes params
        # (onSending → formData.set("data", JSON.stringify(params))). Sans ce
        # champ, l'API répond code 512.
        params = {"idListePiece": int(id_liste), "idPiece": int(id_piece), "idPersonne": int(id_personne)}
        data = {k: str(v) for k, v in params.items()}
        data["data"] = json.dumps(params)
        headers = {**self._headers(), "Accept": "application/json", "Cache-Control": "no-cache",
                   "X-Requested-With": "XMLHttpRequest"}
        resp = await self.http.post(url, data=data, files=files, headers=headers, timeout=120)
        try:
            payload = resp.json()
        except ValueError as exc:
            raise DepotError(f"televersement : réponse non JSON (HTTP {resp.status_code})") from exc
        self._take_token(resp, payload)
        return payload


async def ouvrir_supervision(admin_client, compte: dict[str, Any]) -> SessionFamille:
    type_code = "2" if compte.get("type") == "conjoint" else "1"
    url = (f"{SETTINGS.api_base}supervision.awp?id={compte['id']}&type={type_code}"
           f"&n={quote(compte['nom'][:3])}&version=")
    http = httpx.AsyncClient(timeout=SETTINGS.timeout_seconds, follow_redirects=False)
    m_at = m_i = None
    for tentative in (1, 2):
        # 2e tentative : le jeton admin a pu être invalidé (session unique par
        # compte) → re-login automatique via le Trousseau, puis nouvel essai.
        if tentative == 2:
            admin_client.auth.invalidate()
        session = await admin_client.auth.ensure_session(admin_client._http)
        resp = await http.post(url, data={"token": session.token},
                               headers={"User-Agent": SETTINGS.user_agent})
        blob = unquote(resp.headers.get("location", "") + " " + resp.text)
        m_at = re.search(r"atoken=([^&\"'\s<>]+)", blob)
        m_i = re.search(r"[?&]i=([^&\"'\s<>]+)", blob)
        if m_at:
            break
    if not m_at:
        await http.aclose()
        raise DepotError(f"Supervision refusée ou format inattendu (HTTP {resp.status_code}).")
    body = {"aToken": m_at.group(1)}
    if m_i:
        body["i"] = m_i.group(1)
    resp2 = await http.post(
        f"{WWW_API_BASE}loginexterne.awp?verbe=post&v={WWW_API_VERSION}",
        content=encode_form_data(body),
        headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": SETTINGS.user_agent},
    )
    code = resp2.headers.get("X-Code")
    try:
        payload = resp2.json()
    except ValueError:
        payload = {}
    token = resp2.headers.get("X-Token") or payload.get("token")
    if str(code or payload.get("code")) != "200" or not token:
        await http.aclose()
        raise DepotError(f"Ouverture de session famille refusée (code {code or payload.get('code')}).")
    return SessionFamille(http, token, compte)


# ----------------------------------------------------------------------
# Opération principale
# ----------------------------------------------------------------------
def _trouver_liste(lp: dict[str, Any], id_eleve: int, id_compte: int | None = None,
                   piece: str | None = None) -> tuple[dict, dict, int]:
    """→ (liste, pièce, idPersonne). Listes autorisées seulement. Si une liste
    contient plusieurs pièces, `piece` (libellé) est obligatoire. Liste de type
    « F » (famille) : le dépôt se rattache au compte famille, sinon à l'élève."""
    autorisees = _listes_autorisees()
    listes = [l for l in lp.get("listesPieces", []) if _norm(l.get("libelle", "")) in autorisees]
    if not listes:
        raise DepotError("Aucune liste de pièces autorisée visible pour cette famille.")
    candidats = []
    for liste in listes:
        pieces = [p for p in lp.get("pieces", [])
                  if p.get("idListePiece") == liste.get("id") and p.get("id") in (liste.get("pieces") or [p.get("id")])]
        if piece:
            pieces = [p for p in pieces if _norm(p.get("libelle", "")) == _norm(piece)]
        elif len(pieces) > 1:
            raise DepotError(f"La liste « {liste.get('libelle')} » contient {len(pieces)} pièces : préciser la pièce "
                             f"({', '.join(p.get('libelle', '') for p in pieces)}).")
        candidats += [(liste, p) for p in pieces]
    if len(candidats) != 1:
        raise DepotError("Pièce introuvable dans les listes autorisées." if not candidats
                         else "Plusieurs pièces correspondent : préciser la pièce.")
    liste, pc = candidats[0]
    id_personne = id_compte if liste.get("type") == "F" else id_eleve
    if id_personne is None:
        raise DepotError("Liste de type famille : compte famille inconnu.")
    personnes = liste.get("personnes") or [x.get("id") for x in lp.get("personnes", [])]
    if int(id_personne) not in [int(x) for x in personnes]:
        qui = "Ce compte famille" if liste.get("type") == "F" else "L'élève"
        raise DepotError(f"{qui} n'est pas concerné par cette liste dans l'espace de la famille.")
    return liste, pc, int(id_personne)


def _depot_existant(lp: dict[str, Any], id_liste: int, id_piece: int, id_personne: int) -> dict | None:
    return next((t for t in lp.get("televersements", [])
                 if t.get("idListePiece") == id_liste and t.get("idPiece") == id_piece
                 and int(t.get("idPersonne", -1)) == int(id_personne)), None)


async def deposer_piece(admin_client, id_eleve: int, fichier: str, confirm: bool = False,
                        eleves: list | None = None, familles: list | None = None,
                        piece: str | None = None) -> dict[str, Any]:
    p = check_fichier(fichier)
    res = await resoudre_eleve_famille(admin_client, id_eleve, eleves, familles)
    eleve, compte = res["eleve"], res["compte"]
    apercu = {
        "eleve": f"{eleve['nom']} {eleve['prenom']} ({eleve.get('libelleClasse')}, id {eleve['id']})",
        "compte_famille": f"{compte.get('civilite','')} {compte['nom']} {compte['prenom']} (id {compte['id']}, {compte.get('type')})",
        "fichier": p.name,
        "taille_octets": p.stat().st_size,
        **({"piece_demandee": piece} if piece else {}),
    }
    if not confirm:
        return {**apercu, "depot_effectue": False,
                "message": "Simulation : rien n'a été envoyé ni supervisé. Rappeler avec confirm=True."}
    if not _depot_actif():
        raise DepotError("Écriture désactivée (ED_ADMIN_DEPOT_ACTIF≠1).")

    fam = await ouvrir_supervision(admin_client, compte)
    try:
        lp = await fam.documents()
        liste, pc, id_personne = _trouver_liste(lp, eleve["id"], compte["id"], piece)
        existant = _depot_existant(lp, liste["id"], pc["id"], id_personne)
        if existant:
            return {**apercu, "depot_effectue": False, "deja_depose": True,
                    "depot_existant": {k: existant.get(k) for k in ("libelle", "date", "isLock")},
                    "message": "Un document est déjà déposé pour cette pièce : rien n'a été remplacé."}
        payload = await fam.televerser(p, liste["id"], pc["id"], id_personne)
        lp2 = await fam.documents()
        verif = _depot_existant(lp2, liste["id"], pc["id"], id_personne)
        ok = payload.get("code") == 200 and verif is not None
        _journaliser({
            "horodatage": datetime.now().isoformat(timespec="seconds"),
            "id_eleve": eleve["id"], "eleve": f"{eleve['nom']} {eleve['prenom']}",
            "classe": eleve.get("libelleClasse"), "id_compte_famille": compte["id"],
            "liste": liste.get("libelle"), "piece": pc.get("libelle"), "id_personne": id_personne, "fichier": p.name,
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            "code_api": payload.get("code"), "verifie": ok,
        })
        if not ok:
            raise DepotError(f"Dépôt non confirmé (code {payload.get('code')} — {payload.get('message') or ''}).")
        return {**apercu, "depot_effectue": True, "liste": liste.get("libelle"),
                "piece": pc.get("libelle"),
                "depot": {k: verif.get(k) for k in ("libelle", "date", "isLock")}}
    finally:
        await fam.http.aclose()

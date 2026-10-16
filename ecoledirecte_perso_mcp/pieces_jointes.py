"""Téléchargement des pièces jointes de la messagerie (lecture seule).

Le fichier est retrouvé dans la LISTE de la messagerie (qui ne marque aucun message
lu) : on vérifie ainsi qu'il appartient bien au message indiqué, puis on le récupère
comme le bouton de téléchargement du site (telechargement.awp, type PIECE_JOINTE).
Garde-fous : dossier local obligatoire (ED_PERSO_PJ_DIR, absent sur un serveur
distant = outil refusé), documents bancaires refusés, 20 Mo au plus, format contrôlé
(PDF, JPEG, PNG, GIF, HEIC, Office), droits 600, jamais d'écrasement.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import unicodedata
from typing import Any

from mcp.server.mcpserver.exceptions import ToolError

from .client import DOSSIERS

MOTIFS_BANCAIRES = re.compile(r"sepa|rib\b|iban|mandat|pr[ée]l[èe]vement", re.I)
MAX_BYTES = 20 * 1024 * 1024
FORMATS = ((b"%PDF", ".pdf"), (b"\xff\xd8\xff", ".jpg"), (b"\x89PNG", ".png"), (b"GIF8", ".gif"),
           (b"PK\x03\x04", None), (b"\xd0\xcf\x11\xe0", ".doc"))
_EXT_ZIP = (".docx", ".xlsx", ".pptx", ".odt", ".ods")


def dossier_pieces_jointes() -> Path:
    d = os.environ.get("ED_PERSO_PJ_DIR")
    if not d:
        raise ToolError("Téléchargement désactivé : définir ED_PERSO_PJ_DIR (dossier local où "
                        "enregistrer les pièces jointes).")
    p = Path(d).expanduser()
    p.mkdir(parents=True, exist_ok=True)
    return p


def _extension(contenu: bytes, libelle: str) -> str | None:
    suffixe = Path(libelle).suffix.lower()
    if contenu[4:12] in (b"ftypheic", b"ftypheix", b"ftypmif1"):
        return ".heic"
    for magie, ext in FORMATS:
        if contenu.startswith(magie):
            if ext is None:  # conteneur zip : seulement un document Office
                return suffixe if suffixe in _EXT_ZIP else None
            return ext
    return None


def _nom_sur(texte: str) -> str:
    t = unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode()
    t = re.sub(r"[^A-Za-z0-9._-]+", "_", t).strip("._")
    return t[:80] or "piece_jointe"


async def _trouver_message(client, id_message: int, boite: str) -> dict[str, Any]:
    for page in range(10):
        data = await client.list_messages(boite=boite, page=page, items=100)
        msgs = ((data or {}).get("messages") or {}).get(boite) or []
        for m in msgs:
            if int(m.get("id", -1)) == int(id_message):
                return m
        if len(msgs) < 100:
            break
    raise ToolError(f"Message {id_message} introuvable dans le dossier '{boite}' (année en cours).")


async def telecharger_piece_jointe(client, id_message: int, id_fichier: int | None = None,
                                   boite: str = "received") -> dict[str, Any]:
    """Télécharge une pièce jointe (ou toutes, si id_fichier est omis) d'un message."""
    if boite not in DOSSIERS:
        raise ToolError("boite doit être 'received', 'sent', 'archived' ou 'draft'.")
    dossier = dossier_pieces_jointes()
    msg = await _trouver_message(client, id_message, boite)
    fichiers = [f for f in (msg.get("files") or []) if isinstance(f, dict) and f.get("id") is not None]
    if not fichiers:
        raise ToolError(f"Le message {id_message} n'a pas de pièce jointe.")
    if id_fichier is not None:
        fichiers = [f for f in fichiers if int(f["id"]) == int(id_fichier)]
        if not fichiers:
            raise ToolError(f"La pièce jointe {id_fichier} n'appartient pas au message {id_message}.")
    resultats = []
    for f in fichiers:
        libelle = str(f.get("libelle") or f"piece_{f['id']}")
        ligne: dict[str, Any] = {"id_fichier": f["id"], "libelle": libelle}
        if MOTIFS_BANCAIRES.search(libelle):
            ligne["refus"] = "document bancaire (mandat SEPA, RIB…) : jamais téléchargé par le connecteur"
            resultats.append(ligne)
            continue
        contenu = await client.telecharger_piece_jointe_brut(int(f["id"]))
        if len(contenu) > MAX_BYTES:
            ligne["refus"] = "fichier trop volumineux (> 20 Mo)"
        elif not (ext := _extension(contenu, libelle)):
            ligne["refus"] = "format non reconnu (PDF, image ou document Office attendus)"
        else:
            base = f"msg{int(id_message)}_{f['id']}_{_nom_sur(Path(libelle).stem)}"
            chemin, n = dossier / f"{base}{ext}", 2
            while chemin.exists():
                chemin, n = dossier / f"{base}_{n}{ext}", n + 1
            fd = os.open(chemin, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as out:
                out.write(contenu)
            ligne.update({"fichier": str(chemin), "octets": len(contenu), "format": ext.lstrip(".")})
        resultats.append(ligne)
    return {"message": {"id": msg.get("id"), "date": msg.get("date"), "objet": msg.get("subject"),
                        "lu": msg.get("read")},
            "pieces_jointes": resultats,
            "note": "Message non ouvert : son état lu/non lu est inchangé."}

"""Messagerie EcoleDirecte du compte connecté : BROUILLON et ENVOI (écriture, 01/10/2026).

Reproduit le formulaire « Nouveau message » du front (relevé le 01/10/2026) :
  POST v3/<personnels>/<id>/messages.awp?verbe=post
  data={"message": {subject, content=base64(escapeHTMLEncode(html)), groupesDestinataires,
                    files:[], transfertFiles:[], read:true, from:{role, id, read:true},
                    brouillon: true|false}, "anneeMessages": ""}
Destinataires : contacts renvoyés par messagerie/contacts/{familles,personnels} (lecture), complétés
de `to_cc_cci` (to|cc|cci) et, pour une famille, `type="1"` ; regroupés par type
(`groupesDestinataires=[{destinataires:[…], selection:{type}}]`).

Le compte connecté est le compte PARTAGÉ du secrétariat (accord de sa titulaire, 01/10/2026) :
les messages partent sous son nom. Garde-fous :
  - SIMULATION par défaut : destinataires résolus, objet et texte affichés, rien n'est écrit ;
  - `mode="brouillon"` (déposé dans les brouillons, l'utilisateur l'envoie lui-même depuis
    EcoleDirecte) ou `mode="envoi"` ; dans les deux cas confirm=True après accord explicite ;
  - écriture activée seulement si ED_PERSO_MESSAGERIE_ACTIF=1 (jamais sur Azure) ;
  - plafond de destinataires par message : ED_PERSO_MESSAGERIE_MAX_DEST (défaut 30) ;
  - pas de pièce jointe, pas de réponse/transfert automatique, pas d'envoi différé (v1) ;
  - journal local (sans contenu du message) : ~/.ecoledirecte-perso-mcp/messages_envoyes.csv.
"""
from __future__ import annotations

import base64
import csv
import html
import os
from datetime import datetime
from html.entities import codepoint2name
from pathlib import Path
from typing import Any

from mcp.server.mcpserver.exceptions import ToolError

TYPES_CONTACTS = {"famille": "familles", "personnel": "personnels"}
TYPE_FAMILLE_RESPONSABLE = "1"
JOURNAL = Path(os.environ.get("ED_PERSO_HOME", Path.home() / ".ecoledirecte-perso-mcp")) / "messages_envoyes.csv"


class MessagerieError(ToolError):
    """Erreur de préparation ou d'envoi d'un message (message transmis tel quel)."""


def _actif() -> bool:
    return os.environ.get("ED_PERSO_MESSAGERIE_ACTIF", "") == "1"


def _max_dest() -> int:
    try:
        return int(os.environ.get("ED_PERSO_MESSAGERIE_MAX_DEST", "30"))
    except ValueError:
        return 30


# ---------------------------------------------------------------- fonctions pures
def escape_html_encode(s: str) -> str:
    """Équivalent de escapeHTMLEncode du front : caractères non ASCII → entités HTML."""
    out = []
    for ch in s:
        o = ord(ch)
        if o < 128:
            out.append(ch)
        elif o in codepoint2name:
            out.append(f"&{codepoint2name[o]};")
        else:
            out.append(f"&#{o};")
    return "".join(out)


def texte_vers_html(texte: str) -> str:
    """Texte brut → HTML simple (paragraphes, retours à la ligne), échappé."""
    paras = [p for p in texte.replace("\r\n", "\n").split("\n\n")]
    return "".join("<p>" + html.escape(p).replace("\n", "<br>") + "</p>" for p in paras if p.strip())


def contenu_message(texte: str) -> str:
    return base64.b64encode(escape_html_encode(texte_vers_html(texte)).encode("ascii")).decode()


def libelle_contact(c: dict[str, Any]) -> str:
    if c.get("responsable", {}).get("contacts") and c.get("type") == TYPE_FAMILLE_RESPONSABLE:
        r = c["responsable"]
        return f"{', '.join(r['contacts'])} (parent de {c.get('prenom')} {c.get('nom')}, {c.get('classe', {}).get('libelle', '')})"
    f = (c.get("fonction") or {}).get("libelle")
    nom = " ".join(x for x in (c.get("civilite"), c.get("prenom"), c.get("nom")) if x)
    return f"{nom} ({f})" if f else nom


def construire_message(sujet: str, texte: str, destinataires: list[dict[str, Any]],
                       role: str, id_compte: int, brouillon: bool) -> dict[str, Any]:
    groupes: dict[str, list[dict[str, Any]]] = {}
    for d in destinataires:
        groupes.setdefault(d["type"], []).append(d)
    return {"subject": sujet, "content": contenu_message(texte),
            "groupesDestinataires": [{"destinataires": v, "selection": {"type": k}} for k, v in groupes.items()],
            "transfertFiles": [], "files": [], "read": True,
            "from": {"role": role, "id": int(id_compte), "read": True}, "brouillon": bool(brouillon)}


# ---------------------------------------------------------------- résolution des destinataires
async def _contacts(client, type_: str, nom: str = "") -> list[dict[str, Any]]:
    if type_ == "famille":
        q = {"idClasse": 0, "idGroupe": 0, "idMatiere": 0, "codeMatiere": "", "nom": nom,
             "recupAll": 0 if nom else 1, "onlyPresents": 0}
    else:
        q = {}
    d = await client.get(f"messagerie/contacts/{TYPES_CONTACTS[type_]}", q)
    return (d or {}).get("contacts") or []


async def rechercher_contacts(client, type_: str, nom: str) -> list[dict[str, Any]]:
    """LECTURE — annuaire de la messagerie (familles : par nom d'élève ; personnels)."""
    if type_ not in TYPES_CONTACTS:
        raise MessagerieError("type doit être 'famille' ou 'personnel'.")
    res = []
    for c in await _contacts(client, type_, nom if type_ == "famille" else ""):
        if type_ == "personnel" and nom and nom.lower() not in f"{c.get('nom', '')} {c.get('prenom', '')}".lower():
            continue
        if type_ == "famille":
            r = c.get("responsable") or {}
            res.append({"type": "famille", "id_eleve": c.get("id"), "eleve": f"{c.get('prenom')} {c.get('nom')}",
                        "classe": (c.get("classe") or {}).get("libelle"), "responsable": r.get("typeResp"),
                        "id_responsable": r.get("id"), "parents": r.get("contacts"),
                        "messagerie_active": c.get("messagerieActive")})
        else:
            res.append({"type": "personnel", "id": c.get("id"), "nom": libelle_contact(c),
                        "messagerie_active": c.get("messagerieActive")})
    # un même personnel peut apparaître une fois par fonction
    vus, uniques = set(), []
    for r in res:
        k = (r["type"], r.get("id"), r.get("id_eleve"), r.get("id_responsable"))
        if k not in vus:
            vus.add(k); uniques.append(r)
    return uniques


async def resoudre_destinataires(client, demandes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """[{type:'famille', id_eleve, responsable:'1'|'2'|'tous', champ:'to'|'cc'|'cci'},
        {type:'personnel', id, champ}] → contacts EcoleDirecte complets prêts à envoyer."""
    cache: dict[str, list] = {}
    out: list[dict[str, Any]] = []
    for d in demandes:
        t = d.get("type")
        if t not in TYPES_CONTACTS:
            raise MessagerieError(f"Destinataire de type inconnu : {d!r} (famille ou personnel).")
        champ = d.get("champ", "to")
        if champ not in ("to", "cc", "cci"):
            raise MessagerieError("champ doit être 'to', 'cc' ou 'cci'.")
        if t not in cache:
            cache[t] = await _contacts(client, t)
        if t == "famille":
            resp = str(d.get("responsable", "tous"))
            trouves = [c for c in cache[t] if int(c.get("id", -1)) == int(d["id_eleve"])
                       and (resp == "tous" or str((c.get("responsable") or {}).get("typeResp")) == resp)]
            for c in trouves:
                out.append({**c, "type": TYPE_FAMILLE_RESPONSABLE, "to_cc_cci": champ})
        else:
            trouves = [c for c in cache[t] if int(c.get("id", -1)) == int(d["id"])][:1]
            out.extend({**c, "to_cc_cci": champ} for c in trouves)
        if not trouves:
            raise MessagerieError(f"Destinataire introuvable dans l'annuaire de la messagerie : {d!r}.")
    inactifs = [libelle_contact(c) for c in out if c.get("messagerieActive") is False]
    if inactifs:
        raise MessagerieError("Messagerie inactive pour : " + " ; ".join(inactifs))
    return out


# ---------------------------------------------------------------- brouillon / envoi
async def preparer_message(client, sujet: str, texte: str, destinataires: list[dict[str, Any]],
                           mode: str = "brouillon", confirm: bool = False) -> dict[str, Any]:
    if mode not in ("brouillon", "envoi"):
        raise MessagerieError("mode doit être 'brouillon' ou 'envoi'.")
    if not sujet.strip() or not texte.strip():
        raise MessagerieError("Objet et texte obligatoires.")
    dest = await resoudre_destinataires(client, destinataires)
    if len(dest) > _max_dest():
        raise MessagerieError(f"{len(dest)} destinataires : plafond de {_max_dest()} par message "
                              "(ED_PERSO_MESSAGERIE_MAX_DEST).")
    info = await client.session_info()
    apercu = {"mode": mode, "expediteur": f"{info.get('prenom')} {info.get('nom')} (compte {info.get('id')})",
              "objet": sujet, "texte": texte,
              "destinataires": [f"[{c['to_cc_cci']}] {libelle_contact(c)}" for c in dest]}
    if not confirm:
        return {**apercu, "ecrit": False, "message": "Simulation : rien n'a été écrit. Rappeler avec confirm=True "
                "après accord explicite de l'utilisateur."}
    if not _actif():
        raise MessagerieError("Écriture désactivée (ED_PERSO_MESSAGERIE_ACTIF≠1).")
    msg = construire_message(sujet, texte, dest, info.get("typeCompte") or "A", int(info["id"]), mode == "brouillon")
    r = await client.poster_message(msg)
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    new = not JOURNAL.exists()
    with JOURNAL.open("a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(["horodatage", "mode", "id_message", "objet", "nb_destinataires", "destinataires"])
        w.writerow([datetime.now().isoformat(timespec="seconds"), mode, (r or {}).get("id"), sujet, len(dest),
                    " ; ".join(apercu["destinataires"])])
    return {**apercu, "ecrit": True, "id_message": (r or {}).get("id"),
            "message": "Brouillon enregistré dans les brouillons EcoleDirecte." if mode == "brouillon"
            else "Message envoyé."}

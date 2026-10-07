"""Documents publiés dans l'espace « Documents » des familles — LECTURE seule.

L'espace Documents d'une famille (site www.ecoledirecte.com, rubrique
Documents) regroupe ce que l'établissement y publie : factures, documents
administratifs (circulaires, invitations, projet éducatif…, souvent diffusés
à une ou plusieurs classes), documents de notes / vie scolaire / inscription,
et les « pièces à verser ». Contrairement à un message de la messagerie, une
publication dans cet espace ne déclenche AUCUNE notification aux familles.

L'API admin n'expose pas la liste des documents diffusés. On la reconstitue en
se plaçant dans l'espace d'une famille, exactement comme `etat_pieces` :

  1. supervision admin → session famille (cf. depot_pieces.ouvrir_supervision) ;
  2. POST v3/familledocuments.awp?verbe=get&archive=<année|vide>
     → data = {factures: [...], administratifs: [...], notes: [...],
               viescolaire: [...], inscriptions: [...], entreprises: [...],
               listesPiecesAVerser: {...}}   (seules les rubriques non vides
               sont présentes) ; chaque document : {id, libelle, date, type,
               signatureDemandee, etatSignatures, signature, idEleve?}.

Les documents sont publiés COMPTE PAR COMPTE (constat du 06/10/2026 : un
mandat SEPA présent chez un seul des deux parents, et le même document
administratif sous deux identifiants différents). Sauf compte précisé, on lit
donc tous les comptes rattachés à l'élève et on fusionne.

Aucun document n'est téléchargé ni ouvert : seuls les intitulés et dates sont
lus. Pour une vue « école », on interroge UNE famille par classe et on regroupe
les documents par (intitulé, date) : les factures et les documents propres à
une famille (mandat SEPA, document nominatif) sont écartés de la vue école.
"""
from __future__ import annotations

import asyncio
import os
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

from mcp.server.mcpserver.exceptions import ToolError

from . import depot_pieces as dp
from .auth import encode_form_data

RUBRIQUES = {
    "administratifs": "Administratifs",
    "factures": "Factures",
    "notes": "Notes",
    "viescolaire": "Vie scolaire",
    "inscriptions": "Inscription / Ré-inscription",
    "entreprises": "Entreprise",
}


def _norm(s: Any) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return " ".join(s.lower().split())


def resume_document(doc: dict[str, Any], rubrique: str) -> dict[str, Any]:
    """Champs utiles d'un document, sans contenu ni lien de téléchargement."""
    out = {
        "id": doc.get("id"),
        "rubrique": RUBRIQUES.get(rubrique, rubrique),
        "libelle": (doc.get("libelle") or "").strip(),
        "date": doc.get("date"),
        "type": doc.get("type") or "",
    }
    if doc.get("signatureDemandee"):
        out["signature_demandee"] = True
        etats = doc.get("etatSignatures") or []
        if etats:
            out["etat_signatures"] = etats
    if doc.get("idEleve"):
        out["id_eleve"] = doc.get("idEleve")
    return out


def documents_de_reponse(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Aplati les rubriques de la réponse familledocuments (hors pièces à verser)."""
    docs = []
    for rubrique, liste in (data or {}).items():
        if rubrique == "listesPiecesAVerser" or not isinstance(liste, list):
            continue
        for d in liste:
            if isinstance(d, dict):
                docs.append(resume_document(d, rubrique))
    docs.sort(key=lambda d: (d.get("date") or ""), reverse=True)
    return docs


def est_propre_a_la_famille(doc: dict[str, Any]) -> bool:
    """Facture, document nominatif (idEleve) ou à signer (mandat SEPA…)."""
    return (doc["rubrique"] == RUBRIQUES["factures"] or bool(doc.get("id_eleve"))
            or bool(doc.get("signature_demandee")))


async def _lire_documents_famille(admin_client, compte: dict[str, Any], archive: str = "") -> list[dict[str, Any]]:
    fam = await dp.ouvrir_supervision(admin_client, compte)
    try:
        url = (f"{dp.WWW_API_BASE}familledocuments.awp?archive={archive}"
               f"&verbe=get&v={dp.WWW_API_VERSION}")
        resp = await fam.http.post(url, content=encode_form_data({}),
                                   headers={**fam._headers(),
                                            "Content-Type": "application/x-www-form-urlencoded"})
        try:
            payload = resp.json()
        except ValueError as exc:
            raise ToolError(f"familledocuments : réponse non JSON (HTTP {resp.status_code})") from exc
        if payload.get("code") != 200:
            raise ToolError(f"familledocuments : code {payload.get('code')} — {payload.get('message', '')}")
        return documents_de_reponse(payload.get("data") or {})
    finally:
        await fam.http.aclose()


def _libelle_compte(compte: dict[str, Any]) -> str:
    return f"{compte.get('civilite', '')} {compte['nom']} {compte['prenom']} (id {compte['id']})".strip()


def fusionner_comptes(par_compte: list[tuple[dict[str, Any], list[dict[str, Any]]]]) -> list[dict[str, Any]]:
    """[(compte, docs)] → un document par (rubrique, intitulé, date, type), avec
    les comptes qui le voient et l'identifiant du document dans chacun (il
    diffère d'un compte à l'autre). `seulement_pour` si tous ne le voient pas."""
    tous = [_libelle_compte(c) for c, _ in par_compte]
    fusion: dict[tuple, dict[str, Any]] = {}
    for compte, docs in par_compte:
        nom = _libelle_compte(compte)
        for d in docs:
            cle = (d["rubrique"], _norm(d["libelle"]), d.get("date") or "", d.get("type") or "")
            e = fusion.get(cle)
            if e is None:
                e = fusion[cle] = {**d, "ids_par_compte": {}, "visible_pour": []}
            e["ids_par_compte"][str(compte["id"])] = d.get("id")
            if nom not in e["visible_pour"]:
                e["visible_pour"].append(nom)
    out = []
    for e in fusion.values():
        if len(tous) > 1 and len(e["visible_pour"]) < len(tous):
            e["seulement_pour"] = e["visible_pour"]
        out.append(e)
    out.sort(key=lambda d: (d.get("date") or ""), reverse=True)
    return out


async def documents_famille(admin_client, id_eleve: int, compte_id: int | None = None,
                            archive: str = "") -> dict[str, Any]:
    res = await dp.resoudre_eleve_famille(admin_client, id_eleve)
    comptes = [dp.choisir_compte(res, compte_id)] if compte_id is not None else res["comptes"]
    par_compte = []
    for i, compte in enumerate(comptes):
        if i:
            await asyncio.sleep(0.3)
        par_compte.append((compte, await _lire_documents_famille(admin_client, compte, archive)))
    docs = fusionner_comptes(par_compte)
    eleve = res["eleve"]
    out = {
        "eleve": f"{eleve.get('nom', '')} {eleve.get('prenom', '')} ({eleve.get('libelleClasse') or eleve.get('idClasse')})".strip(),
        "comptes_lus": [f"{_libelle_compte(c)}, {c.get('type')}" for c in comptes],
        "archive": archive or "année en cours",
        "nb_documents": len(docs),
        "documents": docs,
        "note": ("Documents visibles dans l'espace Documents (sans notification à la publication). "
                 "Publiés compte par compte : `visible_pour` / `seulement_pour` indiquent quel parent "
                 "les voit ; pour télécharger, passer l'id du document dans le compte voulu "
                 "(`ids_par_compte`). Les pièces à verser sont dans ed_admin_pieces_etat."),
    }
    if any(d.get("seulement_pour") for d in docs):
        out["attention"] = "Certains documents ne sont visibles que d'un des parents (voir `seulement_pour`)."
    return out


def regrouper_par_classe(par_classe: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """{classe: [docs]} → documents communs, regroupés par (libellé, date)."""
    toutes = sorted(par_classe)
    vus: dict[tuple[str, str, str], dict[str, Any]] = {}
    for classe, docs in par_classe.items():
        for d in docs:
            if est_propre_a_la_famille(d):
                continue
            cle = (d["rubrique"], _norm(d["libelle"]), d.get("date") or "")
            e = vus.setdefault(cle, {"rubrique": d["rubrique"], "libelle": d["libelle"],
                                     "date": d.get("date"), "classes": []})
            if classe not in e["classes"]:
                e["classes"].append(classe)
    docs = []
    for e in vus.values():
        e["classes"].sort()
        e["portee"] = "toutes les classes interrogées" if e["classes"] == toutes else "classes ciblées"
        docs.append(e)
    docs.sort(key=lambda e: (e.get("date") or ""), reverse=True)
    return {"classes_interrogees": toutes, "documents": docs}


async def documents_ecole(admin_client, classe: str | None = None, archive: str = "") -> dict[str, Any]:
    eleves = await admin_client.list_utilisateurs("eleves", "")
    familles = await admin_client.list_utilisateurs("familles", "")
    cible = _norm(classe) if classe else None
    # Une famille voit aussi les documents de ses AUTRES enfants : on choisit donc,
    # pour chaque classe, une famille dont tous les enfants sont dans cette classe
    # (à défaut, la première trouvée, signalée dans `representant_avec_fratrie`).
    representants: dict[str, list[dict[str, Any]]] = {}
    avec_fratrie: set[str] = set()
    for e in sorted(eleves, key=lambda x: int(x.get("id", 0))):
        lib = (e.get("libelleClasse") or "").strip()
        if not lib or str(e.get("idClasse")) in ("0", ""):
            continue
        if cible and cible not in (_norm(lib), _norm(lib).replace(" ", ""), str(e.get("idClasse"))):
            continue
        if lib in representants and lib not in avec_fratrie:
            continue
        try:
            res = await dp.resoudre_eleve_famille(admin_client, e["id"], eleves=eleves, familles=familles)
        except ToolError:
            continue
        compte = res["compte"]
        classes_enfants = {str(c.get("idClasse")) for c in compte.get("enfants") or []}
        seule_classe = classes_enfants <= {str(e.get("idClasse"))}
        if lib not in representants or seule_classe:
            representants[lib] = res.get("comptes") or [compte]
            if seule_classe:
                avec_fratrie.discard(lib)
            else:
                avec_fratrie.add(lib)
    if not representants:
        raise ToolError(f"Aucune classe trouvée{f' pour « {classe} »' if classe else ''} (voir ed_admin_classes_list).")

    par_classe: dict[str, list[dict[str, Any]]] = {}
    erreurs = {}
    for lib, comptes in representants.items():
        # tous les comptes de la famille (les documents sont publiés compte par compte)
        docs: list[dict[str, Any]] = []
        for compte in comptes:
            try:
                docs.extend(await _lire_documents_famille(admin_client, compte, archive))
            except Exception as exc:  # noqa: BLE001 — une classe en erreur ne bloque pas les autres
                erreurs[lib] = str(exc)
            await asyncio.sleep(0.3)
        if docs or lib not in erreurs:
            par_classe[lib] = docs
    out = regrouper_par_classe(par_classe)
    out["archive"] = archive or "année en cours"
    if erreurs:
        out["erreurs"] = erreurs
    if avec_fratrie:
        out["representant_avec_fratrie"] = sorted(avec_fratrie)
    out["note"] = ("Reconstitué en lisant l'espace Documents d'UNE famille par classe, tous ses comptes "
                   "(supervision en lecture seule) : un document diffusé à quelques familles seulement "
                   "peut ne pas apparaître. Factures, documents nominatifs et documents à signer (mandat SEPA…) "
                   "sont écartés. Une publication dans Documents n'envoie aucune notification aux "
                   "familles ; l'auteur n'est pas exposé par l'API.")
    return out


# ----------------------------------------------------------------------
# Téléchargement d'un document publié (LECTURE)
# ----------------------------------------------------------------------
#   POST v3/telechargement.awp?verbe=get&fichierId=<id>&leTypeDeFichier=<type du document>
#   corps data={"forceDownload":0}  (même appel que le site famille, loadBlobFile)
# Le type de fichier est le champ `type` du document dans familledocuments
# ("Doc", "Facture", ou vide). Vérifié en réel le 06/10/2026.

MOTIFS_BANCAIRES = re.compile(r"sepa|rib\b|iban|mandat|pr[ée]l[èe]vement", re.I)
MAX_BYTES = 20 * 1024 * 1024


def dossier_telechargements() -> Path:
    d = os.environ.get("ED_ADMIN_DOCUMENTS_DIR")
    if not d:
        raise ToolError("Téléchargement désactivé : définir ED_ADMIN_DOCUMENTS_DIR (dossier local où "
                        "enregistrer les documents).")
    p = Path(d).expanduser()
    p.mkdir(parents=True, exist_ok=True)
    return p


def nom_fichier(doc: dict[str, Any], dossier: Path) -> Path:
    base = unicodedata.normalize("NFKD", doc.get("libelle") or "document").encode("ascii", "ignore").decode()
    base = "_".join(re.sub(r"[^A-Za-z0-9._ -]+", "", base).split())[:80] or "document"
    p = dossier / f"{doc.get('date') or 'sans-date'}_{base}_{doc.get('id')}.pdf"
    n = 2
    while p.exists():
        p = p.with_name(f"{p.stem.rsplit('__', 1)[0]}__{n}.pdf")
        n += 1
    return p


def refus_document(doc: dict[str, Any]) -> str | None:
    if MOTIFS_BANCAIRES.search(doc.get("libelle") or ""):
        return "document bancaire (mandat SEPA, RIB…) : jamais téléchargé par le connecteur"
    return None


async def telecharger_document(admin_client, id_eleve: int, document_id: int,
                               compte_id: int | None = None, archive: str = "") -> dict[str, Any]:
    dossier = dossier_telechargements()
    res = await dp.resoudre_eleve_famille(admin_client, id_eleve)
    comptes = [dp.choisir_compte(res, compte_id)] if compte_id is not None else res["comptes"]
    derniere: ToolError | None = None
    for compte in comptes:
        try:
            return await _telecharger_dans_compte(admin_client, compte, document_id, archive, dossier)
        except DocumentAbsent as exc:  # l'id appartient peut-être à l'autre parent
            derniere = exc
    raise derniere or ToolError("Aucun compte famille.")


class DocumentAbsent(ToolError):
    """Document absent de l'espace du compte interrogé."""


async def _telecharger_dans_compte(admin_client, compte: dict[str, Any], document_id: int,
                                   archive: str, dossier: Path) -> dict[str, Any]:
    fam = await dp.ouvrir_supervision(admin_client, compte)
    try:
        url = (f"{dp.WWW_API_BASE}familledocuments.awp?archive={archive}"
               f"&verbe=get&v={dp.WWW_API_VERSION}")
        resp = await fam.http.post(url, content=encode_form_data({}),
                                   headers={**fam._headers(),
                                            "Content-Type": "application/x-www-form-urlencoded"})
        payload = resp.json()
        fam._take_token(resp, payload)
        brut = {}
        for rubrique, liste in (payload.get("data") or {}).items():
            if rubrique == "listesPiecesAVerser" or not isinstance(liste, list):
                continue
            for d in liste:
                if isinstance(d, dict) and int(d.get("id", -1)) == int(document_id):
                    brut = {"rubrique": rubrique, **d}
        if not brut:
            raise DocumentAbsent(f"Document {document_id} absent de l'espace Documents de cette famille "
                                 "(voir ed_admin_documents_famille, champ ids_par_compte).")
        doc = resume_document(brut, brut["rubrique"])
        motif = refus_document(doc)
        if motif:
            raise ToolError(f"Refusé : {motif}.")
        url = (f"{dp.WWW_API_BASE}telechargement.awp?verbe=get&fichierId={int(document_id)}"
               f"&leTypeDeFichier={brut.get('type') or ''}&v={dp.WWW_API_VERSION}")
        r = await fam.http.post(url, content=encode_form_data({"forceDownload": 0}),
                                headers={**fam._headers(),
                                         "Content-Type": "application/x-www-form-urlencoded"},
                                timeout=120)
    finally:
        await fam.http.aclose()
    contenu = r.content
    if r.status_code != 200 or not contenu.startswith(b"%PDF"):
        raise ToolError(f"Téléchargement refusé ou format inattendu (HTTP {r.status_code}, "
                        f"{r.headers.get('content-type')}).")
    if len(contenu) > MAX_BYTES:
        raise ToolError("Document trop volumineux (> 20 Mo).")
    chemin = nom_fichier(doc, dossier)
    fd = os.open(chemin, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(contenu)
    return {"document": {k: doc[k] for k in ("id", "rubrique", "libelle", "date")},
            "compte": _libelle_compte(compte),
            "fichier": str(chemin), "taille_octets": len(contenu),
            "telecharge_le": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "note": "Copie locale (droits 600, jamais écrasée). Lecture seule côté EcoleDirecte."}

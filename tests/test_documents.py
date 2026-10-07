"""Documents de l'espace famille (documents.py) — sans réseau, données fictives."""
from __future__ import annotations

from ecoledirecte_admin_mcp import documents as docs_mod
from ecoledirecte_admin_mcp.documents import (
    documents_de_reponse, est_propre_a_la_famille, regrouper_par_classe,
)

REPONSE = {
    "factures": [{"id": 1, "libelle": "Facture 9 du 15 septembre", "date": "2026-09-29", "type": "Facture",
                  "signatureDemandee": False}],
    "administratifs": [
        {"id": 2, "libelle": "Circulaire sortie", "date": "2026-10-01", "type": "Doc", "signatureDemandee": False},
        {"id": 3, "libelle": "Mandat SEPA", "date": "2026-09-24", "type": "", "signatureDemandee": True,
         "etatSignatures": [{"etat": "attente"}]},
    ],
    "listesPiecesAVerser": {"listesPieces": [{"id": 9}]},
}


def test_aplatit_les_rubriques_sans_pieces_a_verser():
    d = documents_de_reponse(REPONSE)
    assert [x["libelle"] for x in d] == ["Circulaire sortie", "Facture 9 du 15 septembre", "Mandat SEPA"]
    assert {x["rubrique"] for x in d} == {"Administratifs", "Factures"}
    assert "url" not in str(d) and "listesPieces" not in str(d)


def test_documents_propres_a_la_famille():
    d = {x["libelle"]: x for x in documents_de_reponse(REPONSE)}
    assert est_propre_a_la_famille(d["Facture 9 du 15 septembre"])
    assert est_propre_a_la_famille(d["Mandat SEPA"])
    assert not est_propre_a_la_famille(d["Circulaire sortie"])


def test_regroupement_portee():
    commun = {"rubrique": "Administratifs", "libelle": "Projet éducatif", "date": "2026-09-28"}
    cible = {"rubrique": "Administratifs", "libelle": "Invitation réunion CM2", "date": "2026-10-01"}
    facture = {"rubrique": "Factures", "libelle": "Facture 1", "date": "2026-09-29"}
    r = regrouper_par_classe({"CM2 A": [commun, cible, facture], "CM2 B": [commun, dict(cible)],
                              "CP A": [dict(commun)]})
    par_lib = {d["libelle"]: d for d in r["documents"]}
    assert par_lib["Projet éducatif"]["portee"] == "toutes les classes interrogées"
    assert par_lib["Invitation réunion CM2"]["classes"] == ["CM2 A", "CM2 B"]
    assert par_lib["Invitation réunion CM2"]["portee"] == "classes ciblées"
    assert "Facture 1" not in par_lib


async def test_ecole_prefere_une_famille_sans_fratrie(monkeypatch):
    eleves = [
        {"id": 1, "nom": "A", "prenom": "Un", "idClasse": 7, "libelleClasse": "CM2 A"},
        {"id": 2, "nom": "B", "prenom": "Deux", "idClasse": 7, "libelleClasse": "CM2 A"},
    ]
    familles = {1: {"id": 11, "nom": "A", "prenom": "P", "type": "responsable",
                    "enfants": [{"idClasse": 7}, {"idClasse": 3}]},
                2: {"id": 22, "nom": "B", "prenom": "P", "type": "responsable", "enfants": [{"idClasse": 7}]}}

    class FakeClient:
        async def list_utilisateurs(self, t, f=""):
            return eleves if t == "eleves" else []

    async def resoudre(client, id_eleve, eleves=None, familles_=None, **k):
        return {"eleve": {}, "comptes": [familles[id_eleve]], "compte": familles[id_eleve]}

    lus = []

    async def lire(client, compte, archive=""):
        lus.append(compte["id"])
        return [{"rubrique": "Administratifs", "libelle": "Doc", "date": "2026-10-01", "type": "Doc"}]

    monkeypatch.setattr(docs_mod.dp, "resoudre_eleve_famille", resoudre)
    monkeypatch.setattr(docs_mod, "_lire_documents_famille", lire)
    monkeypatch.setattr(docs_mod.asyncio, "sleep", lambda s: _noop())
    r = await docs_mod.documents_ecole(FakeClient())
    assert lus == [22]
    assert "representant_avec_fratrie" not in r
    assert r["documents"][0]["classes"] == ["CM2 A"]


async def _noop():
    return None


# --- téléchargement ---------------------------------------------------------
import pytest
from mcp.server.mcpserver.exceptions import ToolError


def test_refus_documents_bancaires():
    base = {"rubrique": "Administratifs", "date": "2026-09-24", "id": 4}
    assert docs_mod.refus_document({**base, "libelle": "Mandat SEPA"})
    assert docs_mod.refus_document({**base, "libelle": "RIB école"})
    assert docs_mod.refus_document({**base, "libelle": "Invitation réunion"}) is None
    assert docs_mod.refus_document({**base, "rubrique": "Factures", "libelle": "Facture 7 du 15 septembre"}) is None


def test_nom_fichier_jamais_ecrase(tmp_path):
    doc = {"id": 9, "libelle": "Circulaire : sortie / forêt", "date": "2026-10-01"}
    p1 = docs_mod.nom_fichier(doc, tmp_path)
    assert p1.name == "2026-10-01_Circulaire_sortie_foret_9.pdf"
    p1.write_bytes(b"%PDF")
    p2 = docs_mod.nom_fichier(doc, tmp_path)
    assert p2 != p1 and p2.name.endswith("__2.pdf")


def test_telechargement_desactive_sans_dossier(monkeypatch):
    monkeypatch.delenv("ED_ADMIN_DOCUMENTS_DIR", raising=False)
    with pytest.raises(ToolError):
        docs_mod.dossier_telechargements()


# --- documents publiés compte par compte (06/10/2026) -------------------------
P1 = {"id": 951, "civilite": "Mme", "nom": "X", "prenom": "Mère", "type": "responsable"}
P2 = {"id": 952, "civilite": "M.", "nom": "X", "prenom": "Père", "type": "responsable"}


def test_fusion_par_compte():
    fact = {"rubrique": "Factures", "libelle": "Facture 1", "date": "2026-09-29", "type": "Facture"}
    projet = {"rubrique": "Administratifs", "libelle": "Projet", "date": "2026-09-28", "type": "Doc"}
    sepa = {"rubrique": "Administratifs", "libelle": "Mandat SEPA", "date": "2026-09-24", "type": "",
            "signature_demandee": True}
    docs = docs_mod.fusionner_comptes([
        (P1, [{**fact, "id": 801}, {**projet, "id": 338}]),
        (P2, [{**fact, "id": 801}, {**projet, "id": 339}, {**sepa, "id": 12}]),
    ])
    par = {d["libelle"]: d for d in docs}
    assert len(docs) == 3
    assert par["Projet"]["ids_par_compte"] == {"951": 338, "952": 339}
    assert "seulement_pour" not in par["Projet"]
    assert par["Mandat SEPA"]["seulement_pour"] == ["M. X Père (id 952)"]


def test_fusion_un_seul_compte_sans_seulement_pour():
    d = {"rubrique": "Factures", "libelle": "F", "date": "2026-09-29", "type": "Facture", "id": 1}
    docs = docs_mod.fusionner_comptes([(P1, [d])])
    assert "seulement_pour" not in docs[0]


async def test_documents_famille_lit_tous_les_comptes(monkeypatch):
    async def resoudre(client, id_eleve, **k):
        return {"eleve": {"nom": "X", "prenom": "Enfant", "libelleClasse": "PS"},
                "comptes": [P1, P2], "compte": P1}

    lus = []

    async def lire(client, compte, archive=""):
        lus.append(compte["id"])
        return [{"rubrique": "Factures", "libelle": "F", "date": "2026-09-29", "type": "Facture", "id": 1}]

    monkeypatch.setattr(docs_mod.dp, "resoudre_eleve_famille", resoudre)
    monkeypatch.setattr(docs_mod, "_lire_documents_famille", lire)
    monkeypatch.setattr(docs_mod.asyncio, "sleep", lambda s: _noop())
    r = await docs_mod.documents_famille(object(), 1)
    assert lus == [951, 952] and r["nb_documents"] == 1 and len(r["comptes_lus"]) == 2
    lus.clear()
    await docs_mod.documents_famille(object(), 1, compte_id=952)
    assert lus == [952]


async def test_telechargement_cherche_dans_l_autre_compte(monkeypatch, tmp_path):
    monkeypatch.setenv("ED_ADMIN_DOCUMENTS_DIR", str(tmp_path))

    async def resoudre(client, id_eleve, **k):
        return {"eleve": {}, "comptes": [P1, P2], "compte": P1}

    essais = []

    async def dans_compte(client, compte, document_id, archive, dossier):
        essais.append(compte["id"])
        if compte["id"] == 951:
            raise docs_mod.DocumentAbsent("absent")
        return {"compte": compte["id"]}

    monkeypatch.setattr(docs_mod.dp, "resoudre_eleve_famille", resoudre)
    monkeypatch.setattr(docs_mod, "_telecharger_dans_compte", dans_compte)
    r = await docs_mod.telecharger_document(object(), 1, 339)
    assert essais == [951, 952] and r["compte"] == 952

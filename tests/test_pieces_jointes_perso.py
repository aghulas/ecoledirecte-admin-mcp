"""Pièces jointes de la messagerie perso : téléchargement et garde-fous — sans réseau."""
from __future__ import annotations

import stat

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from ecoledirecte_perso_mcp import pieces_jointes as pj

PDF = b"%PDF-1.4\n%fake\n"
MSGS = [{"id": 92, "subject": "Certificats", "date": "2026-10-10", "read": False,
         "files": [{"id": 14, "libelle": "certificat 1.pdf", "type": "PIECE_JOINTE"},
                   {"id": 15, "libelle": "certificat 2.pdf", "type": "PIECE_JOINTE"}]},
        {"id": 93, "subject": "Facture", "read": True,
         "files": [{"id": 16, "libelle": "Mandat SEPA.pdf", "type": "PIECE_JOINTE"}]},
        {"id": 94, "subject": "Sans PJ", "files": []}]


class FakeClient:
    def __init__(self, contenu=PDF):
        self.contenu, self.telecharges = contenu, []

    async def list_messages(self, boite="received", page=0, items=100, **k):
        return {"messages": {boite: MSGS if page == 0 else []}}

    async def telecharger_piece_jointe_brut(self, id_fichier):
        self.telecharges.append(id_fichier)
        return self.contenu


@pytest.fixture
def dossier(tmp_path, monkeypatch):
    monkeypatch.setenv("ED_PERSO_PJ_DIR", str(tmp_path))
    return tmp_path


async def test_refus_sans_dossier(monkeypatch):
    monkeypatch.delenv("ED_PERSO_PJ_DIR", raising=False)
    with pytest.raises(ToolError, match="ED_PERSO_PJ_DIR"):
        await pj.telecharger_piece_jointe(FakeClient(), 92)


async def test_toutes_les_pj_du_message(dossier):
    c = FakeClient()
    r = await pj.telecharger_piece_jointe(c, 92)
    assert c.telecharges == [14, 15]
    chemins = [p["fichier"] for p in r["pieces_jointes"]]
    assert all(p.endswith(".pdf") for p in chemins)
    for p in chemins:
        assert stat.S_IMODE((dossier / p.split("/")[-1]).stat().st_mode) == 0o600
    assert "inchangé" in r["note"]


async def test_fichier_hors_du_message_refuse(dossier):
    c = FakeClient()
    with pytest.raises(ToolError, match="n'appartient pas"):
        await pj.telecharger_piece_jointe(c, 92, id_fichier=16)
    assert c.telecharges == []


async def test_message_introuvable_ou_sans_pj(dossier):
    with pytest.raises(ToolError, match="introuvable"):
        await pj.telecharger_piece_jointe(FakeClient(), 999)
    with pytest.raises(ToolError, match="pas de pièce jointe"):
        await pj.telecharger_piece_jointe(FakeClient(), 94)


async def test_document_bancaire_jamais_telecharge(dossier):
    c = FakeClient()
    r = await pj.telecharger_piece_jointe(c, 93)
    assert c.telecharges == [] and "bancaire" in r["pieces_jointes"][0]["refus"]


async def test_format_inconnu_et_taille(dossier, monkeypatch):
    r = await pj.telecharger_piece_jointe(FakeClient(b"MZ\x90\x00exe"), 92, id_fichier=14)
    assert "format" in r["pieces_jointes"][0]["refus"]
    monkeypatch.setattr(pj, "MAX_BYTES", 4)
    r = await pj.telecharger_piece_jointe(FakeClient(), 92, id_fichier=14)
    assert "volumineux" in r["pieces_jointes"][0]["refus"]
    assert not list(dossier.iterdir())


async def test_jamais_d_ecrasement(dossier):
    r1 = await pj.telecharger_piece_jointe(FakeClient(), 92, id_fichier=14)
    r2 = await pj.telecharger_piece_jointe(FakeClient(), 92, id_fichier=14)
    a, b = r1["pieces_jointes"][0]["fichier"], r2["pieces_jointes"][0]["fichier"]
    assert a != b and b.endswith("_2.pdf")


def test_zip_seulement_si_office():
    assert pj._extension(b"PK\x03\x04...", "fiche.docx") == ".docx"
    assert pj._extension(b"PK\x03\x04...", "archive.zip") is None

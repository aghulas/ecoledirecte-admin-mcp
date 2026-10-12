"""Téléchargement d'une pièce déposée par une famille (documents.telecharger_piece) — sans réseau."""
from __future__ import annotations

import os
from urllib.parse import parse_qs, urlparse, unquote_plus

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from ecoledirecte_admin_mcp import documents as docs_mod

P1 = {"id": 951, "nom": "TEST", "prenom": "Pere", "type": "responsable"}
P2 = {"id": 952, "nom": "TEST", "prenom": "Mere", "type": "conjoint"}


def espace(televersements, liste="Justificatifs", piece="Justificatif APEL"):
    return {"listesPieces": [{"id": 5, "libelle": liste, "type": "F", "personnes": [951, 952, 953]}],
            "pieces": [{"id": 12, "libelle": piece, "idListePiece": 5}],
            "personnes": [{"id": 951, "prenom": "Pere", "nom": "TEST"}],
            "televersements": televersements}


class Rep:
    def __init__(self, contenu, status=200, ctype="application/force-download"):
        self.content, self.status_code, self.headers = contenu, status, {"content-type": ctype}


class FakeFam:
    def __init__(self, lp, contenu=b"%PDF-1.4 test"):
        self.lp, self.contenu, self.appels = lp, contenu, []
        outer = self

        class Http:
            async def post(self, url, content=None, headers=None, timeout=None):
                outer.appels.append((url, content))
                return Rep(outer.contenu)

            async def aclose(self):
                pass

        self.http = Http()

    async def documents(self):
        return self.lp

    def _headers(self):
        return {}


def installer(monkeypatch, tmp_path, fams):
    monkeypatch.setenv("ED_ADMIN_DOCUMENTS_DIR", str(tmp_path))

    async def resoudre(client, id_eleve, **k):
        return {"eleve": {}, "comptes": [P1, P2], "compte": P1}

    async def ouvrir(client, compte):
        return fams[compte["id"]]

    monkeypatch.setattr(docs_mod.dp, "resoudre_eleve_famille", resoudre)
    monkeypatch.setattr(docs_mod.dp, "ouvrir_supervision", ouvrir)


TV = {"idListePiece": 5, "idPiece": 12, "idPersonne": 951, "date": "2026-10-10",
      "isLock": True, "libelle": "AbCdEf123"}


async def test_appel_et_fichier(monkeypatch, tmp_path):
    fam = FakeFam(espace([TV]))
    installer(monkeypatch, tmp_path, {951: fam, 952: FakeFam(espace([]))})
    r = await docs_mod.telecharger_piece(object(), 1, 12)
    url, corps = fam.appels[0]
    q = parse_qs(urlparse(url).query)
    assert q["fichierId"] == ["AbCdEf123"] and q["leTypeDeFichier"] == ["LISTE_PIECE"]
    data = unquote_plus(corps)
    for cle in ('"idListePiece": 5', '"idPersonne": 951', '"idPiece": 12', '"forceDownload": 0'):
        assert cle.replace(" ", "") in data.replace(" ", "")
    assert r["format"] == "pdf" and r["verrouillee"] is True
    assert r["fichier"].startswith(str(tmp_path / "pieces")) and r["fichier"].endswith(".pdf")
    assert oct(os.stat(r["fichier"]).st_mode)[-3:] == "600"


async def test_cherche_dans_l_autre_compte_et_jpeg(monkeypatch, tmp_path):
    fam2 = FakeFam(espace([dict(TV, idPersonne=952)]), contenu=b"\xff\xd8\xff\xe0 jpeg")
    installer(monkeypatch, tmp_path, {951: FakeFam(espace([])), 952: fam2})
    r = await docs_mod.telecharger_piece(object(), 1, 12)
    assert r["format"] == "jpg" and r["fichier"].endswith(".jpg") and fam2.appels


async def test_refus_piece_bancaire(monkeypatch, tmp_path):
    fam = FakeFam(espace([TV], piece="RIB du payeur"))
    installer(monkeypatch, tmp_path, {951: fam, 952: FakeFam(espace([]))})
    with pytest.raises(ToolError, match="bancaire"):
        await docs_mod.telecharger_piece(object(), 1, 12)
    assert fam.appels == []


async def test_plusieurs_depots_demande_la_personne(monkeypatch, tmp_path):
    fam = FakeFam(espace([TV, dict(TV, idPersonne=953)]))
    installer(monkeypatch, tmp_path, {951: fam, 952: FakeFam(espace([]))})
    with pytest.raises(ToolError, match="id_personne"):
        await docs_mod.telecharger_piece(object(), 1, 12)
    r = await docs_mod.telecharger_piece(object(), 1, 12, id_personne=953)
    assert r["fichier"]


async def test_reponse_html_refusee(monkeypatch, tmp_path):
    fam = FakeFam(espace([TV]), contenu=b"<!doctype html>")
    installer(monkeypatch, tmp_path, {951: fam, 952: FakeFam(espace([]))})
    with pytest.raises(ToolError, match="format inattendu"):
        await docs_mod.telecharger_piece(object(), 1, 12)
    assert not list((tmp_path / "pieces").iterdir())


async def test_sans_depot(monkeypatch, tmp_path):
    installer(monkeypatch, tmp_path, {951: FakeFam(espace([])), 952: FakeFam(espace([]))})
    with pytest.raises(ToolError, match="Aucun dépôt"):
        await docs_mod.telecharger_piece(object(), 1, 12)


async def test_sans_dossier_refuse(monkeypatch):
    monkeypatch.delenv("ED_ADMIN_DOCUMENTS_DIR", raising=False)
    with pytest.raises(ToolError, match="ED_ADMIN_DOCUMENTS_DIR"):
        await docs_mod.telecharger_piece(object(), 1, 12)


async def test_ignore_depot_d_une_autre_famille(monkeypatch, tmp_path):
    # idPersonne absent de liste.personnes : dépôt d'une autre famille (ids qui se recouvrent)
    fam = FakeFam(espace([dict(TV, idPersonne=829)]))
    installer(monkeypatch, tmp_path, {951: fam, 952: FakeFam(espace([]))})
    with pytest.raises(ToolError, match="Aucun dépôt"):
        await docs_mod.telecharger_piece(object(), 1, 12)
    assert fam.appels == []

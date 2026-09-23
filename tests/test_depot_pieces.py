"""Garde-fous du dépôt de pièces (depot_pieces.py / depot_lot.py) — sans réseau."""
from __future__ import annotations

from pathlib import Path

import pytest

from ecoledirecte_admin_mcp import depot_pieces as dp
from ecoledirecte_admin_mcp.client import check_allowed, ForbiddenEndpointError
from ecoledirecte_admin_mcp.depot_lot import rapprocher

PDF = b"%PDF-1.4\n%fake\n"


@pytest.fixture
def racine(tmp_path, monkeypatch):
    r = tmp_path / "fiches"
    (r / "CM2B").mkdir(parents=True)
    monkeypatch.setenv("ED_ADMIN_DEPOT_RACINE", str(r))
    monkeypatch.delenv("ED_ADMIN_DEPOT_ACTIF", raising=False)
    monkeypatch.delenv("ED_ADMIN_DEPOT_LISTES", raising=False)
    return r


def _pdf(path: Path, content: bytes = PDF) -> Path:
    path.write_bytes(content)
    return path


# --- fichier -----------------------------------------------------------
def test_fichier_ok(racine):
    p = _pdf(racine / "CM2B" / "CM2B_DUPONT_Alice.pdf")
    assert dp.check_fichier(str(p)) == p.resolve()


def test_fichier_hors_racine_refuse(racine, tmp_path):
    p = _pdf(tmp_path / "ailleurs.pdf")
    with pytest.raises(dp.DepotError, match="hors du dossier"):
        dp.check_fichier(str(p))


def test_fichier_traversee_refusee(racine):
    _pdf(racine.parent / "secret.pdf")
    with pytest.raises(dp.DepotError, match="hors du dossier"):
        dp.check_fichier(str(racine / "CM2B" / ".." / ".." / "secret.pdf"))


def test_fichier_non_pdf_refuse(racine):
    p = racine / "CM2B" / "x.docx"
    p.write_bytes(b"PK")
    with pytest.raises(dp.DepotError, match="PDF"):
        dp.check_fichier(str(p))


def test_fichier_faux_pdf_refuse(racine):
    p = _pdf(racine / "CM2B" / "faux.pdf", b"<html>")
    with pytest.raises(dp.DepotError, match="en-tête"):
        dp.check_fichier(str(p))


def test_fichier_trop_gros_refuse(racine, monkeypatch):
    monkeypatch.setattr(dp, "MAX_BYTES", 10)
    p = _pdf(racine / "CM2B" / "gros.pdf", PDF * 10)
    with pytest.raises(dp.DepotError, match="Taille"):
        dp.check_fichier(str(p))


def test_sans_racine_refuse(monkeypatch, tmp_path):
    monkeypatch.delenv("ED_ADMIN_DEPOT_RACINE", raising=False)
    with pytest.raises(dp.DepotError, match="RACINE"):
        dp.check_fichier(str(_pdf(tmp_path / "a.pdf")))


# --- activation / listes -------------------------------------------------
def test_ecriture_desactivee_par_defaut(racine):
    assert dp._depot_actif() is False


def test_liste_non_autorisee_refusee():
    lp = {"listesPieces": [{"id": 9, "libelle": "Autre liste", "pieces": [1]}],
          "pieces": [{"id": 1, "idListePiece": 9}], "personnes": [{"id": 5}]}
    with pytest.raises(dp.DepotError, match="autorisée"):
        dp._trouver_liste(lp, 5)


def test_liste_autorisee_et_eleve_concerne(monkeypatch):
    lp = {"listesPieces": [{"id": 1, "libelle": "Fiches Rentrée", "pieces": [1], "personnes": [101, 102]}],
          "pieces": [{"id": 1, "idListePiece": 1, "libelle": "Fiche Rentrée"}], "personnes": []}
    liste, piece = dp._trouver_liste(lp, 102)
    assert liste["id"] == 1 and piece["id"] == 1
    with pytest.raises(dp.DepotError, match="pas concerné"):
        dp._trouver_liste(lp, 999)


def test_depot_existant_detecte():
    lp = {"televersements": [{"idListePiece": 1, "idPiece": 1, "idPersonne": 102}]}
    assert dp._depot_existant(lp, 1, 1, 102) is not None
    assert dp._depot_existant(lp, 1, 1, 101) is None


# --- supervision / fichiers restent bloqués côté client de lecture -------
@pytest.mark.parametrize("path", ["supervision", "televersement", "telechargement"])
def test_client_lecture_bloque_toujours(path):
    with pytest.raises(ForbiddenEndpointError):
        check_allowed(path, "get")


# --- rapprochement fichiers ↔ élèves ------------------------------------
def test_rapprochement(tmp_path):
    eleves = [{"id": 1, "nom": "DUPONT", "prenom": "Alice"},
              {"id": 2, "nom": "DE LA TOUR", "prenom": "Jeanne"},
              {"id": 3, "nom": "MARTIN", "prenom": "Léa"},
              {"id": 4, "nom": "MARTIN", "prenom": "Léon"}]
    fichiers = [tmp_path / n for n in (
        "CM2B_DUPONT_Alice.pdf", "CM2B_DE-LA-TOUR_Jeanne.pdf",
        "CM2B_MARTIN_Le.pdf", "CM2B_INCONNU_Paul.pdf", "CM2B_DUPONT_Alice-bis.pdf", "mauvais.pdf")]
    ok, ko = rapprocher(fichiers, eleves)
    assert {e["id"] for _, e in ok} == {1, 2}
    raisons = {f.name: r for f, r in ko}
    assert raisons["CM2B_MARTIN_Le.pdf"] == "plusieurs élèves possibles"
    assert raisons["CM2B_INCONNU_Paul.pdf"] == "aucun élève correspondant"
    assert raisons["CM2B_DUPONT_Alice-bis.pdf"].startswith("doublon")
    assert raisons["mauvais.pdf"] == "nom de fichier non conforme"


# --- simulation : aucune supervision ------------------------------------
async def test_simulation_ne_supervise_pas(racine, monkeypatch):
    p = _pdf(racine / "CM2B" / "CM2B_DUPONT_Alice.pdf")

    async def boom(*a, **k):
        raise AssertionError("la simulation ne doit jamais superviser")
    monkeypatch.setattr(dp, "ouvrir_supervision", boom)
    eleves = [{"id": 101, "nom": "DUPONT", "prenom": "Alice", "idClasse": 8, "libelleClasse": "CM2 B"}]
    familles = [{"id": 201, "nom": "DUPONT", "prenom": "Claire", "type": "responsable",
                 "enfants": [{"nom": "DUPONT", "prenom": "Alice", "idClasse": 8}]}]
    r = await dp.deposer_piece(object(), 101, str(p), confirm=False, eleves=eleves, familles=familles)
    assert r["depot_effectue"] is False and "201" in r["compte_famille"]


async def test_confirm_refuse_si_inactif(racine):
    p = _pdf(racine / "CM2B" / "CM2B_DUPONT_Alice.pdf")
    eleves = [{"id": 101, "nom": "DUPONT", "prenom": "Alice", "idClasse": 8}]
    familles = [{"id": 201, "nom": "DUPONT", "prenom": "E", "type": "responsable",
                 "enfants": [{"nom": "DUPONT", "prenom": "Alice", "idClasse": 8}]}]
    with pytest.raises(dp.DepotError, match="désactivée"):
        await dp.deposer_piece(object(), 101, str(p), confirm=True, eleves=eleves, familles=familles)

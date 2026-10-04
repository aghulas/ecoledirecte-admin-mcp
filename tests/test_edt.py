"""Emploi du temps enseignant (edt.py) : fonctions pures et garde-fous, hors ligne."""
from __future__ import annotations

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from ecoledirecte_admin_mcp import edt

PROFS = [
    {"id": 24, "nom": "LEFÈVRE", "prenom": "Anne"},
    {"id": 7, "nom": "BERNARD", "prenom": "Léa"},
    {"id": 8, "nom": "BERNARD", "prenom": "Paul"},
]


def test_choisir_par_nom_sans_accent():
    assert edt.choisir_enseignant(PROFS, "lefevre")["id"] == 24


def test_choisir_par_identifiant():
    assert edt.choisir_enseignant(PROFS, "8")["prenom"] == "Paul"


def test_homonymes_refuses():
    with pytest.raises(ToolError, match="Plusieurs"):
        edt.choisir_enseignant(PROFS, "bernard")
    assert edt.choisir_enseignant(PROFS, "bernard paul")["id"] == 8


def test_introuvable():
    with pytest.raises(ToolError, match="introuvable"):
        edt.choisir_enseignant(PROFS, "dupont")


def test_periode_par_defaut_et_limites():
    assert edt._periode("2026-10-05", None) == ("2026-10-05", "2026-10-11")
    with pytest.raises(ToolError):
        edt._periode("2026-10-05", "2026-12-31")
    with pytest.raises(ToolError):
        edt._periode("05/10/2026", None)
    with pytest.raises(ToolError):
        edt._periode("2026-10-05", "2026-10-01")


def test_resumer():
    cours = [
        {"start_date": "2026-10-05 10:00", "end_date": "2026-10-05 10:45", "codeMatiere": "0302",
         "matiere": "ANGLAIS", "classe": "CM2 B", "salle": "E21", "prof": "X", "typeCours": "COURS"},
        {"start_date": "2026-10-05 08:25", "end_date": "2026-10-05 08:50", "codeMatiere": "",
         "matiere": "", "classe": "PS", "salle": "", "prof": "Y", "isAnnule": True},
    ]
    r = edt.resumer(cours)
    assert r["nb_cours"] == 2 and r["nb_sans_matiere"] == 1
    assert r["cours"][0]["debut"] == "08:25" and r["cours"][0]["annule"]
    assert r["par_jour"] == {"2026-10-05": 2}


@pytest.mark.anyio
async def test_desactive_par_defaut(monkeypatch):
    monkeypatch.delenv("ED_ADMIN_EDT_ACTIF", raising=False)
    with pytest.raises(ToolError, match="ED_ADMIN_EDT_ACTIF"):
        await edt.emploi_du_temps_enseignant(object(), "lefevre", "2026-10-05")

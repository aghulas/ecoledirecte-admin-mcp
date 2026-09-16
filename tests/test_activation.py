"""Calcul d'activation des comptes par classe (pur, hors ligne)."""
from __future__ import annotations

import respx

from ecoledirecte_admin_mcp import server
from ecoledirecte_admin_mcp.activation import compute_activation
from ecoledirecte_admin_mcp.client import EcoleDirecteAdminClient

from ._helpers import API, fake_auth, ok

ELEVES = [
    {"id": 1, "nom": "DORLY", "prenom": "Siloé", "idClasse": 8, "libelleClasse": "CM2 B", "dejaConnecte": False},
    {"id": 2, "nom": "DORLY", "prenom": "Loéva", "idClasse": 5, "libelleClasse": "CM1 A", "dejaConnecte": True},
    {"id": 3, "nom": "MARIE", "prenom": "Camille", "idClasse": 8, "libelleClasse": "CM2 B", "dejaConnecte": False},
    {"id": 4, "nom": "SEUL", "prenom": "Paul", "idClasse": 8, "libelleClasse": "CM2 B", "dejaConnecte": False},
]
FAMILLES = [
    {"id": 10, "civilite": "Mme", "nom": "MARTINS", "prenom": "Gaëlle", "type": "responsable", "dejaConnecte": True,
     "enfants": [{"nom": "DORLY", "prenom": "Siloe", "idClasse": 8, "libelleClasse": "CM2 B"},
                 {"nom": "DORLY ", "prenom": "Loéva", "idClasse": 5, "libelleClasse": "CM1 A"}]},
    {"id": 11, "civilite": "M.", "nom": "DORLY", "prenom": "Jean", "type": "responsable", "dejaConnecte": False,
     "enfants": [{"nom": "DORLY", "prenom": "Siloé", "idClasse": 8, "libelleClasse": "CM2 B"}]},
    {"id": 12, "civilite": "M.", "nom": "MARIE", "prenom": "Jérôme", "type": "responsable", "dejaConnecte": False,
     "enfants": [{"nom": "MARIE", "prenom": "Camille", "idClasse": 8, "libelleClasse": "CM2 B"}]},
]


def _row(result, libelle):
    return next(r for r in result["classes"] if r["classe"] == libelle)


def test_counts_per_class_and_accent_insensitive_matching():
    res = compute_activation(FAMILLES, ELEVES)
    cm2 = _row(res, "CM2 B")
    assert cm2["eleves"] == 3
    assert cm2["responsables"] == 3 and cm2["responsables_connectes"] == 1
    # Siloé : un parent connecté (« Siloe » sans accent doit matcher) ; Camille : non ; Paul : aucun compte
    assert cm2["eleves_sans_aucun_parent_connecte"] == 1
    assert cm2["eleves_sans_compte_responsable"] == 1
    assert cm2["taux_activation_familles"] == 33.3
    assert _row(res, "CM1 A")["taux_activation_familles"] == 100.0
    s = res["synthese"]
    assert s["eleves"] == 4 and s["comptes_responsables"] == 3 and s["comptes_responsables_connectes"] == 1
    assert s["eleves_avec_au_moins_un_parent_connecte"] == 2


def test_no_names_by_default():
    cm2 = _row(compute_activation(FAMILLES, ELEVES), "CM2 B")
    assert "responsables_jamais_connectes" not in cm2


def test_filter_by_label_or_id_with_names():
    for classe in ("cm2 b", "CM2B", "8"):
        res = compute_activation(FAMILLES, ELEVES, classe=classe, inclure_noms=True)
        assert [r["classe"] for r in res["classes"]] == ["CM2 B"]
        row = res["classes"][0]
        assert [r["responsable"] for r in row["responsables_jamais_connectes"]] == ["M. DORLY Jean", "M. MARIE Jérôme"]
        assert row["eleves_sans_aucun_parent_connecte_noms"] == ["MARIE Camille"]
        assert row["eleves_sans_compte_responsable_noms"] == ["SEUL Paul"]
        assert res["synthese"]["comptes_responsables"] == 3


@respx.mock
async def test_tool_fetches_full_directories(tmp_path, monkeypatch):
    fam = respx.post(url__startswith=f"{API}utilisateurs/familles.awp").mock(return_value=ok({"utilisateurs": FAMILLES}))
    elv = respx.post(url__startswith=f"{API}utilisateurs/eleves.awp").mock(return_value=ok({"utilisateurs": ELEVES}))
    monkeypatch.setattr(server, "_client", EcoleDirecteAdminClient(auth=fake_auth(tmp_path)))
    res = await server.ed_admin_activation_comptes(classe="CM2 B")
    assert fam.calls[0].request.url.params["filterSearch"] == ""
    assert elv.called
    assert "responsables_jamais_connectes" in res["classes"][0]
    res_all = await server.ed_admin_activation_comptes()
    assert "responsables_jamais_connectes" not in res_all["classes"][0]


def test_pupil_without_class_is_labelled():
    eleves = [{"id": 9, "nom": "X", "prenom": "Y", "idClasse": 0, "libelleClasse": "", "dejaConnecte": False}]
    res = compute_activation([], eleves)
    assert res["classes"][0]["classe"] == "(sans classe)"

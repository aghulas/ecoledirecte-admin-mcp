"""Gestion des comptes de connexion : lecture/régénération des codes, déblocage,
changement de mot de passe. Aucun accès réseau réel (respx), aucun secret renvoyé."""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
import respx

from mcp.server.mcpserver.exceptions import ToolError

from ecoledirecte_admin_mcp import codes_connexion as cc
from ecoledirecte_admin_mcp.client import EcoleDirecteAdminClient

from ._helpers import API, fake_auth, ok

SECRET_IDENT = "0000000Aabc"
SECRET_MDP = "Mdp1ereConnexion!"
CODES = {"edNomUtilisateurOrigine": SECRET_IDENT, "edMotDePasseOrigine": SECRET_MDP, "at": "QR-TOKEN-XYZ"}


def _client(tmp_path):
    return EcoleDirecteAdminClient(auth=fake_auth(tmp_path))


def _actif(monkeypatch, tmp_path):
    monkeypatch.setenv("ED_ADMIN_COMPTES_ACTIF", "1")
    d = tmp_path / "codes"
    monkeypatch.setenv("ED_ADMIN_CODES_DIR", str(d))
    return d


def _verbe(call) -> str:
    return parse_qs(urlparse(str(call.request.url)).query).get("verbe", [""])[0]


# --- lecture ---------------------------------------------------------------

@respx.mock
async def test_lire_ecrit_fichier_sans_renvoyer_les_codes(tmp_path, monkeypatch):
    d = _actif(monkeypatch, tmp_path)
    route = respx.post(url__startswith=f"{API}compteOrigineED/A/42.awp").mock(return_value=ok(CODES))
    out = await cc.lire_codes(_client(tmp_path), "personnel", 42)
    assert route.called and _verbe(route.calls.last) == "get"
    # aucun secret dans la réponse
    blob = repr(out)
    assert SECRET_IDENT not in blob and SECRET_MDP not in blob and "QR-TOKEN" not in blob
    assert out["codes_dans_la_reponse"] is False
    assert out["identifiant_present"] and out["mot_de_passe_present"] and out["jeton_qr_present"]
    # mais le fichier local les contient, en 0600
    chemin = out["fichier_local"]
    contenu = open(chemin, encoding="utf-8").read()
    assert SECRET_IDENT in contenu and SECRET_MDP in contenu
    import os, stat
    assert stat.S_IMODE(os.stat(chemin).st_mode) == 0o600


@respx.mock
async def test_lire_refuse_sans_dossier(tmp_path, monkeypatch):
    monkeypatch.setenv("ED_ADMIN_COMPTES_ACTIF", "1")
    monkeypatch.delenv("ED_ADMIN_CODES_DIR", raising=False)
    route = respx.post(url__startswith=API).mock(return_value=ok(CODES))
    with pytest.raises(ToolError, match="ED_ADMIN_CODES_DIR"):
        await cc.lire_codes(_client(tmp_path), "personnel", 42)
    assert not route.called


@respx.mock
async def test_lire_refuse_si_non_actif(tmp_path, monkeypatch):
    monkeypatch.delenv("ED_ADMIN_COMPTES_ACTIF", raising=False)
    monkeypatch.setenv("ED_ADMIN_CODES_DIR", str(tmp_path / "codes"))
    route = respx.post(url__startswith=API).mock(return_value=ok(CODES))
    with pytest.raises(ToolError, match="ED_ADMIN_COMPTES_ACTIF"):
        await cc.lire_codes(_client(tmp_path), "personnel", 42)
    assert not route.called


async def test_role_invalide(tmp_path, monkeypatch):
    _actif(monkeypatch, tmp_path)
    with pytest.raises(ToolError, match="role invalide"):
        await cc.lire_codes(_client(tmp_path), "directeur", 42)


@respx.mock
async def test_mapping_role_vers_type_court(tmp_path, monkeypatch):
    _actif(monkeypatch, tmp_path)
    route = respx.post(url__startswith=f"{API}compteOrigineED/1/7.awp").mock(return_value=ok(CODES))
    out = await cc.lire_codes(_client(tmp_path), "responsable", 7)
    assert route.called
    assert out["compte"]["type_court"] == "1"


# --- régénération ----------------------------------------------------------

@respx.mock
async def test_regenerer_apercu_sans_reseau(tmp_path, monkeypatch):
    _actif(monkeypatch, tmp_path)
    route = respx.post(url__startswith=API).mock(return_value=ok(CODES))
    out = await cc.regenerer_codes(_client(tmp_path), "eleve", 99, confirm=False)
    assert not route.called
    assert out["ecriture_effectuee"] is False
    assert "associations" in out["avertissement"].lower()


@respx.mock
async def test_regenerer_confirm_delete_puis_get(tmp_path, monkeypatch):
    _actif(monkeypatch, tmp_path)
    route = respx.post(url__startswith=f"{API}compteOrigineED/E/99.awp").mock(return_value=ok(CODES))
    out = await cc.regenerer_codes(_client(tmp_path), "eleve", 99, confirm=True)
    verbes = [_verbe(c) for c in route.calls]
    assert verbes == ["delete", "get"]
    assert out["ecriture_effectuee"] is True
    assert SECRET_MDP not in repr(out)
    assert SECRET_MDP in open(out["fichier_local"], encoding="utf-8").read()


@respx.mock
async def test_regenerer_confirm_refuse_si_non_actif(tmp_path, monkeypatch):
    monkeypatch.delenv("ED_ADMIN_COMPTES_ACTIF", raising=False)
    monkeypatch.setenv("ED_ADMIN_CODES_DIR", str(tmp_path / "codes"))
    route = respx.post(url__startswith=API).mock(return_value=ok(CODES))
    with pytest.raises(ToolError, match="ED_ADMIN_COMPTES_ACTIF"):
        await cc.regenerer_codes(_client(tmp_path), "eleve", 99, confirm=True)
    assert not route.called


# --- déblocage -------------------------------------------------------------

@respx.mock
async def test_debloquer_apercu_lit_etat(tmp_path, monkeypatch):
    monkeypatch.setenv("ED_ADMIN_COMPTES_ACTIF", "1")
    route = respx.post(url__startswith=f"{API}blockingState/A/5.awp").mock(return_value=ok({"isBloque": True}))
    out = await cc.debloquer(_client(tmp_path), "personnel", 5, confirm=False)
    assert [_verbe(c) for c in route.calls] == ["get"]
    assert out["est_bloque"] is True and out["ecriture_effectuee"] is False


@respx.mock
async def test_debloquer_confirm_delete(tmp_path, monkeypatch):
    monkeypatch.setenv("ED_ADMIN_COMPTES_ACTIF", "1")
    route = respx.post(url__startswith=f"{API}blockingState/A/5.awp").mock(
        side_effect=[ok({"isBloque": True}), ok({}), ok({"isBloque": False})]
    )
    out = await cc.debloquer(_client(tmp_path), "personnel", 5, confirm=True)
    assert [_verbe(c) for c in route.calls] == ["get", "delete", "get"]
    assert out["etait_bloque"] is True and out["est_bloque"] is False
    assert out["ecriture_effectuee"] is True


# --- changement de mot de passe -------------------------------------------

@respx.mock
async def test_changement_mdp_apercu_sans_reseau(tmp_path, monkeypatch):
    monkeypatch.setenv("ED_ADMIN_COMPTES_ACTIF", "1")
    route = respx.post(url__startswith=API).mock(return_value=ok({}))
    out = await cc.demander_changement_mdp(_client(tmp_path), "responsable", 7, confirm=False)
    assert not route.called and out["ecriture_effectuee"] is False


@respx.mock
async def test_changement_mdp_confirm_put(tmp_path, monkeypatch):
    monkeypatch.setenv("ED_ADMIN_COMPTES_ACTIF", "1")
    route = respx.post(url__startswith=f"{API}compteOrigineED/1/7.awp").mock(return_value=ok({}))
    out = await cc.demander_changement_mdp(_client(tmp_path), "responsable", 7, confirm=True)
    assert [_verbe(c) for c in route.calls] == ["put"]
    assert out["ecriture_effectuee"] is True

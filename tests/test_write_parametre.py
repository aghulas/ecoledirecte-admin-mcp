"""set_parametre : SEULE méthode d'écriture du connecteur admin. Garde-fous
(secrets, exclusions front, aperçu sans confirm) + forme exacte de l'écriture
réelle (verbe=post, jeton, relecture) — tout mocké via respx, aucun réseau réel."""
from __future__ import annotations

import httpx
import pytest
import respx

from ecoledirecte_admin_mcp.client import (
    EcoleDirecteAdminClient,
    ForbiddenEndpointError,
    is_front_excluded_param,
    is_secret_param,
)

from ._helpers import API, decode_body, fake_auth, ok


# ---- garde-fous : refusés d'office, avant tout appel réseau, même avec confirm=True ----
@pytest.mark.parametrize("libelle", [
    "Sites/Connecteurs/MonApi/ApiKey",
    "Sites/Admin/CertificatSSO",
    "Sites/Familles/MotDePasse/Regle",
])
def test_secret_libelle_detected(libelle):
    assert is_secret_param(libelle)


@pytest.mark.parametrize("libelle", [
    "Sites/Familles/Comptabilité/ReglementsEnLigne/Banque",
    "Sites/Validitemdp/NbJours",
    "Notes/NbreJoursDécalage",
])
def test_front_excluded_libelle_detected(libelle):
    assert is_front_excluded_param(libelle)


@respx.mock
async def test_secret_param_refused_before_any_network_call(tmp_path):
    route = respx.post(url__startswith=f"{API}parametres.awp")
    client = EcoleDirecteAdminClient(auth=fake_auth(tmp_path))
    with pytest.raises(ForbiddenEndpointError):
        await client.set_parametre("Sites/Connecteurs/X/ApiKey", "abc", confirm=True)
    assert not route.calls
    await client.aclose()


@respx.mock
async def test_front_excluded_param_refused_before_any_network_call(tmp_path):
    route = respx.post(url__startswith=f"{API}parametres.awp")
    client = EcoleDirecteAdminClient(auth=fake_auth(tmp_path))
    with pytest.raises(ForbiddenEndpointError):
        await client.set_parametre("Sites/ValiditeMDP/NbJours", "90", confirm=True)
    assert not route.calls
    await client.aclose()


# ---- sans confirm=True : aperçu uniquement, aucune écriture ----
@respx.mock
async def test_preview_without_confirm_does_not_write(tmp_path):
    route = respx.post(url__startswith=f"{API}parametres.awp").mock(
        return_value=ok({"parametres": [{"libelle": "Sites/Familles/Actif", "valeur": "0"}]})
    )
    client = EcoleDirecteAdminClient(auth=fake_auth(tmp_path))
    result = await client.set_parametre("Sites/Familles/Actif", "1")
    assert result == {
        "libelle": "Sites/Familles/Actif",
        "valeur_actuelle": "0",
        "valeur_proposee": "1",
        "ecriture_effectuee": False,
        "message": "Aperçu seulement, rien n'a été écrit — rappelle avec confirm=True pour appliquer.",
    }
    # Un seul appel réseau (la lecture pour l'aperçu), forcément verbe=get.
    assert len(route.calls) == 1
    assert route.calls[0].request.url.params["verbe"] == "get"
    await client.aclose()


# ---- avec confirm=True : écrit réellement (verbe=post), puis relit ----
@respx.mock
async def test_confirm_writes_with_verbe_post_and_rereads(tmp_path):
    route = respx.post(url__startswith=f"{API}parametres.awp").mock(
        side_effect=[
            ok({"parametres": [{"libelle": "Sites/Familles/Actif", "valeur": "0", "encoded": False}]}, token="tok-1"),
            ok({"parametres": [{"libelle": "Sites/Familles/Actif", "valeur": "1"}]}, token="tok-2"),
            ok({"parametres": [{"libelle": "Sites/Familles/Actif", "valeur": "1"}]}, token="tok-3"),
        ]
    )
    client = EcoleDirecteAdminClient(auth=fake_auth(tmp_path))
    result = await client.set_parametre("Sites/Familles/Actif", "1", confirm=True)

    assert len(route.calls) == 3
    read1, write, read2 = (c.request for c in route.calls)
    assert read1.url.params["verbe"] == "get"
    assert write.url.params["verbe"] == "post"
    assert read2.url.params["verbe"] == "get"
    # Le corps d'écriture renvoie l'entrée complète (avec 'encoded'), valeur modifiée.
    sent = decode_body(write)
    assert sent["parametres"] == [{"libelle": "Sites/Familles/Actif", "valeur": "1", "encoded": False}]
    # Rotation du jeton respectée sur les 3 appels.
    assert read1.headers["x-token"] == "tok-0"
    assert write.headers["x-token"] == "tok-1"
    assert read2.headers["x-token"] == "tok-2"

    assert result == {
        "libelle": "Sites/Familles/Actif",
        "valeur_avant": "0",
        "valeur_demandee": "1",
        "valeur_apres": "1",
        "ecriture_effectuee": True,
        "coherent": True,
    }
    await client.aclose()


@respx.mock
async def test_write_error_code_raises(tmp_path):
    route = respx.post(url__startswith=f"{API}parametres.awp").mock(
        side_effect=[
            ok({"parametres": [{"libelle": "Sites/Familles/Actif", "valeur": "0"}]}),
            httpx.Response(200, json={"code": 403, "token": "tok-x", "message": "refusé"}),
        ]
    )
    client = EcoleDirecteAdminClient(auth=fake_auth(tmp_path))
    with pytest.raises(Exception, match="403"):
        await client.set_parametre("Sites/Familles/Actif", "1", confirm=True)
    await client.aclose()


# ---- outil serveur : confirm=False par défaut ----
@respx.mock
async def test_tool_default_confirm_false_previews_only(tmp_path, monkeypatch):
    from ecoledirecte_admin_mcp import server

    route = respx.post(url__startswith=f"{API}parametres.awp").mock(
        return_value=ok({"parametres": [{"libelle": "Sites/Familles/Actif", "valeur": "0"}]})
    )
    monkeypatch.setattr(server, "_client", EcoleDirecteAdminClient(auth=fake_auth(tmp_path)))
    result = await server.ed_admin_parametre_set("Sites/Familles/Actif", "1")
    assert result["ecriture_effectuee"] is False
    assert len(route.calls) == 1  # lecture seule, pas d'écriture

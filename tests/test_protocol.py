"""Forme exacte des requêtes (URL .awp?verbe=get, form data=JSON, x-token) et
rotation du token — protocole confirmé sur l'API réelle le 15/09/2026."""
from __future__ import annotations

import httpx
import pytest
import respx

from ecoledirecte_admin_mcp.auth import AuthError
from ecoledirecte_admin_mcp.client import EcoleDirecteAdminClient, EcoleDirecteApiError

from ._helpers import API, USER, decode_body, fake_auth, ok


@respx.mock
async def test_get_request_shape_and_token_rotation(tmp_path):
    route = respx.post(url__startswith=f"{API}utilisateurs/familles.awp").mock(
        side_effect=[ok({"utilisateurs": []}, token="tok-1"), ok({"utilisateurs": []}, token="tok-2")]
    )
    auth = fake_auth(tmp_path)
    client = EcoleDirecteAdminClient(auth=auth)
    await client.list_utilisateurs("familles", "mar")
    req = route.calls[0].request
    assert req.url.params["verbe"] == "get"
    assert req.url.params["filterSearch"] == "mar"
    assert req.headers["x-token"] == "tok-0"
    assert req.headers["content-type"] == "application/x-www-form-urlencoded"
    assert decode_body(req) == {"token": "tok-0"}
    # Le token renvoyé doit être utilisé pour l'appel suivant, et persisté.
    await client.list_utilisateurs("familles", "mar")
    assert route.calls[1].request.headers["x-token"] == "tok-1"
    assert auth.store.load().token == "tok-2"
    await client.aclose()


@respx.mock
async def test_parametres_sent_in_data(tmp_path):
    route = respx.post(url__startswith=f"{API}parametres.awp").mock(
        return_value=ok({"parametres": [{"libelle": "Messagerie/Actif", "valeur": "1"}]})
    )
    client = EcoleDirecteAdminClient(auth=fake_auth(tmp_path))
    result = await client.get_parametres(["Messagerie/Actif"])
    assert decode_body(route.calls[0].request)["parametres"] == [{"libelle": "Messagerie/Actif"}]
    assert result == [{"libelle": "Messagerie/Actif", "valeur": "1"}]


@respx.mock
async def test_login_when_no_session_then_call(tmp_path):
    login = respx.post(f"{API}login.awp").mock(
        return_value=httpx.Response(200, json={"code": 200, "token": "tok-login", "data": USER})
    )
    classes = respx.post(url__startswith=f"{API}classes.awp").mock(return_value=ok([{"id": 1}]))
    client = EcoleDirecteAdminClient(auth=fake_auth(tmp_path, logged_in=False))
    assert await client.list_classes() == [{"id": 1}]
    body = decode_body(login.calls[0].request)
    assert body == {"identifiant": "admin-id", "motdepasse": "pw-secret", "codeSecure": ""}
    assert classes.calls[0].request.headers["x-token"] == "tok-login"


@respx.mock
async def test_relogin_once_on_expired_session(tmp_path):
    respx.post(f"{API}login.awp").mock(
        return_value=httpx.Response(200, json={"code": 200, "token": "tok-new", "data": USER})
    )
    route = respx.post(url__startswith=f"{API}classes.awp").mock(
        side_effect=[httpx.Response(200, json={"code": 525, "message": "expired"}), ok([])]
    )
    client = EcoleDirecteAdminClient(auth=fake_auth(tmp_path, token="tok-old"))
    assert await client.list_classes() == []
    assert route.calls[1].request.headers["x-token"] == "tok-new"


@respx.mock
async def test_login_errors_never_leak_password(tmp_path):
    respx.post(f"{API}login.awp").mock(
        return_value=httpx.Response(200, json={"code": 505, "message": "bad pw-secret"})
    )
    client = EcoleDirecteAdminClient(auth=fake_auth(tmp_path, logged_in=False))
    with pytest.raises(AuthError) as exc:
        await client.list_classes()
    assert "pw-secret" not in str(exc.value)


@respx.mock
async def test_3dsecure_is_explicit_error(tmp_path):
    respx.post(f"{API}login.awp").mock(
        return_value=httpx.Response(200, json={"code": 202, "data": {"etablissements": []}})
    )
    client = EcoleDirecteAdminClient(auth=fake_auth(tmp_path, logged_in=False))
    with pytest.raises(AuthError, match="3DSecure"):
        await client.list_classes()


@respx.mock
async def test_non_200_code_raises(tmp_path):
    respx.post(url__startswith=f"{API}stats/ecoledirecte.awp").mock(
        return_value=httpx.Response(200, json={"code": 210, "message": "oops", "token": "t"})
    )
    client = EcoleDirecteAdminClient(auth=fake_auth(tmp_path))
    with pytest.raises(EcoleDirecteApiError, match="210"):
        await client.stats()


@respx.mock
async def test_synchros_uses_code_ogec(tmp_path):
    route = respx.post(url__startswith=f"{API}synchrosED/0000000A.awp").mock(return_value=ok({"moduleVS": {}}))
    client = EcoleDirecteAdminClient(auth=fake_auth(tmp_path))
    assert await client.synchros() == {"moduleVS": {}}
    assert route.called

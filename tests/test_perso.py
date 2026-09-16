"""Tests espace personnel : protocole, rotation du jeton, garde-fous, double auth.
Aucun accès réseau réel ni Trousseau : login/appels mockés via respx."""
from __future__ import annotations

import json
from urllib.parse import unquote

import httpx
import pytest
import respx

from ecoledirecte_perso_mcp import server
from ecoledirecte_perso_mcp.auth import (
    DoubleAuthRequired,
    PersoAuth,
    Session,
    SessionStore,
)
from ecoledirecte_perso_mcp.client import (
    EcoleDirectePersoClient,
    ForbiddenEndpointError,
    check_allowed,
)

LOGIN = "https://api.ecoledirecte.com/v3"
DATA = "https://apip.ecoledirecte.com/v3"
ACCOUNT = {"id": 18, "typeCompte": "A", "nom": "COUTOULY", "prenom": "Agnès"}


def make_auth(tmp_path, *, token="tok-0", cn="cn-1", cv="cv-1", logged_in=True):
    store = SessionStore(path=tmp_path / "session.json")
    store.save(Session(token=token if logged_in else "", account=ACCOUNT if logged_in else {},
                       cn=cn, cv=cv))
    return PersoAuth(store=store, password_provider=lambda i: "pw-secret",
                     identifiant_provider=lambda: "secr-id")


def body(request):
    raw = request.content.decode()
    assert raw.startswith("data=")
    return json.loads(unquote(raw[len("data="):]))


def ok(data, token="tok-next"):
    return httpx.Response(200, json={"code": 200, "token": token, "data": data})


# ---- garde-fous ----
@pytest.mark.parametrize("verbe", ["post", "put", "delete"])
def test_only_get(verbe):
    with pytest.raises(ForbiddenEndpointError):
        check_allowed("personnels/18/messages", verbe)


@pytest.mark.parametrize("path", [
    "personnels/18/messages/12345",   # ouvrir un message → marque lu
    "personnels/18/messages/9/marquerLu",
    "personnels/18/messages/corbeille",
])
def test_single_message_and_actions_blocked(path):
    with pytest.raises(ForbiddenEndpointError):
        check_allowed(path, "get")


def test_message_list_allowed():
    check_allowed("personnels/18/messages", "get")  # ne lève pas


def test_client_has_no_write_helpers():
    # Aucune méthode publique d'écriture (postits = lecture du tableau, autorisé).
    write_words = ("envoy", "supprim", "marquer", "creer", "delete", "update", "put_", "post_")
    for n in dir(EcoleDirectePersoClient):
        if not n.startswith("_"):
            assert not any(w in n.lower() for w in write_words), n


# ---- protocole & rotation du jeton ----
@respx.mock
async def test_messages_list_shape_and_token_rotation(tmp_path):
    route = respx.post(url__startswith=f"{DATA}/personnels/18/messages.awp").mock(
        side_effect=[ok({"messages": {"received": []}}, token="tok-1"),
                     ok({"messages": {"received": []}}, token="tok-2")]
    )
    client = EcoleDirectePersoClient(auth=make_auth(tmp_path))
    await client.list_messages()
    req = route.calls[0].request
    assert req.url.params["verbe"] == "get"
    assert req.url.params["typeRecuperation"] == "received"
    assert req.headers["x-token"] == "tok-0"
    assert body(req) == {"anneeMessages": "2026-2027"}
    await client.list_messages()
    assert route.calls[1].request.headers["x-token"] == "tok-1"  # jeton tourné
    assert client.auth.store.load().token == "tok-2"
    await client.aclose()


@respx.mock
async def test_classe_eleves_path(tmp_path):
    route = respx.post(url__startswith=f"{DATA}/classes/8/eleves.awp").mock(return_value=ok([{"id": 1}]))
    client = EcoleDirectePersoClient(auth=make_auth(tmp_path))
    assert await client.classe_eleves("8") == [{"id": 1}]
    assert route.called


@respx.mock
async def test_relogin_on_expired_token(tmp_path):
    respx.get(f"{LOGIN}/login.awp").mock(return_value=httpx.Response(200, headers={"Set-Cookie": "GTK=g1"}, json={}))
    respx.post(f"{LOGIN}/login.awp").mock(
        return_value=httpx.Response(200, json={"code": 200, "token": "tok-new", "data": {"accounts": [ACCOUNT]}})
    )
    route = respx.post(url__startswith=f"{DATA}/personnels/18/agendaEvenements.awp").mock(
        side_effect=[httpx.Response(200, json={"code": 525, "message": "expired"}), ok({"evenements": []})]
    )
    client = EcoleDirectePersoClient(auth=make_auth(tmp_path, token="tok-old"))
    assert await client.agenda_evenements() == {"evenements": []}
    assert route.calls[1].request.headers["x-token"] == "tok-new"


# ---- login ----
@respx.mock
async def test_headless_login_uses_stored_cn_cv(tmp_path):
    respx.get(f"{LOGIN}/login.awp").mock(return_value=httpx.Response(200, headers={"Set-Cookie": "GTK=g1"}, json={}))
    login = respx.post(f"{LOGIN}/login.awp").mock(
        return_value=httpx.Response(200, json={"code": 200, "token": "tok-login", "data": {"accounts": [ACCOUNT]}})
    )
    auth = make_auth(tmp_path, logged_in=False, cn="cn-9", cv="cv-9")
    async with httpx.AsyncClient() as c:
        session = await auth.login(c)
    assert session.account_id == "18" and session.type_compte == "A"
    sent = body(login.calls[0].request)
    assert sent["fa"] == [{"cn": "cn-9", "cv": "cv-9"}]
    assert "pw-secret" == sent["motdepasse"]  # (mock) — jamais loggé en vrai


@respx.mock
async def test_double_auth_required_when_no_cn(tmp_path):
    respx.get(f"{LOGIN}/login.awp").mock(return_value=httpx.Response(200, json={}))
    respx.post(f"{LOGIN}/login.awp").mock(return_value=httpx.Response(200, json={"code": 250, "token": "temp"}))
    auth = make_auth(tmp_path, logged_in=False, cn="", cv="")
    async with httpx.AsyncClient() as c:
        with pytest.raises(DoubleAuthRequired):
            await auth.login(c)


@respx.mock
async def test_login_error_hides_password(tmp_path):
    respx.get(f"{LOGIN}/login.awp").mock(return_value=httpx.Response(200, json={}))
    respx.post(f"{LOGIN}/login.awp").mock(return_value=httpx.Response(200, json={"code": 505, "message": "bad pw-secret"}))
    auth = make_auth(tmp_path, logged_in=False)
    async with httpx.AsyncClient() as c:
        with pytest.raises(Exception) as exc:
            await auth.login(c)
    assert "pw-secret" not in str(exc.value)


# ---- outil serveur ----
@respx.mock
async def test_tool_messages_list_validates_boite(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_client", EcoleDirectePersoClient(auth=make_auth(tmp_path)))
    with pytest.raises(ToolError_or_value_error()):
        await server.ed_perso_messages_list(boite="poubelle")


def ToolError_or_value_error():
    from mcp.server.mcpserver.exceptions import ToolError
    return ToolError

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
ACCOUNT = {"id": 18, "typeCompte": "A", "nom": "DURAND", "prenom": "Jeanne"}


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


# ---- redaction des fiches élèves ----
ELEVE = {"id": 1, "nom": "X", "prenom": "Y", "email": "y@x.fr", "portable": "0600",
         "dateNaissance": "01/01/2015", "numeroBadge": "999", "photo": "/p.jpg",
         "responsables": [{"id": 5, "civilite": "Mme", "nom": "X", "prenom": "Z", "role": "MERE"}]}


@respx.mock
async def test_classe_eleves_redacts_by_default(tmp_path):
    respx.post(url__startswith=f"{DATA}/classes/8/eleves.awp").mock(
        return_value=ok({"entity": {"id": 8}, "eleves": [ELEVE]})
    )
    client = EcoleDirectePersoClient(auth=make_auth(tmp_path))
    e = (await client.classe_eleves("8"))["eleves"][0]
    assert "dateNaissance" not in e and "numeroBadge" not in e and "photo" not in e
    assert e["email"] == "y@x.fr"          # coordonnées élève conservées
    assert e["responsables"][0]["role"] == "MERE"


@respx.mock
async def test_classe_eleves_full_on_demand(tmp_path):
    respx.post(url__startswith=f"{DATA}/classes/8/eleves.awp").mock(
        return_value=ok({"entity": {"id": 8}, "eleves": [ELEVE]})
    )
    client = EcoleDirectePersoClient(auth=make_auth(tmp_path))
    e = (await client.classe_eleves("8", include_sensitive_fields=True))["eleves"][0]
    assert e["dateNaissance"] == "01/01/2015"


@respx.mock
async def test_classe_eleves_unexpected_shape_refused(tmp_path):
    respx.post(url__startswith=f"{DATA}/classes/8/eleves.awp").mock(
        return_value=ok({"entity": {}, "eleves": "pas une liste"})
    )
    client = EcoleDirectePersoClient(auth=make_auth(tmp_path))
    with pytest.raises(Exception, match="format inattendu"):
        await client.classe_eleves("8")


# ---- coordonnées des responsables (eleves/{id}/coordonneesfamille) ----
FAMILLE = [{
    "adresseLigne1": "1 rue Test", "adresseLigne2": "", "adresseLigne3": "",
    "codePostal": "00000", "ville": "VILLE-EXEMPLE", "typeLien": 1, "typeLienLibelle": "Père",
    "responsable": {"civilite": "M.", "nom": "X", "nomSimple": "X", "prenom": "Y",
                    "telDomicile": "0100000000", "telTravail": "0200000000",
                    "telMobile": "0600000000", "mailTravail": "y@work.fr",
                    "mailPerso": "y@perso.fr", "profession": "Cadre",
                    "societe": "Acme", "csp": {"code": "3", "libelle": "Cadres"}},
    "conjoint": {"civilite": "Mme", "nom": "X", "nomSimple": "X", "prenom": "Z",
                "telMobile": "0700000000", "mailPerso": "z@perso.fr",
                "profession": "Infirmière", "societe": "Hopital", "csp": {"code": "4", "libelle": "..."}},
}]


@respx.mock
async def test_coordonnees_famille_redacts_by_default(tmp_path):
    respx.post(url__startswith=f"{DATA}/eleves/881/coordonneesfamille.awp").mock(
        return_value=ok(FAMILLE)
    )
    client = EcoleDirectePersoClient(auth=make_auth(tmp_path))
    out = await client.eleve_coordonnees_famille("881")
    resp = out[0]["responsable"]
    conj = out[0]["conjoint"]
    for d in (resp, conj):
        assert "profession" not in d and "societe" not in d and "csp" not in d
    # coordonnées elles-mêmes conservées
    assert resp["mailPerso"] == "y@perso.fr" and resp["telMobile"] == "0600000000"
    assert out[0]["ville"] == "VILLE-EXEMPLE"


@respx.mock
async def test_coordonnees_famille_full_on_demand(tmp_path):
    respx.post(url__startswith=f"{DATA}/eleves/881/coordonneesfamille.awp").mock(
        return_value=ok(FAMILLE)
    )
    client = EcoleDirectePersoClient(auth=make_auth(tmp_path))
    out = await client.eleve_coordonnees_famille("881", include_sensitive_fields=True)
    assert out[0]["responsable"]["profession"] == "Cadre"


@respx.mock
async def test_coordonnees_famille_unexpected_shape_refused(tmp_path):
    respx.post(url__startswith=f"{DATA}/eleves/881/coordonneesfamille.awp").mock(
        return_value=ok({"pas": "une liste"})
    )
    client = EcoleDirectePersoClient(auth=make_auth(tmp_path))
    with pytest.raises(Exception, match="format inattendu"):
        await client.eleve_coordonnees_famille("881")

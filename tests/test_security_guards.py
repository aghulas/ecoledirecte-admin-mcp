"""Garde-fous : lecture seule, endpoints à secrets bloqués, redaction."""
from __future__ import annotations

import pytest
import respx

from mcp.server.mcpserver.exceptions import ToolError

from ecoledirecte_admin_mcp import server
from ecoledirecte_admin_mcp.client import (
    EcoleDirecteAdminClient,
    ForbiddenEndpointError,
    check_allowed,
    is_secret_param,
    redact_parametres,
)

from ._helpers import API, fake_auth, ok


@pytest.mark.parametrize("verbe", ["post", "put", "delete", "PUT", "migrate"])
def test_only_get_allowed(verbe):
    with pytest.raises(ForbiddenEndpointError):
        check_allowed("parametres", verbe)


@pytest.mark.parametrize(
    "path",
    [
        "compteOrigineED/familles/657",  # identifiant + mdp de 1re connexion
        "supervisionmobile?id=1&type=F",  # identifiants supervision mobile
        "supervision",  # ouverture de session à la place d'un utilisateur
        "loginsED/familles",
        "blockingState/familles/1",
        "logins/0000000X",
        "loginCreation",
        "reinitLogin",
        "banques",
        "telechargement",
        "televersement",
    ],
)
def test_forbidden_endpoints_blocked_even_in_get(path):
    with pytest.raises(ForbiddenEndpointError):
        check_allowed(path, "get")


@respx.mock
async def test_forbidden_endpoint_never_hits_network(tmp_path):
    route = respx.post(url__startswith=API).mock(return_value=ok({}))
    client = EcoleDirecteAdminClient(auth=fake_auth(tmp_path))
    with pytest.raises(ForbiddenEndpointError):
        await client.get("compteOrigineED/familles/1")
    assert not route.called


def test_client_exposes_no_write_helpers():
    # Exception unique et explicite (16/09/2026) : set_parametre, la SEULE méthode
    # d'écriture du client — voir sa propre garde-fous dans test_write_parametre.py
    # (secrets/exclusions front refusés d'office, aperçu sans confirm=True). Toute
    # AUTRE méthode qui apparaîtrait ici ferait échouer ce test, comme avant.
    allowed_write_methods = {"set_parametre"}
    public = [n for n in dir(EcoleDirecteAdminClient) if not n.startswith("_")]
    for name in public:
        if name in allowed_write_methods:
            continue
        assert not name.startswith(("post", "put", "delete", "update", "create", "set", "reinit")), name


@pytest.mark.parametrize(
    "libelle,secret",
    [
        ("PaiementEnLigne/Certificat/Production", True),
        ("PaiementEnLigne/CleSecrete", True),
        ("Sites/Connecteurs/Voltaire/APIKey", True),
        ("SMTP/MotDePasse", True),
        ("Banque/IBAN", True),
        ("Sites/Familles/Notes/Etablissement_0/Notes/Actif", False),
        ("Sites/Familles/LSU/Cycles", False),
        ("Messagerie/Actif", False),
        ("Sites/Familles/Article/Actif", False),
    ],
)
def test_secret_param_detection(libelle, secret):
    assert is_secret_param(libelle) is secret


def test_redact_parametres_masks_value_only():
    params = [
        {"libelle": "PaiementEnLigne/CleSecrete", "valeur": "abc123"},
        {"libelle": "Messagerie/Actif", "valeur": "1"},
    ]
    assert redact_parametres(params) == [
        {"libelle": "PaiementEnLigne/CleSecrete", "valeur": "<masqué>"},
        {"libelle": "Messagerie/Actif", "valeur": "1"},
    ]


@respx.mock
async def test_familles_search_redacts_badge_and_photo(tmp_path, monkeypatch):
    user = {"id": 657, "nom": "X", "prenom": "Y", "badge": "123456", "photo": "/p.jpg",
            "enfants": [{"nom": "X", "prenom": "Z", "idClasse": 8, "libelleClasse": "CM2 B"}]}
    respx.post(url__startswith=f"{API}utilisateurs/familles.awp").mock(return_value=ok({"utilisateurs": [user]}))
    monkeypatch.setattr(server, "_client", EcoleDirecteAdminClient(auth=fake_auth(tmp_path)))
    redacted = await server.ed_admin_familles_search("xx")
    assert "badge" not in redacted[0] and "photo" not in redacted[0]
    assert redacted[0]["enfants"][0]["libelleClasse"] == "CM2 B"
    full = await server.ed_admin_familles_search("xx", include_sensitive_fields=True)
    assert full[0]["badge"] == "123456"


@respx.mock
async def test_unexpected_user_payload_refused(tmp_path, monkeypatch):
    respx.post(url__startswith=f"{API}utilisateurs/eleves.awp").mock(return_value=ok({"autre": 1}))
    monkeypatch.setattr(server, "_client", EcoleDirecteAdminClient(auth=fake_auth(tmp_path)))
    with pytest.raises(Exception, match="format inattendu"):
        await server.ed_admin_eleves_search("ma")


async def test_min_two_chars():
    with pytest.raises(ToolError):
        await server.ed_admin_familles_search("m")


async def test_auth_error_message_reaches_client(tmp_path, monkeypatch):
    """Sans setup, Claude doit voir le message explicite, pas « Error executing tool »."""
    from ecoledirecte_admin_mcp.auth import AdminAuth, AuthError, SessionStore

    def no_ident():
        raise AuthError("Identifiant admin non configuré.")

    auth = AdminAuth(store=SessionStore(path=tmp_path / "s.json"), identifiant_provider=no_ident)
    monkeypatch.setattr(server, "_client", EcoleDirecteAdminClient(auth=auth))
    with pytest.raises(ToolError) as exc:
        await server.mcp.call_tool("ed_admin_classes_list", {})
    assert "non configuré" in str(exc.value)

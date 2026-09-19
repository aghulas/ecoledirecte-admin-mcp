"""Utilitaires de test : auth factice, aucun accès réseau ni Trousseau réel."""
from __future__ import annotations

import json
from urllib.parse import unquote

import httpx

from ecoledirecte_admin_mcp.auth import AdminAuth, Session, SessionStore

API = "https://api.ecoledirecte.com/v3/admin/"
USER = {
    "codeOgec": "0000000A",
    "type": "A",
    "email": "admin@example.org",
    "etablissements": [{"id": 1, "code": "ETB", "RNE": "0000000A", "libelle": "Établissement Test", "$$hashKey": "x"}],
    "parametragesRNE": {"anneeScolaireDebut": 2026, "anneeScolaireFin": 2027},
}


def fake_auth(tmp_path, token: str = "tok-0", logged_in: bool = True) -> AdminAuth:
    store = SessionStore(path=tmp_path / "session.json")
    if logged_in:
        store.save(Session(token=token, user=USER))
    return AdminAuth(store=store, password_provider=lambda ident: "pw-secret",
                     identifiant_provider=lambda: "admin-id")


def decode_body(request: httpx.Request) -> dict:
    raw = request.content.decode()
    assert raw.startswith("data=")
    return json.loads(unquote(raw[len("data="):]))


def ok(data, token="tok-next"):
    return httpx.Response(200, json={"code": 200, "token": token, "host": "HTTP1", "data": data})

"""Authentification espace personnel EcoleDirecte (compte secrétariat).

Flux (voir docs/cartographie-api-personnel.md §3), plus complexe que l'admin :
  1. GET  login.awp?gtk=1   → cookie GTK, à renvoyer en header X-Gtk.
  2. POST login.awp  data={identifiant, motdepasse, isReLogin:false, uuid:"", fa:[...]}
  3. code 200 → {token, data.accounts[0]{id, typeCompte}}.
     code 250 → double authentification (QCM question secrète) requise.
     code 505 → identifiants invalides.
  4. Double auth : GET/POST connexion/doubleauth.awp → {cn, cv} (réutilisables) ;
     on relance le login avec fa=[{cn,cv}].

Le X-Token tourne à chaque appel : chaque réponse fournit un nouveau jeton.

Conception : la double auth (réponse à une question) ne peut PAS être résolue par
un serveur headless. Elle est faite UNE fois, interactivement, par la commande
`login`, qui mémorise cn/cv ; ensuite le serveur se reconnecte tout seul avec ces
jetons. Ce module ne journalise jamais mot de passe ni jeton.
"""
from __future__ import annotations

import base64
import json
import os
import stat
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any

import httpx
from mcp.server.mcpserver.exceptions import ToolError

from .config import SETTINGS

AUTH_EXPIRED_CODES = frozenset({520, 525})
DOUBLE_AUTH_CODE = 250
BAD_CREDENTIALS_CODE = 505


class AuthError(ToolError):
    """Erreur d'authentification — jamais construite avec un secret dans le message."""


class DoubleAuthRequired(AuthError):
    """Le compte exige une double authentification non encore résolue (cn/cv absents)."""


# ----------------------------------------------------------------------
# Identité / Trousseau
# ----------------------------------------------------------------------
def _identifiant() -> str:
    if SETTINGS.identifiant:
        return SETTINGS.identifiant
    if SETTINGS.config_path.exists():
        try:
            value = json.loads(SETTINGS.config_path.read_text()).get("identifiant")
        except json.JSONDecodeError as exc:
            raise AuthError(f"{SETTINGS.config_path} illisible — relance `login`.") from exc
        if value:
            return value
    raise AuthError(
        "Identifiant du compte personnel non configuré. Lance "
        "`python -m ecoledirecte_perso_mcp.auth login` ou définis ED_PERSO_IDENTIFIANT."
    )


def keychain_password(identifiant: str) -> str:
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", SETTINGS.keychain_service,
             "-a", identifiant, "-w"],
            capture_output=True, text=True, check=False,
        )
    except FileNotFoundError as exc:
        raise AuthError("Commande `security` introuvable (Trousseau macOS requis).") from exc
    if result.returncode != 0:
        raise AuthError(
            f"Mot de passe introuvable dans le Trousseau (service "
            f"'{SETTINGS.keychain_service}', compte '{identifiant}'). Lance `login`."
        )
    return result.stdout.rstrip("\n")


# ----------------------------------------------------------------------
# Session persistée : token (tournant) + cn/cv (double auth) + compte
# ----------------------------------------------------------------------
@dataclass
class Session:
    token: str = ""
    account: dict[str, Any] = field(default_factory=dict)
    cn: str = ""
    cv: str = ""

    @property
    def account_id(self) -> str | None:
        return str(self.account.get("id")) if self.account.get("id") is not None else None

    @property
    def type_compte(self) -> str | None:
        return self.account.get("typeCompte")


class SessionStore:
    def __init__(self, path=None):
        self.path = path or SETTINGS.session_path

    def load(self) -> Session:
        if not self.path.exists():
            return Session()
        try:
            raw = json.loads(self.path.read_text())
            return Session(token=raw.get("token", ""), account=raw.get("account", {}),
                           cn=raw.get("cn", ""), cv=raw.get("cv", ""))
        except (json.JSONDecodeError, AttributeError):
            return Session()

    def save(self, session: Session) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(self.path.parent, stat.S_IRWXU)
        self.path.write_text(json.dumps({
            "token": session.token, "account": session.account,
            "cn": session.cn, "cv": session.cv,
        }))
        os.chmod(self.path, stat.S_IRUSR | stat.S_IWUSR)

    def clear_token(self, session: Session) -> None:
        """Oublie seulement le token (garde cn/cv pour se reconnecter sans QCM)."""
        session.token = ""
        self.save(session)


def encode_form_data(data: dict[str, Any]) -> str:
    from urllib.parse import quote
    return "data=" + quote(json.dumps(data, ensure_ascii=False), safe="")


class PersoAuth:
    def __init__(self, store: SessionStore | None = None, password_provider=None,
                 identifiant_provider=None):
        self.store = store or SessionStore()
        self._password_provider = password_provider or keychain_password
        self._identifiant_provider = identifiant_provider or _identifiant
        self.session = self.store.load()

    def update_token(self, new_token: str | None) -> None:
        if new_token and new_token != self.session.token:
            self.session.token = new_token
            self.store.save(self.session)

    def invalidate_token(self) -> None:
        self.store.clear_token(self.session)

    async def ensure_session(self, client: httpx.AsyncClient) -> Session:
        if not self.session.token:
            await self.login(client)
        return self.session

    # ---- primitives réseau ----
    async def _get_gtk(self, client: httpx.AsyncClient) -> str:
        try:
            resp = await client.get(
                f"{SETTINGS.login_base}/login.awp",
                params={"gtk": 1, "v": SETTINGS.api_version},
                headers={"User-Agent": SETTINGS.user_agent},
            )
        except httpx.HTTPError as exc:
            raise AuthError(f"Échec réseau (gtk) : {type(exc).__name__}") from exc
        return resp.cookies.get("GTK") or client.cookies.get("GTK") or ""

    async def _post_login(self, client: httpx.AsyncClient, payload: dict[str, Any],
                          gtk: str) -> dict[str, Any]:
        headers = {"Content-Type": "application/x-www-form-urlencoded",
                   "User-Agent": SETTINGS.user_agent, "Accept": "application/json"}
        if gtk:
            headers["X-Gtk"] = gtk
        try:
            resp = await client.post(
                f"{SETTINGS.login_base}/login.awp",
                params={"v": SETTINGS.api_version},
                content=encode_form_data(payload), headers=headers,
            )
        except httpx.HTTPError as exc:
            raise AuthError(f"Échec réseau (login) : {type(exc).__name__}") from exc
        if resp.status_code != 200:
            raise AuthError(f"Login refusé (HTTP {resp.status_code}).")
        try:
            return resp.json()
        except ValueError as exc:
            raise AuthError("Réponse de login non JSON.") from exc

    def _apply_login_success(self, body: dict[str, Any]) -> Session:
        accounts = (body.get("data") or {}).get("accounts") or []
        if not accounts:
            raise AuthError("Login OK mais aucun compte dans la réponse.")
        self.session.token = body["token"]
        self.session.account = {k: accounts[0].get(k) for k in ("id", "typeCompte", "nom", "prenom")}
        self.store.save(self.session)
        return self.session

    async def login(self, client: httpx.AsyncClient) -> Session:
        """Login headless : réutilise cn/cv mémorisés. Lève DoubleAuthRequired si
        le compte redemande un QCM (→ relancer `login` en interactif)."""
        identifiant = self._identifiant_provider()
        password = self._password_provider(identifiant)
        gtk = await self._get_gtk(client)
        payload: dict[str, Any] = {
            "identifiant": identifiant, "motdepasse": password,
            "isReLogin": False, "uuid": "",
        }
        if self.session.cn and self.session.cv:
            payload["fa"] = [{"cn": self.session.cn, "cv": self.session.cv}]
        body = await self._post_login(client, payload, gtk)
        code = body.get("code")
        if code == 200 and body.get("token"):
            return self._apply_login_success(body)
        if code == DOUBLE_AUTH_CODE:
            raise DoubleAuthRequired(
                "Le compte demande une double authentification. Relance en interactif : "
                "`python -m ecoledirecte_perso_mcp.auth login`."
            )
        if code == BAD_CREDENTIALS_CODE:
            raise AuthError("Identifiant ou mot de passe invalide (code 505).")
        raise AuthError(f"Login refusé (code {code}).")


# ----------------------------------------------------------------------
# Double authentification interactive (CLI uniquement)
# ----------------------------------------------------------------------
def _b64d(s: str) -> str:
    return base64.b64decode(s).decode("utf-8", "replace")


def _b64e(s: str) -> str:
    return base64.b64encode(s.encode("utf-8")).decode()


async def _resolve_double_auth(client: httpx.AsyncClient, temp_token: str) -> tuple[str, str]:
    """Résout le QCM en posant la question à l'utilisateur sur le terminal.
    Renvoie (cn, cv) réutilisables."""
    headers = {"Content-Type": "application/x-www-form-urlencoded", "X-Token": temp_token,
               "User-Agent": SETTINGS.user_agent, "Accept": "application/json"}
    resp = await client.post(f"{SETTINGS.login_base}/connexion/doubleauth.awp",
                             params={"verbe": "get", "v": SETTINGS.api_version},
                             content=encode_form_data({}), headers=headers)
    body = resp.json()
    if body.get("code") != 200:
        raise AuthError(f"Double auth (get) refusée (code {body.get('code')}).")
    data = body["data"]
    question = _b64d(data["question"])
    propositions = [_b64d(p) for p in data["propositions"]]
    print("\nQuestion de sécurité EcoleDirecte :")
    print("  " + question)
    for i, p in enumerate(propositions):
        print(f"   [{i}] {p}")
    choix = input("Numéro de la bonne réponse : ").strip()
    reponse = propositions[int(choix)]
    resp2 = await client.post(f"{SETTINGS.login_base}/connexion/doubleauth.awp",
                              params={"verbe": "post", "v": SETTINGS.api_version},
                              content=encode_form_data({"choix": _b64e(reponse)}), headers=headers)
    body2 = resp2.json()
    if body2.get("code") != 200:
        raise AuthError(f"Double auth (post) refusée (code {body2.get('code')}).")
    return body2["data"]["cn"], body2["data"]["cv"]


async def _interactive_login(auth: PersoAuth) -> Session:
    identifiant = auth._identifiant_provider()
    password = auth._password_provider(identifiant)
    async with httpx.AsyncClient(timeout=SETTINGS.timeout_seconds) as client:
        gtk = await auth._get_gtk(client)
        payload = {"identifiant": identifiant, "motdepasse": password, "isReLogin": False, "uuid": ""}
        if auth.session.cn and auth.session.cv:
            payload["fa"] = [{"cn": auth.session.cn, "cv": auth.session.cv}]
        body = await auth._post_login(client, payload, gtk)
        if body.get("code") == DOUBLE_AUTH_CODE:
            cn, cv = await _resolve_double_auth(client, body["token"])
            auth.session.cn, auth.session.cv = cn, cv
            auth.store.save(auth.session)
            gtk = await auth._get_gtk(client)
            payload["fa"] = [{"cn": cn, "cv": cv}]
            body = await auth._post_login(client, payload, gtk)
        if body.get("code") == BAD_CREDENTIALS_CODE:
            raise AuthError("Identifiant ou mot de passe invalide (code 505).")
        if body.get("code") != 200 or not body.get("token"):
            raise AuthError(f"Login refusé (code {body.get('code')}).")
        return auth._apply_login_success(body)


# ----------------------------------------------------------------------
# CLI : login (interactif, gère le QCM) / setup (Trousseau) / logout
# ----------------------------------------------------------------------
def _setup_keychain() -> None:
    identifiant = input("Identifiant du compte personnel (secrétariat) : ").strip()
    if not identifiant:
        raise SystemExit("Identifiant vide.")
    SETTINGS.home_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(SETTINGS.home_dir, stat.S_IRWXU)
    SETTINGS.config_path.write_text(json.dumps({"identifiant": identifiant}))
    print("Le Trousseau va demander le mot de passe (saisie masquée, jamais affichée).")
    rc = subprocess.call(
        ["security", "add-generic-password", "-U", "-s", SETTINGS.keychain_service,
         "-a", identifiant, "-l", "EcoleDirecte perso (MCP)", "-w"]
    )
    if rc != 0:
        raise SystemExit(f"Échec Trousseau (code {rc}).")
    print(f"OK — identifiant dans {SETTINGS.config_path}, mot de passe dans le Trousseau.")


def _cli() -> None:
    import asyncio
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "setup":
        _setup_keychain()
    elif cmd == "login":
        if not SETTINGS.config_path.exists() and not SETTINGS.identifiant:
            _setup_keychain()
        auth = PersoAuth()
        session = asyncio.run(_interactive_login(auth))
        print(f"Connexion OK — compte {session.account_id} ({session.type_compte}). "
              f"Double auth mémorisée : {'oui' if session.cn else 'non'}.")
    elif cmd == "logout":
        SessionStore().clear_token(SessionStore().load())
        print("Token local oublié (cn/cv conservés).")
    else:
        print("Usage : python -m ecoledirecte_perso_mcp.auth [setup|login|logout]", file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    _cli()

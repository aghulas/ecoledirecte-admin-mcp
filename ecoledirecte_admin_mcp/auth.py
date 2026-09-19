"""Authentification admin EcoleDirecte : login automatique + Trousseau macOS.

Flux confirmé le 15/09/2026 par lecture du front admin (scripts.41ac2ecf.js,
AuthService.login / LoginService) — voir docs/cartographie-api-admin.md §3 :

  POST https://api.ecoledirecte.com/v3/admin/login.awp
  Content-Type: application/x-www-form-urlencoded
  data={"identifiant": "...", "motdepasse": "...", "codeSecure": ""}

Réponses :
  - code 200 : {token, data:{codeOgec, email, etablissements[...], parametragesRNE, ...}}
  - code 202 : étape « 3DSecure » (code envoyé par mail/SMS) → POST login/3DSecure.awp.
    Paramètre établissement `Sites/Admin/3DSecure/Actif` = 0 sur l'établissement
    testé au 15/09/2026 : pas géré automatiquement, erreur explicite si ça change.
  - code 505 : identifiant/mot de passe invalide ; 506 : code 3DSecure invalide.

Le token (36 caractères) TOURNE : chaque réponse API en renvoie un nouveau, à
réutiliser pour l'appel suivant. Codes 520/525 = session expirée → re-login.

Ce module ne journalise jamais ni mot de passe ni token.
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

import httpx
from mcp.server.mcpserver.exceptions import ToolError

from .config import SETTINGS

AUTH_EXPIRED_CODES = frozenset({520, 525})


class AuthError(ToolError):
    # ToolError : le message est transmis tel quel à Claude (sinon le SDK MCP ne
    # renvoie que « Error executing tool <nom> »).
    """Erreur d'authentification — jamais construite avec un secret dans le message."""


# ----------------------------------------------------------------------
# Trousseau macOS
# ----------------------------------------------------------------------
def _identifiant() -> str:
    if SETTINGS.identifiant:
        return SETTINGS.identifiant
    if SETTINGS.config_path.exists():
        try:
            value = json.loads(SETTINGS.config_path.read_text()).get("identifiant")
        except json.JSONDecodeError as exc:
            raise AuthError(f"{SETTINGS.config_path} illisible — relance `setup`.") from exc
        if value:
            return value
    raise AuthError(
        "Identifiant admin non configuré. Lance `python -m ecoledirecte_admin_mcp.auth setup` "
        "ou définis ED_ADMIN_IDENTIFIANT."
    )


def keychain_password(identifiant: str) -> str:
    """Lit le mot de passe dans le Trousseau via /usr/bin/security (sans l'afficher)."""
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
            f"'{SETTINGS.keychain_service}', compte '{identifiant}'). "
            "Lance `python -m ecoledirecte_admin_mcp.auth setup`."
        )
    return result.stdout.rstrip("\n")


# ----------------------------------------------------------------------
# Session (token tournant)
# ----------------------------------------------------------------------
@dataclass
class Session:
    token: str = ""
    user: dict[str, Any] = field(default_factory=dict)

    @property
    def code_ogec(self) -> str | None:
        return self.user.get("codeOgec")


class SessionStore:
    """Persiste le dernier token sur disque (600) pour éviter un login à chaque
    démarrage du serveur. Perdre ce fichier n'a aucune conséquence : re-login."""

    def __init__(self, path=None):
        self.path = path or SETTINGS.session_path

    def load(self) -> Session:
        if not self.path.exists():
            return Session()
        try:
            raw = json.loads(self.path.read_text())
            return Session(token=raw.get("token", ""), user=raw.get("user", {}))
        except (json.JSONDecodeError, AttributeError):
            return Session()

    def save(self, session: Session) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(self.path.parent, stat.S_IRWXU)
        self.path.write_text(json.dumps({"token": session.token, "user": session.user}))
        os.chmod(self.path, stat.S_IRUSR | stat.S_IWUSR)

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()


def encode_form_data(data: dict[str, Any]) -> str:
    """Corps `data=<JSON>` url-encodé (le front n'échappe que % & + ; un encodage
    complet est accepté par le serveur — vérifié le 15/09/2026)."""
    return "data=" + quote(json.dumps(data, ensure_ascii=False), safe="")


class AdminAuth:
    """Fournit un token valide ; se reconnecte avec le Trousseau si besoin."""

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

    def invalidate(self) -> None:
        self.session = Session()
        self.store.clear()

    async def ensure_session(self, client: httpx.AsyncClient) -> Session:
        if not self.session.token:
            await self.login(client)
        return self.session

    async def login(self, client: httpx.AsyncClient) -> Session:
        identifiant = self._identifiant_provider()
        password = self._password_provider(identifiant)
        body = encode_form_data({"identifiant": identifiant, "motdepasse": password, "codeSecure": ""})
        try:
            resp = await client.post(
                f"{SETTINGS.api_base}login.awp",
                content=body,
                headers={"Content-Type": "application/x-www-form-urlencoded",
                         "User-Agent": SETTINGS.user_agent},
            )
        except httpx.HTTPError as exc:
            raise AuthError(f"Échec réseau pendant le login : {type(exc).__name__}") from exc
        if resp.status_code != 200:
            raise AuthError(f"Login refusé (HTTP {resp.status_code}).")
        try:
            payload = resp.json()
        except ValueError as exc:
            raise AuthError("Réponse de login non JSON.") from exc

        code = payload.get("code")
        if code == 202:
            raise AuthError(
                "Le login demande un code 3DSecure (paramètre Sites/Admin/3DSecure/Actif activé). "
                "Non géré par ce prototype — voir docs/cartographie-api-admin.md §3."
            )
        if code == 505:
            raise AuthError("Identifiant ou mot de passe admin invalide (code 505).")
        if code != 200 or not payload.get("token"):
            # Ne jamais inclure le corps (peut contenir des infos de compte).
            raise AuthError(f"Login refusé par EcoleDirecte (code {code}).")
        data = payload.get("data") or {}
        if not data.get("etablissements"):
            raise AuthError("Aucun établissement disponible pour ce compte admin.")

        self.session = Session(token=payload["token"], user=data)
        self.store.save(self.session)
        return self.session


# ----------------------------------------------------------------------
# CLI : setup (Trousseau) / check (login réel) / logout
# ----------------------------------------------------------------------
def _setup() -> None:
    identifiant = input("Identifiant admin EcoleDirecte : ").strip()
    if not identifiant:
        raise SystemExit("Identifiant vide.")
    SETTINGS.home_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(SETTINGS.home_dir, stat.S_IRWXU)
    SETTINGS.config_path.write_text(json.dumps({"identifiant": identifiant}))
    print("Le Trousseau va te demander le mot de passe (saisie masquée, jamais affichée).")
    # Sans valeur après -w, `security` demande le mot de passe lui-même sur le TTY :
    # il ne transite ni par argv ni par ce process Python.
    rc = subprocess.call(
        ["security", "add-generic-password", "-U", "-s", SETTINGS.keychain_service,
         "-a", identifiant, "-l", "EcoleDirecte admin (MCP)", "-w"]
    )
    if rc != 0:
        raise SystemExit(f"Échec de l'enregistrement dans le Trousseau (code {rc}).")
    SessionStore().clear()
    print(f"OK — identifiant dans {SETTINGS.config_path}, mot de passe dans le Trousseau.")


async def _check() -> None:
    auth = AdminAuth()
    auth.invalidate()
    async with httpx.AsyncClient(timeout=SETTINGS.timeout_seconds) as client:
        session = await auth.login(client)
    etabs = ", ".join(f"{e.get('libelle')} ({e.get('RNE') or e.get('code')})"
                      for e in session.user.get("etablissements", []))
    print(f"Login OK — codeOgec {session.code_ogec} — établissement(s) : {etabs}")


def _cli() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "setup":
        _setup()
    elif cmd == "check":
        import asyncio
        asyncio.run(_check())
    elif cmd == "logout":
        SessionStore().clear()
        print("Session locale supprimée.")
    else:
        print("Usage : python -m ecoledirecte_admin_mcp.auth [setup|check|logout]", file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    _cli()

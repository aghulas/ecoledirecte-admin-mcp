"""Client HTTP vers l'API admin EcoleDirecte (v3/admin), en LECTURE SEULE.

Protocole (confirmé le 15/09/2026, voir docs/cartographie-api-admin.md §2) :
  POST https://api.ecoledirecte.com/v3/admin/<chemin>.awp?verbe=get&<query>
  headers : Content-Type: application/x-www-form-urlencoded, x-token: <token>
  corps   : data={"token": "<token>", ...paramètres...}
  réponse : {"code": 200, "token": "<nouveau token>", "host": "HTTPxxx", "data": {...}}

Garde-fous appliqués AU NIVEAU DU CLIENT (pas seulement par absence d'outil) :
  1. Seul `verbe=get` est autorisé — aucune écriture possible via ce client.
  2. Liste d'endpoints interdits même en GET, car ils renvoient des secrets
     d'authentification d'autres utilisateurs ou ouvrent une session à leur place :
       - compteOrigineED/<type>/<id>  → identifiant + mot de passe de 1re connexion
       - supervisionmobile             → identifiant + mot de passe « supervision mobile »
       - supervision                   → ouvre l'espace ED d'une famille/élève (usurpation)
       - loginsED, blockingState, logins/, loginCreation, reinitLogin → gestion des comptes
       - banques                       → coordonnées bancaires de l'établissement
       - televersement, telechargement → fichiers
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any
from urllib.parse import urlencode

import httpx
from mcp.server.mcpserver.exceptions import ToolError

from .auth import AUTH_EXPIRED_CODES, AdminAuth, AuthError, encode_form_data
from .config import SETTINGS

_FORBIDDEN_PATH_PREFIXES: tuple[str, ...] = (
    "compteorigineed",
    "supervisionmobile",
    "supervision",
    "loginsed",
    "blockingstate",
    "logins",
    "logincreation",
    "reinitlogin",
    "login",
    "banques",
    "televersement",
    "telechargement",
    "purgerent",
    "migrationpaiement",
)

_ALLOWED_TYPES_UTILISATEURS = ("familles", "eleves", "professeurs", "personnels", "entreprises")


class ForbiddenEndpointError(ToolError):
    """Levée si du code tente d'atteindre un endpoint explicitement exclu."""


class EcoleDirecteApiError(ToolError):
    """Erreur renvoyée par l'API admin."""


def check_allowed(path: str, verbe: str) -> None:
    if verbe.lower() != "get":
        raise ForbiddenEndpointError(
            f"Verbe '{verbe}' refusé : ce connecteur est strictement en lecture seule."
        )
    first_segment = path.strip("/").split("/", 1)[0].split("?", 1)[0].lower()
    if first_segment in _FORBIDDEN_PATH_PREFIXES:
        raise ForbiddenEndpointError(
            f"Endpoint explicitement exclu du connecteur : '{path}' "
            "(secrets d'authentification, usurpation de session ou données bancaires)."
        )


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


_SECRET_RE = re.compile(
    r"(?<![a-z])clef?(?![a-z])|(?<![a-z])cle(?=[a-z_])|certificat|secret|password|motdepasse|"
    r"mot de passe|(?<![a-z])mdp|token|apikey|api_key|iban|(?<![a-z])bic(?![a-z])|pspid"
)


def is_secret_param(libelle: str) -> bool:
    return bool(_SECRET_RE.search(_normalize(libelle)))


def redact_parametres(parametres: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for p in parametres:
        if isinstance(p, dict) and is_secret_param(str(p.get("libelle", ""))) and p.get("valeur") not in (None, ""):
            p = {**p, "valeur": "<masqué>"}
        out.append(p)
    return out


def redact_user(user: dict[str, Any], include_sensitive: bool = False) -> dict[str, Any]:
    if include_sensitive:
        return user
    return {k: v for k, v in user.items() if k not in SETTINGS.sensitive_user_fields}


class EcoleDirecteAdminClient:
    def __init__(self, auth: AdminAuth | None = None, http: httpx.AsyncClient | None = None):
        self._auth = auth or AdminAuth()
        self._http = http or httpx.AsyncClient(timeout=SETTINGS.timeout_seconds)

    @property
    def auth(self) -> AdminAuth:
        return self._auth

    async def aclose(self) -> None:
        await self._http.aclose()

    async def get(self, path: str, query: dict[str, Any] | None = None,
                  data: dict[str, Any] | None = None) -> Any:
        """Appel GET (verbe=get). Re-login automatique une fois si session expirée."""
        check_allowed(path, "get")
        for attempt in (1, 2):
            session = await self._auth.ensure_session(self._http)
            payload = await self._post_raw(path, query, data, session.token)
            code = payload.get("code")
            self._auth.update_token(payload.get("token"))
            if code in AUTH_EXPIRED_CODES and attempt == 1:
                self._auth.invalidate()
                continue
            if code in AUTH_EXPIRED_CODES:
                raise AuthError(f"Session refusée après re-login (code {code}).")
            if code == 403:
                raise EcoleDirecteApiError(f"GET {path} : accès refusé (403) pour ce compte admin.")
            if code != 200:
                raise EcoleDirecteApiError(
                    f"GET {path} : code {code} — {payload.get('message') or 'pas de message'}"
                )
            return payload.get("data")
        raise AssertionError("unreachable")

    async def _post_raw(self, path: str, query: dict[str, Any] | None,
                        data: dict[str, Any] | None, token: str) -> dict[str, Any]:
        qs = "verbe=get&" + urlencode({k: v for k, v in (query or {}).items() if v is not None})
        url = f"{SETTINGS.api_base}{path.strip('/')}.awp?{qs}"
        body = encode_form_data({**(data or {}), "token": token})
        try:
            resp = await self._http.post(
                url, content=body,
                headers={"Content-Type": "application/x-www-form-urlencoded",
                         "Accept": "application/json, text/plain, */*",
                         "x-token": token, "User-Agent": SETTINGS.user_agent},
            )
        except httpx.HTTPError as exc:
            raise EcoleDirecteApiError(f"GET {path} : erreur réseau {type(exc).__name__}") from exc
        if resp.status_code != 200:
            raise EcoleDirecteApiError(f"GET {path} : HTTP {resp.status_code}")
        try:
            payload = resp.json()
        except ValueError as exc:
            raise EcoleDirecteApiError(f"GET {path} : réponse non JSON") from exc
        if not isinstance(payload, dict):
            raise EcoleDirecteApiError(f"GET {path} : enveloppe inattendue ({type(payload).__name__})")
        return payload

    # ------------------------------------------------------------------
    # Méthodes métier (schémas confirmés sur données réelles le 15/09/2026)
    # ------------------------------------------------------------------
    async def session_info(self) -> dict[str, Any]:
        session = await self._auth.ensure_session(self._http)
        user = session.user
        return {
            "codeOgec": user.get("codeOgec"),
            "type": user.get("type"),
            "etablissements": [
                {k: v for k, v in e.items() if not k.startswith("$$")}
                for e in user.get("etablissements", [])
            ],
            "parametragesRNE": user.get("parametragesRNE"),
            "isModeRestreint": user.get("isModeRestreint"),
            "parametrageMultiEtab": user.get("parametrageMultiEtab"),
        }

    async def list_classes(self) -> Any:
        """Arborescence établissement → niveaux → classes {id, code, libelle, idGroupe}."""
        return await self.get("classes")

    async def list_utilisateurs(self, type_utilisateurs: str, filtre: str = "") -> list[dict[str, Any]]:
        """Annuaire des comptes EcoleDirecte d'un type donné.

        familles : {id, civilite, nom, prenom, type (responsable|conjoint), profil,
                    otp, dejaConnecte, dateModifMdp, nbJourDerniereModifMdp,
                    enfants[{nom, prenom, idClasse, libelleClasse}], badge, photo}
        eleves   : mêmes champs + idClasse, libelleClasse (sans enfants)
        professeurs / personnels : sans enfants ni classe.
        Pour familles/eleves/entreprises, le front exige ≥ 2 caractères de filtre.
        """
        if type_utilisateurs not in _ALLOWED_TYPES_UTILISATEURS:
            raise ToolError(f"type_utilisateurs doit être parmi {_ALLOWED_TYPES_UTILISATEURS}")
        data = await self.get(f"utilisateurs/{type_utilisateurs}", {"filterSearch": filtre})
        if not isinstance(data, dict) or not isinstance(data.get("utilisateurs"), list):
            raise EcoleDirecteApiError(
                f"utilisateurs/{type_utilisateurs} : format inattendu — refus de renvoyer "
                "un résultat potentiellement non redacté."
            )
        return data["utilisateurs"]

    async def get_parametres(self, libelles: list[str]) -> list[dict[str, Any]]:
        """Valeurs de paramètres établissement par libellé exact (ex.
        'Sites/Familles/Notes/Etablissement_0/Notes/Actif'). Valeurs secrètes masquées."""
        data = await self.get("parametres", data={"parametres": [{"libelle": l} for l in libelles]})
        params = (data or {}).get("parametres", []) if isinstance(data, dict) else []
        return redact_parametres(params)

    async def stats(self, site: str = "ecoledirecte") -> Any:
        """Statistiques de connexion par profil, mois, jour (écran Statistiques)."""
        return await self.get(f"stats/{site}")

    async def synchros(self) -> Any:
        """État des derniers transferts Charlemagne → EcoleDirecte par module."""
        session = await self._auth.ensure_session(self._http)
        if not session.code_ogec:
            raise EcoleDirecteApiError("codeOgec inconnu dans la session.")
        return await self.get(f"synchrosED/{session.code_ogec}")

    async def list_connecteurs(self) -> Any:
        return await self.get("connecteurs")

    async def list_activites(self, type_user: str = "familles") -> Any:
        """Activités de suivi (cantine, étude…) paramétrées pour un type d'utilisateur."""
        return await self.get(f"activites/{type_user}")

    async def list_portes_monnaie(self, type_user: str = "commun") -> Any:
        return await self.get(f"portesMonnaie/{type_user}")

    async def list_types_sanction(self) -> Any:
        return await self.get("carnetCorrespondance/typesSanction")

    async def list_categories_suivi(self) -> Any:
        return await self.get("carnetCorrespondance/categoriesSuivi")

    async def list_cahier_textes_tags(self) -> Any:
        return await self.get("cahierDeTexte/tags")

    async def list_salles(self) -> Any:
        return await self.get("salles")

    async def list_lsu_competences_numeriques(self) -> Any:
        return await self.get("LSU/CompNumeriques/classes")

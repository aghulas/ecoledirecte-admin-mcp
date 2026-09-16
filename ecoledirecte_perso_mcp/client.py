"""Client HTTP vers l'espace personnel EcoleDirecte (apip/v3), LECTURE SEULE.

Protocole (docs/cartographie-api-personnel.md §2) :
  POST https://apip.ecoledirecte.com/v3/<chemin>.awp?verbe=get&v=<ver>&<params>
  headers : Content-Type x-www-form-urlencoded, X-Token, Accept json
  corps   : data=<JSON>
  réponse : {code, token, data} ; le X-Token TOURNE (dernier reçu à réutiliser).

Garde-fous (au niveau du client) :
  1. `verbe=get` uniquement — aucune écriture possible.
  2. Ouvrir un message précis le marque « lu » chez le destinataire → tout chemin
     `messages/<id>` (message unique) est BLOQUÉ. Seule la LISTE est autorisée.
  3. Endpoints d'action (marquerLu, corbeille, deplacer, etc.) bloqués.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlencode

import httpx
from mcp.server.mcpserver.exceptions import ToolError

from .auth import AUTH_EXPIRED_CODES, AuthError, PersoAuth, encode_form_data
from .config import SETTINGS

# Mot-clé de type de compte utilisé dans les chemins « pluriels » (ex. personnels/18).
_TYPE_WORD = {"A": "personnels", "E": "eleves", "P": "professeurs", "1": "familles"}

# Un chemin `.../messages/<id>` (message unique) marque le message lu → interdit.
_SINGLE_MESSAGE_RE = re.compile(r"messages/\d+")
# Fragments d'action de messagerie / écriture, bloqués même en apparence GET.
_FORBIDDEN_FRAGMENTS = ("marquer", "corbeille", "deplacer", "brouillon", "envoi", "supprim")


class ForbiddenEndpointError(ToolError):
    """Levée si du code vise un endpoint exclu (message unique, action, écriture)."""


class EcoleDirectePersoApiError(ToolError):
    """Erreur renvoyée par l'API espace personnel."""


def check_allowed(path: str, verbe: str) -> None:
    if verbe.lower() != "get":
        raise ForbiddenEndpointError(
            f"Verbe '{verbe}' refusé : connecteur strictement en lecture seule."
        )
    low = path.lower()
    if _SINGLE_MESSAGE_RE.search(low):
        raise ForbiddenEndpointError(
            f"Ouverture d'un message unique ('{path}') interdite : marquerait le "
            "message comme lu chez le destinataire. Seule la liste est autorisée."
        )
    for frag in _FORBIDDEN_FRAGMENTS:
        if frag in low:
            raise ForbiddenEndpointError(f"Endpoint d'action/écriture exclu : '{path}'.")


class EcoleDirectePersoClient:
    def __init__(self, auth: PersoAuth | None = None, http: httpx.AsyncClient | None = None):
        self._auth = auth or PersoAuth()
        self._http = http or httpx.AsyncClient(timeout=SETTINGS.timeout_seconds)

    @property
    def auth(self) -> PersoAuth:
        return self._auth

    async def aclose(self) -> None:
        await self._http.aclose()

    def _word(self) -> str:
        tc = self._auth.session.type_compte or "A"
        return _TYPE_WORD.get(tc, "personnels")

    def _account_id(self) -> str:
        aid = self._auth.session.account_id
        if not aid:
            raise EcoleDirectePersoApiError("Aucun compte en session (relance `login`).")
        return aid

    async def get(self, path: str, query: dict[str, Any] | None = None,
                  data: dict[str, Any] | None = None) -> Any:
        check_allowed(path, "get")
        for attempt in (1, 2):
            session = await self._auth.ensure_session(self._http)
            payload = await self._post_raw(path, query, data, session.token)
            code = payload.get("code")
            self._auth.update_token(payload.get("token"))
            if code in AUTH_EXPIRED_CODES and attempt == 1:
                self._auth.invalidate_token()
                continue
            if code in AUTH_EXPIRED_CODES:
                raise AuthError(f"Session refusée après re-login (code {code}).")
            if code == 403:
                raise EcoleDirectePersoApiError(f"GET {path} : accès refusé (403) pour ce compte.")
            if code != 200:
                raise EcoleDirectePersoApiError(
                    f"GET {path} : code {code} — {payload.get('message') or 'sans message'}"
                )
            return payload.get("data")
        raise AssertionError("unreachable")

    async def _post_raw(self, path: str, query, data, token: str) -> dict[str, Any]:
        params = {"verbe": "get", "v": SETTINGS.api_version}
        params.update({k: v for k, v in (query or {}).items() if v is not None})
        url = f"{SETTINGS.data_base}/{path.strip('/')}.awp?{urlencode(params)}"
        body = encode_form_data(data or {})
        try:
            resp = await self._http.post(
                url, content=body,
                headers={"Content-Type": "application/x-www-form-urlencoded",
                         "Accept": "application/json", "X-Token": token,
                         "User-Agent": SETTINGS.user_agent},
            )
        except httpx.HTTPError as exc:
            raise EcoleDirectePersoApiError(f"GET {path} : réseau {type(exc).__name__}") from exc
        if resp.status_code != 200:
            raise EcoleDirectePersoApiError(f"GET {path} : HTTP {resp.status_code}")
        try:
            payload = resp.json()
        except ValueError as exc:
            raise EcoleDirectePersoApiError(f"GET {path} : réponse non JSON") from exc
        if not isinstance(payload, dict):
            raise EcoleDirectePersoApiError(f"GET {path} : enveloppe inattendue")
        return payload

    # ------------------------------------------------------------------
    # Méthodes métier (endpoints relevés le 16/09/2026)
    # ------------------------------------------------------------------
    async def session_info(self) -> dict[str, Any]:
        session = await self._auth.ensure_session(self._http)
        return {"id": session.account_id, "typeCompte": session.type_compte,
                "nom": session.account.get("nom"), "prenom": session.account.get("prenom"),
                "doubleAuthMemorisee": bool(session.cn)}

    async def list_messages(self, *, boite: str = "received", id_classeur: int = 0,
                            page: int = 0, items: int = 100, only_read: str = "",
                            query: str = "") -> Any:
        """Liste la messagerie (NE marque rien lu). `boite` = received|sent|archived."""
        aid = self._account_id()
        params = {"force": "false", "typeRecuperation": boite, "idClasseur": id_classeur,
                  "orderBy": "date", "order": "desc", "query": query, "onlyRead": only_read,
                  "page": page, "itemsPerPage": items, "getAll": 0}
        return await self.get(f"{self._word()}/{aid}/messages", params,
                              {"anneeMessages": SETTINGS.annee})

    async def agenda_evenements(self) -> Any:
        return await self.get(f"{self._word()}/{self._account_id()}/agendaEvenements")

    async def carnet_badges_non_lus(self) -> Any:
        return await self.get("carnetCorrespondance/badgesNonLues")

    async def sessions_rdv(self) -> Any:
        return await self.get(f"{self._auth.session.type_compte}/{self._account_id()}/sessionsRdv")

    async def rdv_individuels(self) -> Any:
        return await self.get(f"{self._auth.session.type_compte}/{self._account_id()}/rdvi")

    async def documents(self, archive: str = "") -> Any:
        return await self.get("adultesDocuments", {"archive": archive, "listesPieces": 1})

    async def postits(self) -> Any:
        return await self.get(f"{self._auth.session.type_compte}/{self._account_id()}/postits",
                              {"administrable": "o"})

    async def niveaux(self) -> Any:
        return await self.get("niveauxListe")

    async def classe_eleves(self, id_classe: str, include_sensitive_fields: bool = False) -> Any:
        """Élèves d'une classe. Schéma réel (16/09/2026) : {entity:{...}, eleves:[{
        id, nom, prenom, sexe, dateNaissance, email, portable, regime, numeroBadge,
        dateEntree, dateSortie, dispense, dispositifs, photo, classeId, classeLibelle,
        responsables:[{id, civilite, nom, prenom, role}]}]}.
        ATTENTION : les responsables n'ont PAS de coordonnées ici (ni mail ni tél)."""
        data = await self.get(f"classes/{id_classe}/eleves")
        if include_sensitive_fields or not isinstance(data, dict):
            return data
        eleves = data.get("eleves")
        if not isinstance(eleves, list):
            raise EcoleDirectePersoApiError(
                "classes/{id}/eleves : format inattendu — refus de renvoyer un "
                "résultat potentiellement non redacté."
            )
        return {**data, "eleves": [
            {k: v for k, v in e.items() if k not in SETTINGS.sensitive_eleve_fields}
            if isinstance(e, dict) else e for e in eleves
        ]}

    async def eleve_coordonnees_famille(self, id_eleve: str, include_sensitive_fields: bool = False) -> Any:
        """Coordonnées des responsables familiaux d'un élève. Schéma réel (16/09/2026) :
        liste de {adresseLigne1, adresseLigne2, adresseLigne3, codePostal, ville, typeLien,
        typeLienLibelle, responsable{civilite, nom, nomSimple, prenom, codePays, telDomicile,
        telTravail, telMobile, mailTravail, mailPerso, profession, societe, csp{code,libelle}},
        conjoint{...même forme, si applicable...}}.
        `profession`/`societe`/`csp` retirés par défaut (hors périmètre "coordonnées")."""
        data = await self.get(f"eleves/{id_eleve}/coordonneesfamille")
        if include_sensitive_fields:
            return data
        if not isinstance(data, list):
            raise EcoleDirectePersoApiError(
                "eleves/{id}/coordonneesfamille : format inattendu — refus de renvoyer "
                "un résultat potentiellement non rédacté."
            )
        def _redact_person(p: Any) -> Any:
            if not isinstance(p, dict):
                return p
            return {k: v for k, v in p.items() if k not in SETTINGS.sensitive_famille_fields}
        out = []
        for entry in data:
            if not isinstance(entry, dict):
                out.append(entry)
                continue
            new_entry = dict(entry)
            if "responsable" in new_entry:
                new_entry["responsable"] = _redact_person(new_entry["responsable"])
            if "conjoint" in new_entry:
                new_entry["conjoint"] = _redact_person(new_entry["conjoint"])
            out.append(new_entry)
        return out

    async def professeurs(self) -> Any:
        return await self.get("utilisateurs/professeurs")

    async def salles(self) -> Any:
        return await self.get("salles")

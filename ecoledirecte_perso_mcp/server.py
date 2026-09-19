"""Serveur MCP EcoleDirecte — espace personnel (compte secrétariat), lecture seule.

Complète le serveur admin : ici on lit ce que voit un compte personnel sur
www.ecoledirecte.com — messagerie (liste seule), agenda, rendez-vous, cahier de
liaison, documents, post-it, la CONSULTATION des élèves par classe (fiches
élèves : email/portable de l'élève, régime, dispositifs, responsables sans
coordonnées à ce niveau), et les coordonnées détaillées d'un élève
(ed_perso_eleve_coordonnees_famille : adresse/téléphones/emails des
responsables — données absentes de l'API admin). Voir
docs/cartographie-api-personnel.md.

Aucune écriture. Aucun outil n'ouvre un message individuel (cela le marquerait
« lu » chez le destinataire) — bloqué au niveau du client.
"""
from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from .client import EcoleDirectePersoClient

mcp = MCPServer(
    name="ecoledirecte-perso",
    title="EcoleDirecte espace personnel (prototype non officiel)",
    instructions=(
        "Accès en LECTURE SEULE à l'espace personnel EcoleDirecte d'un compte "
        "personnel (secrétariat) de votre établissement, via l'API interne du site "
        "www.ecoledirecte.com. Sert à consulter les fiches élèves par classe et "
        "l'activité de communication. Données personnelles : n'extraire "
        "que ce qui est nécessaire. Ne jamais ouvrir un message individuel."
    ),
)

_client: EcoleDirectePersoClient | None = None


def _get_client() -> EcoleDirectePersoClient:
    global _client
    if _client is None:
        _client = EcoleDirectePersoClient()
    return _client


@mcp.tool()
async def ed_perso_session_info() -> Any:
    """Compte personnel connecté : id, type de compte, nom, et si la double
    authentification est mémorisée. Utile pour vérifier la connexion."""
    return await _get_client().session_info()


@mcp.tool()
async def ed_perso_classe_eleves(id_classe: str, include_sensitive_fields: bool = False) -> Any:
    """Élèves d'une classe : nom, prénom, sexe, régime, dates d'entrée/sortie,
    dispenses/dispositifs, `email` et `portable` DE L'ÉLÈVE, et la liste des
    responsables (civilité, nom, prénom, rôle). `id_classe` = identifiant interne
    de la classe, le même que côté serveur admin (ex. '8' pour CM2 B).

    ⚠️ Les responsables n'ont PAS de coordonnées ici (ni email ni téléphone) —
    l'API ne les expose pas sur cette route.
    `dateNaissance`, `numeroBadge` et `photo` sont retirés sauf
    include_sensitive_fields=True."""
    return await _get_client().classe_eleves(id_classe, include_sensitive_fields)


@mcp.tool()
async def ed_perso_niveaux_list() -> Any:
    """Référentiel des niveaux/classes visibles par le compte (pour retrouver les
    identifiants de classe à passer à ed_perso_classe_eleves)."""
    return await _get_client().niveaux()


@mcp.tool()
async def ed_perso_eleve_coordonnees_famille(id_eleve: str, include_sensitive_fields: bool = False) -> Any:
    """Coordonnées des responsables familiaux d'un élève : adresse postale, téléphones
    (domicile/travail/mobile) et emails (perso/travail) de chaque responsable, et de son
    conjoint le cas échéant. `id_eleve` = identifiant interne de l'élève (le champ `id`
    renvoyé par ed_perso_classe_eleves).

    ⚠️ Données personnelles directement identifiantes sur des tiers (parents/responsables) —
    à utiliser uniquement pour un besoin de contact légitime (ex. activation de compte,
    urgence), pas pour de la collecte systématique.
    `profession`, `societe` et la catégorie socio-professionnelle (`csp`) sont retirés
    par défaut (hors périmètre "coordonnées"), surchargeable avec
    include_sensitive_fields=True."""
    return await _get_client().eleve_coordonnees_famille(id_eleve, include_sensitive_fields)


@mcp.tool()
async def ed_perso_professeurs_list() -> Any:
    """Annuaire des enseignants (vue Consultation)."""
    return await _get_client().professeurs()


@mcp.tool()
async def ed_perso_messages_list(
    boite: str = "received", page: int = 0, items: int = 100, only_read: str = ""
) -> Any:
    """Liste des messages de la messagerie (⚠️ liste seulement — n'ouvre aucun
    message, donc ne marque rien comme « lu »). `boite` = 'received', 'sent' ou
    'archived'. Renvoie les en-têtes (expéditeur, sujet, date, lu/non lu), pas le
    corps des messages."""
    if boite not in ("received", "sent", "archived"):
        raise ToolError("boite doit être 'received', 'sent' ou 'archived'.")
    return await _get_client().list_messages(boite=boite, page=page, items=items, only_read=only_read)


@mcp.tool()
async def ed_perso_agenda() -> Any:
    """Événements de l'agenda du compte."""
    return await _get_client().agenda_evenements()


@mcp.tool()
async def ed_perso_carnet_liaison_non_lus() -> Any:
    """Compteurs de badges non lus du cahier de liaison / carnet de correspondance,
    par classe, groupe et élève."""
    return await _get_client().carnet_badges_non_lus()


@mcp.tool()
async def ed_perso_rendez_vous() -> Any:
    """Rendez-vous : sessions de RDV et rendez-vous individuels du compte."""
    c = _get_client()
    return {"sessions": await c.sessions_rdv(), "individuels": await c.rdv_individuels()}


@mcp.tool()
async def ed_perso_documents(archive: str = "") -> Any:
    """Documents de l'établissement accessibles au compte adulte (et pièces à
    verser). `archive` non vide pour inclure les archives."""
    return await _get_client().documents(archive=archive)


@mcp.tool()
async def ed_perso_postits() -> Any:
    """Post-it / tableau d'affichage administrable par le compte."""
    return await _get_client().postits()

"""Serveur MCP EcoleDirecte — espace personnel (compte de l'utilisateur).

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

from .messagerie_ecriture import modifier_brouillon, preparer_message, rechercher_contacts, supprimer_brouillon
from .client import EcoleDirectePersoClient

mcp = MCPServer(
    name="ecoledirecte-perso",
    title="EcoleDirecte espace personnel (prototype non officiel)",
    instructions=(
        "Accès en LECTURE SEULE à l'espace personnel EcoleDirecte d'un compte "
        "personnel de l'établissement (celui de l'utilisateur), via l'API interne du site "
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
    boite: str = "received", page: int = 0, items: int = 100, only_read: str = "",
    recherche: str = ""
) -> Any:
    """Liste des messages de la messagerie (⚠️ liste seulement — n'ouvre aucun
    message, donc ne marque rien comme « lu »). `boite` = 'received', 'sent',
    'archived' ou 'draft' (brouillons). `recherche` = texte cherché (objet,
    correspondant). Renvoie les en-têtes (id, expéditeur, sujet, date, lu/non lu),
    pas le corps : pour le lire, ed_perso_message_lire."""
    if boite not in ("received", "sent", "archived", "draft"):
        raise ToolError("boite doit être 'received', 'sent', 'archived' ou 'draft'.")
    return await _get_client().list_messages(boite=boite, page=page, items=items, only_read=only_read,
                                             query=recherche)


@mcp.tool()
async def ed_perso_message_lire(id_message: int, boite: str = "received",
                                remettre_non_lu: bool = True) -> Any:
    """Ouvre UN message de la messagerie du compte et renvoie son contenu (objet,
    expéditeur, destinataires, date, texte, pièces jointes listées).
    ⚠️ À n'appeler QUE si l'utilisateur demande explicitement de lire CE message
    (id obtenu par ed_perso_messages_list) : l'ouverture d'un message reçu non lu
    le marque « lu ». Par défaut (`remettre_non_lu=True`), il est aussitôt remis en
    « non lu » s'il l'était avant. `boite` = dossier du message ('received',
    'sent', 'archived', 'draft')."""
    return await _get_client().lire_message(id_message, boite, remettre_non_lu)


@mcp.tool()
async def ed_perso_contacts_rechercher(type: str, nom: str = "") -> Any:
    """Annuaire de la messagerie (lecture) : destinataires possibles d'un message.
    `type` = 'famille' (recherche par NOM DE L'ÉLÈVE ; une ligne par parent, avec
    id_eleve et responsable '1' ou '2') ou 'personnel' (filtre sur le nom). Sert à
    choisir les destinataires de ed_perso_message_ecrire."""
    return await rechercher_contacts(_get_client(), type, nom)


@mcp.tool()
async def ed_perso_message_ecrire(sujet: str, texte: str, destinataires: list[dict[str, Any]],
                                  mode: str = "brouillon", confirm: bool = False,
                                  pieces_jointes: list[str] | None = None,
                                  plafond_destinataires: int | None = None) -> Any:
    """ÉCRITURE — prépare un message de la messagerie EcoleDirecte du compte connecté
    (compte personnel de l'utilisateur : il part sous son nom, brouillon dans sa boîte). `mode` = 'brouillon'
    (déposé dans les brouillons ; l'utilisateur relit et envoie lui-même depuis
    EcoleDirecte — à privilégier) ou 'envoi' (envoyé directement).

    `destinataires` = liste de {"type": "famille", "id_eleve": N, "responsable":
    "1"|"2"|"tous", "champ": "to"|"cc"|"cci"} ou {"type": "personnel", "id": N,
    "champ": …} (ids : ed_perso_contacts_rechercher). `texte` = texte brut
    (paragraphes séparés par une ligne vide), signature comprise.

    Sans confirm=True (par défaut) : SIMULATION — destinataires résolus, objet et
    texte affichés, rien n'est écrit. Il faut TOUJOURS montrer la simulation à
    l'utilisateur et obtenir son accord explicite avant confirm=True.
    `pieces_jointes` = chemins de fichiers locaux (pdf, png, jpg, docx ; 20 Mo et 5
    fichiers au plus ; sous ED_PERSO_PJ_RACINES, défaut ~/Charlemagne ; jamais de
    document bancaire), téléversés seulement à l'écriture. `plafond_destinataires`
    = relève le plafond pour un BROUILLON uniquement (jusqu'à 150) ; les parents en
    double (fratries) sont dédoublonnés.
    Garde-fous : ED_PERSO_MESSAGERIE_ACTIF=1 ; plafond ED_PERSO_MESSAGERIE_MAX_DEST
    (défaut 30) ; messagerie inactive refusée ; journal."""
    return await preparer_message(_get_client(), sujet, texte, destinataires, mode, confirm,
                                  pieces_jointes, plafond_destinataires)


@mcp.tool()
async def ed_perso_brouillon_modifier(id_message: int, sujet: str | None = None, texte: str | None = None,
                                      remplacements: list[dict[str, str]] | None = None,
                                      destinataires: list[dict[str, Any]] | None = None,
                                      confirm: bool = False) -> Any:
    """ÉCRITURE — modifie un BROUILLON existant de la boîte du compte connecté (id :
    ed_perso_messages_list boite='draft'), sans l'envoyer. `sujet` = nouvel objet ;
    `texte` = remplace tout le texte (texte brut, comme ed_perso_message_ecrire) ;
    OU `remplacements` = [{"ancien": "...", "nouveau": "..."}] : remplacements exacts
    dans le texte, mise en forme conservée (chaque « ancien » doit exister).
    Destinataires : conservés (to/cc/cci), retrouvés un par un dans l'annuaire — un
    destinataire introuvable bloque la modification ; ou remplacés par `destinataires`
    (même format que ed_perso_message_ecrire, 150 au plus). Pièces jointes conservées.
    Sans confirm=True : SIMULATION (objet avant/après, remplacements et nombre
    d'occurrences, destinataires, texte final) — la montrer et obtenir l'accord
    explicite avant confirm=True. Après écriture, relire avec ed_perso_message_lire
    (boite='draft') : nombre de destinataires et texte. Garde-fous :
    ED_PERSO_MESSAGERIE_ACTIF=1 ; refus si le message n'est pas un brouillon ; jamais
    d'envoi ; journal."""
    return await modifier_brouillon(_get_client(), id_message, sujet, texte, remplacements, confirm,
                                    destinataires)


@mcp.tool()
async def ed_perso_brouillon_supprimer(id_message: int, confirm: bool = False) -> Any:
    """ÉCRITURE — supprime UN brouillon de la boîte du compte connecté (id :
    ed_perso_messages_list boite='draft'). Refusé si le message n'est pas un
    brouillon (jamais un message reçu ou envoyé). Sans confirm=True : SIMULATION
    (objet, date, nombre de destinataires, début du texte) — la montrer et obtenir
    l'accord explicite avant confirm=True ; suppression définitive. Garde-fous :
    ED_PERSO_MESSAGERIE_ACTIF=1 ; un seul brouillon par appel ; journal."""
    return await supprimer_brouillon(_get_client(), id_message, confirm)


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

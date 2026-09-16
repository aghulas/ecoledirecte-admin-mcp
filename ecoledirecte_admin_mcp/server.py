"""Serveur MCP EcoleDirecte Admin (prototype, lecture seule).

Périmètre : ce que l'API v3/admin expose réellement (voir
docs/cartographie-api-admin.md) — annuaire des comptes (familles↔enfants↔classe,
élèves, professeurs, personnels, entreprises), structure des classes,
paramétrages établissement, statistiques de connexion, état des synchronisations
Charlemagne, référentiels (connecteurs, activités, sanctions, tags CDT...).

N'expose PAS : factures, notes, messages (absents de l'API admin), ni aucun
endpoint renvoyant identifiants/mots de passe d'utilisateurs ou ouvrant une
supervision (bloqués dans client.py). Aucun outil d'écriture.
"""
from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from .activation import compute_activation
from .client import EcoleDirecteAdminClient, redact_user

mcp = MCPServer(
    name="ecoledirecte-admin",
    title="EcoleDirecte Admin (prototype non officiel)",
    instructions=(
        "Accès en lecture seule à la console admin EcoleDirecte de l'école l'établissement "
        "([ville]) via l'API interne v3/admin, identifiée par analyse du front "
        "admin.ecoledirecte.com. Contient l'annuaire des comptes et les paramétrages, "
        "PAS les factures, notes ni messages. Les données familles/élèves sont "
        "personnelles : n'en extraire que ce qui est nécessaire à la demande."
    ),
)

_client: EcoleDirecteAdminClient | None = None


def _get_client() -> EcoleDirecteAdminClient:
    global _client
    if _client is None:
        _client = EcoleDirecteAdminClient()
    return _client


def _users(users: Any, include_sensitive_fields: bool) -> list[dict[str, Any]]:
    if not isinstance(users, list):
        raise ToolError("Liste d'utilisateurs attendue — refus de renvoyer un résultat non redacté.")
    return [redact_user(u, include_sensitive_fields) if isinstance(u, dict) else u for u in users]


def _min2(nom: str) -> str:
    nom = (nom or "").strip()
    if len(nom) < 2:
        raise ToolError("Renseigne au moins 2 caractères du nom (contrainte de l'API).")
    return nom


@mcp.tool()
async def ed_admin_session_info() -> Any:
    """Compte admin connecté : codeOgec, établissement(s) (RNE/UAI, libellé),
    année scolaire en cours, mode restreint. Utile pour vérifier la connexion."""
    return await _get_client().session_info()


@mcp.tool()
async def ed_admin_classes_list() -> Any:
    """Structure des classes : établissement → niveaux → classes {id, code, libelle}.
    Les `id` de classe correspondent au champ `idClasse` des élèves/enfants."""
    return await _get_client().list_classes()


@mcp.tool()
async def ed_admin_familles_search(nom: str, include_sensitive_fields: bool = False) -> Any:
    """Recherche des comptes famille (responsables et conjoints) par nom — au moins
    2 caractères, correspondance partielle. Chaque résultat : id, civilité, nom,
    prénom, type (responsable|conjoint), enfants [{nom, prénom, idClasse,
    libelleClasse}], dejaConnecte, otp, date de dernière modification du mot de passe.
    Pas d'email/téléphone/adresse (non exposés par l'API admin). `badge`/`photo`
    retirés sauf include_sensitive_fields=True."""
    users = await _get_client().list_utilisateurs("familles", _min2(nom))
    return _users(users, include_sensitive_fields)


@mcp.tool()
async def ed_admin_eleves_search(nom: str, include_sensitive_fields: bool = False) -> Any:
    """Recherche des comptes élèves par nom (≥ 2 caractères) : id, nom, prénom,
    idClasse, libelleClasse, dejaConnecte... `badge`/`photo` retirés par défaut."""
    users = await _get_client().list_utilisateurs("eleves", _min2(nom))
    return _users(users, include_sensitive_fields)


@mcp.tool()
async def ed_admin_professeurs_list(filtre: str = "", include_sensitive_fields: bool = False) -> Any:
    """Liste des comptes professeurs (filtre optionnel sur le nom)."""
    users = await _get_client().list_utilisateurs("professeurs", filtre)
    return _users(users, include_sensitive_fields)


@mcp.tool()
async def ed_admin_personnels_list(filtre: str = "", include_sensitive_fields: bool = False) -> Any:
    """Liste des comptes personnels (administratif, vie scolaire...), filtre optionnel."""
    users = await _get_client().list_utilisateurs("personnels", filtre)
    return _users(users, include_sensitive_fields)


@mcp.tool()
async def ed_admin_entreprises_search(nom: str, include_sensitive_fields: bool = False) -> Any:
    """Recherche des comptes entreprises/tuteurs de stage par nom (≥ 2 caractères)."""
    users = await _get_client().list_utilisateurs("entreprises", _min2(nom))
    return _users(users, include_sensitive_fields)


@mcp.tool()
async def ed_admin_parametres_get(libelles: list[str]) -> Any:
    """Valeurs de paramètres de l'établissement, par libellé exact. Exemples réels :
    'Sites/Familles/Notes/Etablissement_0/Notes/Actif', 'Sites/Familles/Comptabilité/Actif',
    'Messagerie/Actif', 'Messagerie/Etablissement_0/Prof-Fam', 'Sites/Admin/3DSecure/Actif'.
    Valeurs ('0'/'1' ou texte). Les paramètres ressemblant à des secrets (clés,
    certificats, mots de passe, IBAN...) sont masqués."""
    if not libelles:
        raise ToolError("Fournis au moins un libellé de paramètre.")
    return await _get_client().get_parametres(libelles)


@mcp.tool()
async def ed_admin_stats_connexions(site: str = "ecoledirecte") -> Any:
    """Statistiques de connexion au site EcoleDirecte par profil (Famille, Élève,
    Professeur, Personnel), par mois/jour/heure."""
    return await _get_client().stats(site)


@mcp.tool()
async def ed_admin_synchros_etat() -> Any:
    """État des derniers transferts Charlemagne → EcoleDirecte par module (Vie
    scolaire, Notes, Administratif, Comptabilité, Passage, Entreprise) : date et
    message. Utile pour vérifier que les données ED sont à jour."""
    return await _get_client().synchros()


@mcp.tool()
async def ed_admin_connecteurs_list(actifs_seulement: bool = True) -> Any:
    """Applications partenaires (« Mes Applis » / connecteurs) : libellé, code,
    description, activation établissement, données RGPD partagées. Par défaut
    uniquement celles activées pour l'établissement."""
    data = await _get_client().list_connecteurs()
    connecteurs = (data or {}).get("connecteurs", []) if isinstance(data, dict) else []
    keep = ("code", "libelle", "description", "isActifEtab", "isPremium", "isAppliTierce",
            "urlSiteConnecteur", "tabRGPD")
    rows = [{k: c.get(k) for k in keep} for c in connecteurs if isinstance(c, dict)]
    if actifs_seulement:
        rows = [r for r in rows if r.get("isActifEtab")]
    return rows


@mcp.tool()
async def ed_admin_activites_list(type_user: str = "familles") -> Any:
    """Activités de suivi paramétrées (ex. cantine, étude — matin/après-midi)
    pour un type d'utilisateur ('familles' confirmé)."""
    return await _get_client().list_activites(type_user)


@mcp.tool()
async def ed_admin_referentiels_get() -> Any:
    """Référentiels vie scolaire et pédagogie en un appel : types de sanction et
    catégories de suivi du carnet de correspondance, tags du cahier de textes,
    salles, porte-monnaie communs, classes LSU compétences numériques."""
    c = _get_client()
    return {
        "typesSanction": await c.list_types_sanction(),
        "categoriesSuivi": await c.list_categories_suivi(),
        "cahierDeTexteTags": await c.list_cahier_textes_tags(),
        "salles": await c.list_salles(),
        "portesMonnaieCommun": await c.list_portes_monnaie("commun"),
        "lsuCompetencesNumeriques": await c.list_lsu_competences_numeriques(),
    }


@mcp.tool()
async def ed_admin_activation_comptes(classe: str | None = None, inclure_noms: bool | None = None) -> Any:
    """Suivi de l'activation des comptes EcoleDirecte, par classe : nombre d'élèves,
    comptes responsables rattachés, combien se sont déjà connectés, élèves dont
    AUCUN parent ne s'est encore connecté, élèves sans compte responsable, et taux
    d'activation. Couvre tout l'annuaire (2 appels API).

    - `classe` : libellé ('CM2 B', 'PS/MS'...) ou idClasse ; vide = toutes les classes.
    - `inclure_noms` : ajoute les listes nominatives (responsables jamais connectés
      avec leurs enfants dans la classe, élèves sans parent connecté). Par défaut
      activé seulement si une classe est précisée, pour limiter les données
      personnelles renvoyées.
    """
    if inclure_noms is None:
        inclure_noms = bool(classe)
    c = _get_client()
    familles = await c.list_utilisateurs("familles", "")
    eleves = await c.list_utilisateurs("eleves", "")
    result = compute_activation(familles, eleves, classe=classe, inclure_noms=inclure_noms)
    if classe and not result["classes"]:
        raise ToolError(f"Classe '{classe}' introuvable (utilise ed_admin_classes_list).")
    return result

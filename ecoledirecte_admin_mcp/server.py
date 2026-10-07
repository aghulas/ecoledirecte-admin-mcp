"""Serveur MCP EcoleDirecte Admin (prototype, lecture seule).

Périmètre : ce que l'API v3/admin expose réellement (voir
docs/cartographie-api-admin.md) — annuaire des comptes (familles↔enfants↔classe,
élèves, professeurs, personnels, entreprises), structure des classes,
paramétrages établissement, statistiques de connexion, état des synchronisations
Charlemagne, référentiels (connecteurs, activités, sanctions, tags CDT...).

N'expose PAS : factures, notes, messages (absents de l'API admin), ni aucun
endpoint renvoyant identifiants/mots de passe d'utilisateurs ou ouvrant une
supervision (bloqués dans client.py).

EXCEPTIONS D'ÉCRITURE (explicites, voir aussi README) :
  - 16/09/2026 : `ed_admin_parametre_set` écrit UN paramètre établissement
    (voir sa docstring et client.py::set_parametre) ;
  - 23/09/2026 : `ed_admin_deposer_piece` dépose UN PDF dans une liste de pièces
    à verser, au nom de la famille, via la supervision (depot_pieces.py) ;
  - 30/09/2026 : demandes de modification (demandes.py) ;
  - 02/10/2026 : `ed_admin_connecteur_activer` (dés)active une application
    partenaire (paramètres « Sites/Connecteur/…/Actif », connecteurs.py),
    ED_ADMIN_CONNECTEURS_ACTIF=1.
SUPERVISION EN LECTURE (04/10/2026) : `ed_admin_emploi_du_temps` ouvre l'espace
d'un enseignant pour lire son emploi du temps (verbe=get uniquement, edt.py),
ED_ADMIN_EDT_ACTIF=1.
Tous les autres outils restent strictement lecture seule.
"""
from __future__ import annotations

import os
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from . import connecteurs as connecteurs_mod
from . import parametres_catalogue as catalogue
from .activation import compute_activation
from .client import EcoleDirecteAdminClient, redact_user
from .demandes import demande_activites, demande_coordonnees, demande_telephones
from .depot_pieces import deposer_piece, etat_pieces
from .documents import documents_ecole, documents_famille, telecharger_document
from .edt import emploi_du_temps_enseignant

mcp = MCPServer(
    name="ecoledirecte-admin",
    title="EcoleDirecte Admin (prototype non officiel)",
    instructions=(
        "Accès en lecture seule à la console admin EcoleDirecte de votre établissement "
        "via l'API interne v3/admin, identifiée par analyse du front "
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


def _libelles_inconnus(libelles: list[str]) -> list[dict[str, Any]]:
    return [{"libelle": l, "suggestions": catalogue.suggestions(l)}
            for l in libelles if not catalogue.est_connu(l)]


def _enrichir(valeurs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ajoute intitulé / menu / rubrique du catalogue, et décode les valeurs base64."""
    out = []
    for v in valeurs:
        fiche = catalogue.entree(str(v.get("libelle", ""))) if isinstance(v, dict) else None
        if fiche:
            v = {**v, "intitule": fiche["intitule"], "menu": fiche["menu"], "rubrique": fiche["rubrique"]}
            if fiche.get("base64") and v.get("valeur") not in (None, "", "<masqué>"):
                v["valeur_decodee"] = catalogue.decoder_base64(str(v["valeur"]))
        out.append(v)
    return out


@mcp.tool()
async def ed_admin_parametres_get(libelles: list[str], hors_catalogue: bool = False) -> Any:
    """Valeurs de paramètres de l'établissement, par libellé exact (ex.
    'Sites/Familles/Actif', 'Messagerie/Etablissement_0/Fam-Admin',
    'Sites/Familles/Documents/Etablissement_0/Administratifs'). Valeurs '0'/'1'
    ou texte, avec l'intitulé lisible, le menu et la rubrique de l'admin.

    ⚠️ L'API renvoie « 0 » SANS ERREUR pour un libellé qui n'existe pas : les
    libellés sont donc vérifiés contre le catalogue (~650 paramètres relevés dans
    le front admin, voir ed_admin_parametres_catalogue). Un libellé inconnu est
    refusé avec des suggestions (souvent un accent : 'Sites/Elèves/Actif').
    `hors_catalogue=True` force la lecture (valeur alors non fiable).
    Pour lire toute une rubrique d'un coup : ed_admin_parametrage_lire.
    Les paramètres ressemblant à des secrets sont masqués."""
    if not libelles:
        raise ToolError("Fournis au moins un libellé de paramètre.")
    inconnus = _libelles_inconnus(libelles)
    if inconnus and not hors_catalogue:
        raise ToolError(
            "Libellé(s) absent(s) du catalogue — l'API renverrait « 0 » sans erreur, "
            "valeur non fiable. Suggestions : "
            + "; ".join(f"{i['libelle']} → {', '.join(i['suggestions']) or 'aucune'}" for i in inconnus)
            + ". Voir ed_admin_parametres_catalogue, ou hors_catalogue=True pour forcer."
        )
    valeurs = _enrichir(await _get_client().get_parametres(libelles))
    if inconnus:
        noms = {i["libelle"] for i in inconnus}
        valeurs = [{**v, "hors_catalogue": True, "avertissement": "libellé inconnu : valeur non fiable"}
                   if v.get("libelle") in noms else v for v in valeurs]
    return valeurs


@mcp.tool()
async def ed_admin_parametres_catalogue(menu: str | None = None, rubrique: str | None = None,
                                        recherche: str | None = None) -> Any:
    """Catalogue des paramètres établissement (sans appel réseau) : libellé exact,
    intitulé lisible, menu et rubrique de l'admin, fiabilité, modifiable ou non.

    Sans filtre : sommaire (nombre de paramètres par menu et rubrique).
    `menu` : 'généraux', 'familles', 'élèves', 'professeurs', 'personnels',
    'entreprises' (ou nom complet « Paramétrages … ») ; `rubrique` : ex.
    'Messagerie', 'Accès sites', 'Documents', 'Vie scolaire' ; `recherche` :
    texte cherché dans le libellé ou l'intitulé (sans accents ni casse).

    `certain: false` = libellé construit dynamiquement par le front pour plusieurs
    profils ; il peut ne pas exister pour l'un d'eux. Catalogue régénérable avec
    tools/extraire_parametres.py si l'admin EcoleDirecte évolue."""
    if not (menu or rubrique or recherche):
        return {**catalogue.info_source(), "sommaire": catalogue.sommaire(),
                "aide": "Filtre par menu / rubrique / recherche pour obtenir les libellés."}
    entrees = catalogue.lister(menu, rubrique, recherche)
    if not entrees:
        raise ToolError("Aucun paramètre pour ce filtre. Appelle l'outil sans filtre pour voir le sommaire.")
    return {"nombre": len(entrees), "parametres": entrees}


@mcp.tool()
async def ed_admin_parametrage_lire(menu: str, rubrique: str | None = None,
                                    certains_seulement: bool = True) -> Any:
    """Lit d'un coup les valeurs actuelles de toute une rubrique (ou tout un menu)
    de l'admin, avec les intitulés — pour vérifier un paramétrage, par exemple
    section par section du support de formation Aplim.

    `menu` / `rubrique` : comme ed_admin_parametres_catalogue (ex. menu='généraux',
    rubrique='Messagerie'). `certains_seulement` (défaut True) écarte les libellés
    dont l'existence n'est pas certaine pour ce profil (voir le catalogue).
    Lecture seule ; secrets masqués ; valeurs base64 décodées."""
    entrees = catalogue.lister(menu, rubrique)
    if certains_seulement:
        entrees = [e for e in entrees if e["certain"]]
    if not entrees:
        raise ToolError("Aucun paramètre pour ce filtre (voir ed_admin_parametres_catalogue).")
    if len(entrees) > 300:
        raise ToolError(f"{len(entrees)} paramètres : précise une rubrique.")
    valeurs: list[dict[str, Any]] = []
    libelles = [e["libelle"] for e in entrees]
    for i in range(0, len(libelles), 100):
        valeurs += await _get_client().get_parametres(libelles[i:i + 100])
    groupes: dict[str, list[dict[str, Any]]] = {}
    for v in _enrichir(valeurs):
        cle = f"{v.get('menu')} › {v.get('rubrique')}"
        groupes.setdefault(cle, []).append(
            {k: v[k] for k in ("libelle", "intitule", "valeur", "valeur_decodee") if k in v})
    return {"nombre": len(valeurs), "rubriques": groupes,
            "note": "Valeur '0' ou vide = désactivé / non renseigné (ou valeur par défaut du front)."}


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
async def ed_admin_emploi_du_temps(enseignant: str, date_debut: str, date_fin: str | None = None) -> Any:
    """Emploi du temps d'un enseignant TEL QU'ECOLEDIRECTE L'AFFICHE, sur une période
    (date_fin optionnelle = 7 jours ; 31 jours maximum). `enseignant` = nom (sans
    accents ni casse) ou identifiant EcoleDirecte. Renvoie les cours (date, heures,
    matière, classe, salle, annulé/modifié), un comptage par jour et par classe, et
    le nombre de cours sans matière (matière inconnue d'EcoleDirecte : relancer le
    transfert du module Administratif depuis Charlemagne).

    Sert à vérifier un import d'emploi du temps Charlemagne après le transfert Vie
    scolaire. LECTURE SEULE via la supervision de l'espace enseignant
    (ED_ADMIN_EDT_ACTIF=1). L'emploi du temps ne se modifie pas dans EcoleDirecte :
    toute correction se fait dans Charlemagne Vie Scolaire."""
    return await emploi_du_temps_enseignant(_get_client(), enseignant, date_debut, date_fin)

async def _connecteurs_et_etat() -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """(réponse `connecteurs`, valeurs des paramètres d'activation, établissements)."""
    c = _get_client()
    data = await c.list_connecteurs()
    if not isinstance(data, dict):
        raise ToolError("Réponse inattendue de l'API (connecteurs).")
    etabs_info = [e for e in ((await c.session_info()) or {}).get("etablissements") or [] if isinstance(e, dict)]
    etabs = [int(e["id"]) for e in etabs_info if e.get("id") not in (None, 0)]
    cles: list[str] = []
    for conn in data.get("connecteurs") or []:
        cles += [k for k, _ in connecteurs_mod.cles_activation(conn, etabs)]
        if conn.get("isCASAuth") and conn.get("isActivationByEtab"):
            cles += [connecteurs_mod.cle(conn, "RNE", False, e) for e in etabs]
    valeurs: dict[str, Any] = {}
    for i in range(0, len(cles), 40):
        for v in await c.get_parametres(cles[i:i + 40]):
            valeurs[v.get("libelle")] = v.get("valeur")
    return data, valeurs, etabs_info


@mcp.tool()
async def ed_admin_connecteurs_list(actifs_seulement: bool = True, recherche: str | None = None,
                                    code: str | None = None) -> Any:
    """Applications partenaires (« Mes Applis » de l'admin) avec leur état RÉEL
    par public (Familles, Élèves, Enseignants, Personnels), lu dans les
    paramètres d'activation — le champ isActifEtab de l'API n'est pas fiable.
    Pour chaque appli : actif, état par public, activée par défaut par Aplim,
    niveaux visés et « adapte_ecole » (maternelle/élémentaire), premium,
    données personnelles transmises à l'éditeur par public, contraintes
    (clé d'API, CAS, activation par classe, paramètres complémentaires).

    - `actifs_seulement` (défaut True) : seulement les applis actives pour au
      moins un public ; False = tout le catalogue (87 applis).
    - `recherche` : filtre sur le libellé ou le code.
    - `code` : une appli précise, avec le détail (description, info
      administrateur, publics possibles, catégories, site, clés de paramètres).
    Lecture seule ; pour (dés)activer : ed_admin_connecteur_activer."""
    data, valeurs, etabs_info = await _connecteurs_et_etat()
    etabs = [int(e["id"]) for e in etabs_info if e.get("id") not in (None, 0)]
    cats = connecteurs_mod._labels_categories(data.get("categories") or [])
    rgpd = data.get("rgpd") or []
    conns = [x for x in data.get("connecteurs") or [] if isinstance(x, dict)]
    if code:
        conn = next((x for x in conns if str(x.get("code")).lower() == code.strip().lower()), None)
        if conn is None:
            raise ToolError(f"Appli de code {code!r} introuvable (voir ed_admin_connecteurs_list(actifs_seulement=False)).")
        return connecteurs_mod.ligne(conn, valeurs, etabs, cats, rgpd, detail=True)
    rows = [connecteurs_mod.ligne(x, valeurs, etabs, cats, rgpd) for x in conns]
    if recherche:
        r = recherche.strip().lower()
        rows = [x for x in rows if r in x["libelle"].lower() or r in str(x["code"]).lower()]
    if actifs_seulement:
        rows = [x for x in rows if x["actif"]]
    return {"nb": len(rows), "nb_actives_total": sum(1 for x in conns if connecteurs_mod.etat(x, valeurs, etabs)
                                                    and any(connecteurs_mod.etat(x, valeurs, etabs).values())),
            "applis": rows}


@mcp.tool()
async def ed_admin_connecteur_activer(code: str, actif: bool, publics: list[str] | None = None,
                                      confirm: bool = False) -> Any:
    """ÉCRITURE — active ou désactive une application partenaire (« Mes Applis »)
    pour tous ses publics ou certains (`publics` : Familles, Élèves, Enseignants,
    Personnels — ou F/E/P/A), exactement comme l'écran Connecteurs de l'admin :
    écriture des paramètres « …/Actif » (et du RNE pour une appli CAS).

    Sans confirm=True (par défaut) : SIMULATION — état avant/après par public et,
    pour une activation, les données personnelles qui seront transmises à
    l'éditeur. Il faut TOUJOURS obtenir l'accord explicite de l'utilisateur en
    conversation avant d'appeler avec confirm=True. Refuse : applis à écran
    spécifique (non universelles) ; activation d'une appli qui exige une clé
    d'API, une activation par classe ou des paramètres complémentaires (à faire
    dans l'admin). Désactivation toujours possible pour une appli universelle."""
    data, valeurs, etabs_info = await _connecteurs_et_etat()
    conn = next((x for x in data.get("connecteurs") or [] if str(x.get("code")).lower() == code.strip().lower()), None)
    if conn is None:
        raise ToolError(f"Appli de code {code!r} introuvable.")
    try:
        plan = connecteurs_mod.plan_activation(conn, valeurs, etabs_info, actif, publics, data.get("rgpd") or [])
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    if not plan["a_ecrire"]:
        return {**plan, "ecriture_effectuee": False, "message": "Rien à changer : déjà dans l'état demandé."}
    if not confirm:
        return {**plan, "ecriture_effectuee": False,
                "message": "Simulation, rien n'a été écrit — rappeler avec confirm=True après accord explicite."}
    if os.environ.get("ED_ADMIN_CONNECTEURS_ACTIF", "") != "1":
        raise ToolError("Écriture désactivée (ED_ADMIN_CONNECTEURS_ACTIF≠1) — jamais activée sur Azure.")
    res = await _get_client().ecrire_activation_connecteur({ch["libelle"]: ch["apres"] for ch in plan["a_ecrire"]})
    return {**plan, "ecriture_effectuee": True, **res}


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
async def ed_admin_parametre_set(libelle: str, valeur: str, confirm: bool = False) -> Any:
    """ÉCRITURE — modifie UN paramètre établissement. Un des QUATRE seuls outils
    d'écriture de ce connecteur (avec ed_admin_deposer_piece) ; tous les autres
    restent lecture seule.

    Sans confirm=True (par défaut) : n'écrit RIEN, renvoie un aperçu (valeur
    actuelle vs proposée) pour relecture. Il faut rappeler explicitement avec
    confirm=True pour appliquer le changement pour de vrai — et il faut TOUJOURS
    obtenir l'accord explicite de l'utilisateur en conversation avant de faire
    cet appel avec confirm=True, quel que soit le contexte.

    Refusé d'office pour tout paramètre ressemblant à un secret (clé, mot de
    passe, certificat, IBAN...) ou faisant partie de la liste que l'admin
    EcoleDirecte exclut lui-même de l'édition générique (règlements en ligne,
    connecteurs partenaires, délais réglementaires notes/LSU...).

    Refusé aussi, avant tout appel réseau, pour un libellé absent du catalogue
    (l'API accepterait une faute de frappe sans rien changer au vrai réglage).
    Les valeurs stockées en base64 (adresse, présentation de la page contact…)
    s'écrivent en clair : l'encodage est fait par l'outil.

    `libelle` = identifiant exact du paramètre (ex. 'Sites/Familles/Actif',
    trouvable via ed_admin_parametres_catalogue). `valeur` = nouvelle valeur en
    chaîne — les booléens s'écrivent '1'/'0', comme le fait l'interface admin
    elle-même."""
    return await _get_client().set_parametre(libelle, valeur, confirm)


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


@mcp.tool()
async def ed_admin_deposer_piece(id_eleve: int, fichier: str, confirm: bool = False,
                                 piece: str | None = None, compte_id: int | None = None,
                                 verifier: bool = True) -> Any:
    """ÉCRITURE — dépose UN PDF dans la liste de pièces à verser d'un élève
    (ex. « Fiches Rentrée »), à la place de la famille, via la supervision admin.
    L'un des cinq seuls outils d'écriture de ce connecteur.

    Sans confirm=True (par défaut) : SIMULATION — vérifie le fichier et retrouve
    l'élève et le compte famille, sans rien envoyer. Avec verifier=True (défaut
    de l'outil), la simulation ouvre aussi une supervision EN LECTURE SEULE pour
    contrôler que la liste et la pièce existent, sont autorisées, et qu'aucun
    document n'est déjà déposé ; verifier=False = simulation hors ligne.
    Il faut TOUJOURS obtenir l'accord explicite de l'utilisateur en conversation
    avant d'appeler avec confirm=True.

    Garde-fous : PDF ≤ 10 Mo situé sous ED_ADMIN_DEPOT_RACINE ; liste autorisée
    (ED_ADMIN_DEPOT_LISTES : libellés, débuts de libellés (≥ 6 lettres) et/ou
    numéros de listes, défaut « Fiches Rentrée ») ; en cas de refus, l'erreur
    liste les listes visibles et leur statut ; écriture seulement si
    ED_ADMIN_DEPOT_ACTIF=1 ; ne remplace JAMAIS un dépôt existant ; ne supprime
    rien ; journal local de chaque dépôt. Pour une classe entière, utiliser le
    script `python -m ecoledirecte_admin_mcp.depot_lot --classe <CLASSE>`.

    `id_eleve` = id EcoleDirecte de l'élève (identique à l'IDELEVE Charlemagne,
    trouvable via ed_admin_eleves_search). `fichier` = chemin absolu du PDF.
    `piece` = libellé exact de la pièce quand la liste en contient plusieurs
    (ex. « Justificatif Certificat Scolarité Ext. »). Pour une liste de type
    Famille, le document est rattaché au compte famille de l'élève indiqué.
    `compte_id` = compte famille à utiliser (par défaut le responsable) : doit être
    un compte rattaché à l'élève — ex. déposer sur le compte du second parent quand
    le premier a déjà un document pour cette pièce (parents séparés, 2e certificat)."""
    return await deposer_piece(_get_client(), id_eleve, fichier, confirm, piece=piece, compte_id=compte_id,
                               verifier=verifier)


@mcp.tool()
async def ed_admin_pieces_etat(id_eleve: int, compte_id: int | None = None) -> Any:
    """LECTURE — état des « pièces à verser » visibles dans l'espace d'une famille :
    pour chaque liste et chaque pièce, qui est concerné, si un document est déposé,
    à quelle date, et s'il est verrouillé (récupéré par Charlemagne). Indique aussi
    si le connecteur est autorisé à déposer dans chaque liste. Sert à savoir ce
    qu'une famille a déjà déposé elle-même avant un dépôt, ou à vérifier un dépôt.
    Ouvre une supervision en lecture seule ; ne télécharge ni ne modifie rien.
    `id_eleve` = un élève de la famille ; `compte_id` = compte famille précis
    (par défaut le responsable)."""
    return await etat_pieces(_get_client(), id_eleve, compte_id)


@mcp.tool()
async def ed_admin_documents_famille(id_eleve: int, compte_id: int | None = None,
                                     archive: str = "") -> Any:
    """LECTURE — documents publiés dans l'espace « Documents » d'une famille
    (factures, administratifs, notes, vie scolaire, inscription…) : rubrique,
    intitulé, date, type, signature demandée et son état. Une publication dans
    Documents ne notifie PAS les familles (contrairement à un message). Ouvre une
    supervision en lecture seule ; aucun document n'est ouvert ni téléchargé.
    `id_eleve` = un élève de la famille ; `compte_id` = un compte précis ; par
    défaut TOUS les comptes rattachés (les documents sont publiés compte par
    compte : `visible_pour` / `seulement_pour` disent quel parent voit quoi,
    `ids_par_compte` donne l'id à télécharger) ; `archive` = année d'archive
    (vide = en cours). Les pièces à verser sont dans ed_admin_pieces_etat."""
    return await documents_famille(_get_client(), id_eleve, compte_id, archive)


@mcp.tool()
async def ed_admin_documents_ecole(classe: str | None = None, archive: str = "") -> Any:
    """LECTURE — documents publiés par l'école dans l'espace « Documents » des
    familles, regroupés par intitulé et date, avec les classes où ils sont
    visibles (« toutes les classes » ou « classes ciblées »). Reconstitué en lisant
    l'espace d'UNE famille par classe (supervision en lecture seule, ~2 s par
    classe) ; factures, documents nominatifs et à signer (mandat SEPA) écartés.
    Sert à retrouver une circulaire publiée sans notification. `classe` =
    libellé ou idClasse pour se limiter à une classe ; `archive` = année."""
    return await documents_ecole(_get_client(), classe, archive)


@mcp.tool()
async def ed_admin_document_telecharger(id_eleve: int, document_id: int, compte_id: int | None = None,
                                        archive: str = "") -> Any:
    """LECTURE — télécharge un document publié dans l'espace « Documents » d'une
    famille (circulaire, facture…) et l'enregistre en PDF dans le dossier local
    ED_ADMIN_DOCUMENTS_DIR (droits 600, jamais écrasé) ; renvoie le chemin.
    `document_id` = champ `id` donné par ed_admin_documents_famille pour la même
    famille (`id_eleve` = un élève de la famille). Supervision en lecture seule.
    Refuse les documents bancaires (mandat SEPA, RIB). Les pièces déposées par les
    familles (pièces à verser) ne sont pas concernées."""
    return await telecharger_document(_get_client(), id_eleve, document_id, compte_id, archive)


@mcp.tool()
async def ed_admin_demande_activites(id_eleve: int, activites: dict[str, str] | None = None,
                                     regime: int | None = None, confirm: bool = False,
                                     compte_id: int | None = None) -> Any:
    """ÉCRITURE — envoie, au nom de la famille, une DEMANDE de modification des
    activités (garderie, étude, cantine…) et/ou du régime d'un élève, comme le
    formulaire « Vos informations » de l'espace famille. La demande arrive dans
    Charlemagne, où le secrétariat la valide : rien n'est modifié directement.

    `activites` = {code: jours}, jours parmi L M J V (ex. {"ETUDE": "LMJ",
    "MIDI": "LMJV", "MATIN": ""} ; "" = retirer tous les jours). Seules les
    activités qui changent sont envoyées. `regime` = id EcoleDirecte du régime
    (ex. 1 demi-pensionnaire, 2 externe — vérifier sur l'établissement).

    Sans confirm=True (par défaut) : SIMULATION — la fiche est lue pour montrer
    exactement ce qui changerait, rien n'est envoyé. Il faut TOUJOURS obtenir
    l'accord explicite de l'utilisateur en conversation avant confirm=True.
    Garde-fous : ED_ADMIN_DEMANDES_ACTIF=1 requis ; types autorisés
    (ED_ADMIN_DEMANDES_TYPES) ; code d'activité déjà présent sur la fiche ou listé
    dans ED_ADMIN_DEMANDES_ACTIVITES ; refus si une demande est déjà en attente ;
    journal local. Ne permet JAMAIS de modifier le mode de règlement ni les
    coordonnées bancaires : l'utilisateur lance lui-même, dans un Terminal,
    `python -m ecoledirecte_admin_mcp.rib --compte <id>` (IBAN jamais vu par l'assistant)."""
    return await demande_activites(_get_client(), id_eleve, activites, regime, confirm, compte_id)


@mcp.tool()
async def ed_admin_demande_telephones(compte_id: int, confirm: bool = False) -> Any:
    """ÉCRITURE — reformate les téléphones d'une famille au format
    « 06 12 34 56 78 » (requis pour l'envoi de SMS) par une DEMANDE de
    modification des coordonnées, comme le formulaire de l'espace famille. Tous
    les autres champs de la fiche (adresse, mails, profession…) sont renvoyés à
    l'identique. Seuls les numéros français reconnus sont reformatés ; les autres
    (étrangers, mentions, plusieurs numéros) sont listés « à traiter à la main ».

    Sans confirm=True (par défaut) : SIMULATION (lecture de la fiche, rien n'est
    envoyé). Il faut TOUJOURS obtenir l'accord explicite de l'utilisateur avant
    confirm=True. Garde-fous : ED_ADMIN_DEMANDES_ACTIF=1, type « telephones »
    autorisé, refus si une demande de coordonnées est déjà en attente, journal.
    `compte_id` = id du compte famille (ed_admin_familles_search)."""
    return await demande_telephones(_get_client(), compte_id, confirm)


@mcp.tool()
async def ed_admin_demande_coordonnees(compte_id: int, modifications: dict[str, str],
                                       confirm: bool = False) -> Any:
    """ÉCRITURE — envoie, au nom de la famille, une DEMANDE de modification de ses
    coordonnées, comme le formulaire de l'espace famille. La demande arrive dans
    Charlemagne, où le secrétariat la valide : rien n'est modifié directement.

    `modifications` = {champ: valeur}. Champs permis :
      - adresse : adresse1, adresse2, adresse3, codePostal (5 chiffres), ville ;
      - "responsable.<champ>" ou "conjoint.<champ>" : nom, mailPerso, mailTravail,
        telMobile, telTravail, telDomicile (responsable seulement), profession,
        societe, csp (code numérique).
    Ex. {"responsable.telMobile": "0612345678", "conjoint.mailPerso":
    "prenom.nom@example.org", "adresse1": "3 rue …", "codePostal": "77300",
    "ville": "FONTAINEBLEAU"}. Téléphones mis au format « 06 12 34 56 78 »
    (numéros français seulement) ; "" efface un champ facultatif ; adresse1,
    codePostal, ville et nom jamais vides. Civilité, prénom et situation
    familiale ne sont pas modifiables. Tous les autres champs sont renvoyés à
    l'identique.

    Sans confirm=True (par défaut) : SIMULATION (la fiche est lue, avant → après
    affiché, rien n'est envoyé). Il faut TOUJOURS obtenir l'accord explicite de
    l'utilisateur avant confirm=True. Garde-fous : ED_ADMIN_DEMANDES_ACTIF=1, type
    « coordonnees » autorisé (ED_ADMIN_DEMANDES_TYPES), refus si une demande de
    coordonnées est déjà en attente, journal. JAMAIS de coordonnées bancaires ni
    de mode de règlement (commande `…rib` lancée par l'utilisateur lui-même). `compte_id` = id du compte famille
    (ed_admin_familles_search)."""
    return await demande_coordonnees(_get_client(), compte_id, modifications, confirm)

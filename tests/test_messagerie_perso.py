"""Messagerie du connecteur personnel : lecture d'un message et brouillon/envoi — sans réseau."""
from __future__ import annotations

import base64

import pytest

from ecoledirecte_perso_mcp import client as cl
from ecoledirecte_perso_mcp import messagerie_ecriture as me

FAMILLES = [
    {"id": 7, "nom": "DUPONT", "prenom": "Alice", "classe": {"libelle": "CP"}, "messagerieActive": True,
     "responsable": {"id": 70, "typeResp": "1", "contacts": ["M. Jean DUPONT"]}},
    {"id": 7, "nom": "DUPONT", "prenom": "Alice", "classe": {"libelle": "CP"}, "messagerieActive": True,
     "responsable": {"id": 71, "typeResp": "2", "contacts": ["Mme Anne DUPONT"]}},
    {"id": 8, "nom": "MARTIN", "prenom": "Bob", "classe": {"libelle": "CE1"}, "messagerieActive": False,
     "responsable": {"id": 80, "typeResp": "1", "contacts": ["M. Paul MARTIN"]}},
]
PERSONNELS = [{"id": 30, "civilite": "Mme", "prenom": "Zoé", "nom": "TEST", "type": "A",
               "fonction": {"libelle": "ASEM"}, "messagerieActive": True}]


class FakeClient:
    def __init__(self):
        self.postes = []

    async def get(self, path, query=None, data=None):
        return {"contacts": FAMILLES if path.endswith("familles") else PERSONNELS}

    async def session_info(self):
        return {"id": "18", "typeCompte": "A", "nom": "SECRETARIAT", "prenom": "Compte"}

    async def poster_message(self, msg):
        self.postes.append(msg)
        return {"id": 99}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.delenv("ED_PERSO_MESSAGERIE_ACTIF", raising=False)
    monkeypatch.delenv("ED_PERSO_MESSAGERIE_MAX_DEST", raising=False)
    monkeypatch.setattr(me, "JOURNAL", tmp_path / "messages.csv")
    return FakeClient()


# --- garde-fous du client --------------------------------------------------
def test_ouverture_generique_toujours_bloquee():
    with pytest.raises(cl.ForbiddenEndpointError):
        cl.check_allowed("personnels/18/messages/12", "get")
    with pytest.raises(cl.ForbiddenEndpointError):
        cl.check_allowed("personnels/18/messages", "post")


class _Auth:
    class session:
        account_id, type_compte, token = "18", "A", "t"
    async def ensure_session(self, http):
        return self.session
    def update_token(self, t):
        pass
    def invalidate_token(self):
        pass


async def test_chemin_dedie_refuse_le_reste(monkeypatch):
    c = cl.EcoleDirectePersoClient(auth=_Auth(), http=object())
    base = "personnels/18/messages"
    for path, verbe, q, d in ((base + "/12", "get", {"mode": "autre"}, {}),
                              (base, "put", {}, {"action": "supprimer", "ids": [12]}),
                              (base, "put", {}, {"action": "marquerCommeNonLu", "ids": [12, 13]}),
                              (base, "delete", {}, {"ids": [12]}),
                              ("personnels/19/messages/12", "get", {"mode": "destinataire"}, {})):
        with pytest.raises(cl.ForbiddenEndpointError):
            await c._appel_messagerie(path, verbe, q, d)
    monkeypatch.delenv("ED_PERSO_MESSAGERIE_ACTIF", raising=False)
    with pytest.raises(cl.ForbiddenEndpointError):
        await c._appel_messagerie(base, "post", {}, {"message": {}, "anneeMessages": ""})


def test_texte_message_decode():
    b64 = base64.b64encode("<p>Bonjour&nbsp;Mme&#233;<br>ligne 2</p><p>Fin</p>".encode()).decode()
    assert cl.texte_message(b64) == "Bonjour\xa0Mmeé\nligne 2\n\nFin"


# --- encodage ----------------------------------------------------------------
def test_encodage_contenu():
    html = base64.b64decode(me.contenu_message("Bonjour à tous,\n\nCordialement,\nLe secrétariat")).decode("ascii")
    assert html == "<p>Bonjour &agrave; tous,</p><p>Cordialement,<br>Le secr&eacute;tariat</p>"
    assert me.texte_vers_html("<script>") == "<p>&lt;script&gt;</p>"


def test_groupes_destinataires():
    dest = [{"id": 7, "type": "1", "to_cc_cci": "to"}, {"id": 30, "type": "A", "to_cc_cci": "cc"}]
    m = me.construire_message("Objet", "Texte", dest, "A", 18, brouillon=True)
    assert [g["selection"]["type"] for g in m["groupesDestinataires"]] == ["1", "A"]
    assert m["brouillon"] is True and m["from"] == {"role": "A", "id": 18, "read": True}


# --- résolution et garde-fous d'écriture -------------------------------------
async def test_resolution(env):
    d = await me.resoudre_destinataires(env, [{"type": "famille", "id_eleve": 7, "responsable": "tous"},
                                              {"type": "personnel", "id": 30, "champ": "cc"}])
    assert [(x["responsable"]["id"] if "responsable" in x else x["id"], x["to_cc_cci"]) for x in d] == [(70, "to"), (71, "to"), (30, "cc")]
    assert all(x["type"] == "1" for x in d[:2])
    d = await me.resoudre_destinataires(env, [{"type": "famille", "id_eleve": 7, "responsable": "2"}])
    assert len(d) == 1 and d[0]["responsable"]["id"] == 71


async def test_introuvable_et_inactif(env):
    with pytest.raises(me.MessagerieError, match="introuvable"):
        await me.resoudre_destinataires(env, [{"type": "famille", "id_eleve": 999}])
    with pytest.raises(me.MessagerieError, match="inactive"):
        await me.resoudre_destinataires(env, [{"type": "famille", "id_eleve": 8}])


async def test_simulation_n_ecrit_rien(env):
    r = await me.preparer_message(env, "Objet", "Texte", [{"type": "famille", "id_eleve": 7}])
    assert r["ecrit"] is False and len(r["destinataires"]) == 2 and env.postes == []


async def test_ecriture_desactivee_par_defaut(env):
    with pytest.raises(me.MessagerieError, match="désactivée"):
        await me.preparer_message(env, "Objet", "Texte", [{"type": "personnel", "id": 30}], confirm=True)
    assert env.postes == []


async def test_brouillon_et_journal(env, monkeypatch):
    monkeypatch.setenv("ED_PERSO_MESSAGERIE_ACTIF", "1")
    r = await me.preparer_message(env, "Objet", "Texte", [{"type": "personnel", "id": 30}], confirm=True)
    assert r["ecrit"] is True and env.postes[0]["brouillon"] is True and me.JOURNAL.exists()
    assert "Texte" not in me.JOURNAL.read_text()          # le contenu n'est pas journalisé


async def test_plafond(env, monkeypatch):
    monkeypatch.setenv("ED_PERSO_MESSAGERIE_MAX_DEST", "1")
    with pytest.raises(me.MessagerieError, match="plafond"):
        await me.preparer_message(env, "Objet", "Texte", [{"type": "famille", "id_eleve": 7}])


async def test_mode_et_champs_invalides(env):
    with pytest.raises(me.MessagerieError):
        await me.preparer_message(env, "Objet", "Texte", [{"type": "personnel", "id": 30}], mode="differe")
    with pytest.raises(me.MessagerieError):
        await me.preparer_message(env, "", "Texte", [{"type": "personnel", "id": 30}])
    with pytest.raises(me.MessagerieError):
        await me.resoudre_destinataires(env, [{"type": "personnel", "id": 30, "champ": "bcc"}])

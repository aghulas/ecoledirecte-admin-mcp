"""Passage Web du connecteur personnel : lecture, pointage, suppression — sans réseau."""
from __future__ import annotations

from datetime import date

import pytest

from ecoledirecte_perso_mcp import client as cl
from ecoledirecte_perso_mcp import passage_web as pw

LISTE = "6:Garderie:0600:2000||7:Cantine:1130:1330||8:Etude / Garderie:1630:1830"
PREVUS = [
    {"idEleve": 101, "nom": "TESTEUR", "prenom": "Ixe", "classeCode": "CP", "regimeCode": "D",
     "badge": "11010", "photo": "x.jpg", "dateNaissance": "2019-01-01", "sexe": "F", "particule": ""},
    {"idEleve": 102, "nom": "EXEMPLE", "prenom": "Ygrec", "classeCode": "CP", "regimeCode": "E",
     "badge": "11020", "photo": "", "dateNaissance": "2019-02-02", "sexe": "M", "particule": ""},
]
CLASSES = {"etablissements": [{"niveaux": [{"classes": [{"id": 1, "code": "CP"}, {"id": 2, "code": "CE1"}]}]}]}
ELEVES = {"1": {"eleves": [{"id": 101, "nom": "TESTEUR", "prenom": "Ixe"}]},
          "2": {"eleves": [{"id": 201, "nom": "FICTIF", "prenom": "Zede", "sexe": "F", "particule": ""}]}}


class _Session:
    account_id, type_compte, token = "47", "A", "t"
    account = {"id": "47", "typeCompte": "A", "listePDP": LISTE}


class _Auth:
    session = _Session()
    async def ensure_session(self, http):
        return self.session
    def update_token(self, t):
        pass
    def invalidate_token(self):
        pass


class FakeClient:
    def __init__(self, deja=None):
        self.auth, self._http = _Auth(), None
        self.ajouts, self.suppressions = [], []
        self.jour = list(deja or [])
        self.classes_lues = 0

    def points_passage_web(self):
        return self.auth.session.account["listePDP"]

    async def passage_web_prevus(self, id_pdp):
        return PREVUS

    async def passage_web_jour(self, id_pdp, jour):
        return [p for p in self.jour if p["idPDP"] == id_pdp and p["date"] == jour]

    async def niveaux(self):
        return CLASSES

    async def classe_eleves(self, id_classe):
        self.classes_lues += 1
        return ELEVES[id_classe]

    async def ajouter_passage_web(self, passage):
        self.ajouts.append(passage)
        p = {**passage, "idPassageWeb": 500 + len(self.ajouts)}
        self.jour.append(p)
        return {"idPassageWeb": p["idPassageWeb"]}

    async def supprimer_passage_web(self, i):
        self.suppressions.append(i)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.delenv("ED_PERSO_PASSAGEWEB_ACTIF", raising=False)
    monkeypatch.delenv("ED_PERSO_PASSAGEWEB_MAX", raising=False)
    monkeypatch.setattr(pw, "JOURNAL", tmp_path / "passages_web.csv")
    monkeypatch.setattr(pw, "PAUSE_SECONDES", 0)
    return tmp_path


# --- fonctions pures ---------------------------------------------------------
def test_analyser_points():
    pts = pw.analyser_points(LISTE)
    assert [p["id"] for p in pts] == [6, 7, 8]
    assert pts[2] == {"id": 8, "libelle": "Etude / Garderie", "heureDebut": "16:30", "heureFin": "18:30"}
    assert pw.analyser_points("") == [] and pw.analyser_points("x:y") == []


def test_dates_et_heures(monkeypatch):
    monkeypatch.setattr(pw.SETTINGS.__class__, "annee", "2026-2027", raising=False)
    assert pw.verifier_date("2026-10-22", aujourd_hui=date(2026, 10, 23)) == "2026-10-22"
    for mauvaise in ("22/10/2026", "2026-10-24", "2026-07-01", "", None):
        with pytest.raises(pw.PassageWebError):
            pw.verifier_date(mauvaise, aujourd_hui=date(2026, 10, 23))
    assert pw.verifier_heure("17:05") == "17:05"
    for h in ("17h05", "25:00", "7:05", None):
        with pytest.raises(pw.PassageWebError):
            pw.verifier_heure(h)


def test_construire_passage_comme_le_front():
    p = pw.construire_passage(8, "2026-10-22", "17:00", PREVUS[0], "11010")
    assert p == {"idPassageWeb": 0, "idPassant": 101, "typePassant": "E", "date": "2026-10-22",
                 "heure": "17:00", "idPDP": 8, "dateTransmission": "", "dateAcq": "", "nom": "TESTEUR",
                 "prenom": "Ixe", "particule": "", "dateNaissance": "", "sexe": "F", "photo": "",
                 "badge": "11010"}


# --- lecture -------------------------------------------------------------------
async def test_prevus_sans_donnees_sensibles(env):
    r = await pw.prevus(FakeClient(), 8)
    assert r["nombre"] == 2
    for e in r["eleves"]:
        assert not {"badge", "photo", "dateNaissance"} & set(e)


async def test_point_inconnu_refuse(env):
    with pytest.raises(pw.PassageWebError):
        await pw.prevus(FakeClient(), 99)


# --- pointage --------------------------------------------------------------------
async def test_simulation_par_defaut(env, monkeypatch):
    monkeypatch.setenv("ED_PERSO_PASSAGEWEB_ACTIF", "1")
    c = FakeClient()
    r = await pw.pointer(c, 8, "2026-10-22", "17:00", [101, 201, 999])
    assert r["mode"] == "simulation" and c.ajouts == []
    statuts = {e["idEleve"]: e["statut"] for e in r["eleves"]}
    assert statuts[101] == "à pointer" and statuts[201] == "à pointer" and statuts[999].startswith("inconnu")
    assert r["sans_badge"] == 1
    assert all(not k.startswith("_") for e in r["eleves"] for k in e)


async def test_ecriture_refusee_sans_variable(env):
    with pytest.raises(pw.PassageWebError):
        await pw.pointer(FakeClient(), 8, "2026-10-22", "17:00", [101], confirm=True)


async def test_pointage_sans_doublon_et_journal(env, monkeypatch):
    monkeypatch.setenv("ED_PERSO_PASSAGEWEB_ACTIF", "1")
    deja = [{"idPassageWeb": 1, "idPassant": 102, "typePassant": "E", "idPDP": 8, "date": "2026-10-22"}]
    c = FakeClient(deja)
    r = await pw.pointer(c, 8, "2026-10-22", "17:00", [101, 102, 101, 201], badges={"201": "12010"}, confirm=True)
    assert [a["idPassant"] for a in c.ajouts] == [101, 201]
    assert c.ajouts[0]["badge"] == "11010" and c.ajouts[1]["badge"] == "12010"
    assert r["pointes"] == 2 and r["deja_pointes"] == 1 and r["passages_du_jour_apres"] == 3
    lignes = (env / "passages_web.csv").read_text(encoding="utf-8").splitlines()
    assert len(lignes) == 3 and "TESTEUR" not in "".join(lignes)
    r2 = await pw.pointer(c, 8, "2026-10-22", "17:00", [101, 201], confirm=True)
    assert r2["a_pointer"] == 0 and len(c.ajouts) == 2


async def test_plafond(env, monkeypatch):
    monkeypatch.setenv("ED_PERSO_PASSAGEWEB_MAX", "2")
    with pytest.raises(pw.PassageWebError):
        await pw.pointer(FakeClient(), 8, "2026-10-22", "17:00", [1, 2, 3])


async def test_annuaire_seulement_si_necessaire(env):
    c = FakeClient()
    await pw.pointer(c, 8, "2026-10-22", "17:00", [101, 102])
    assert c.classes_lues == 0


# --- suppression -----------------------------------------------------------------
async def test_suppression_non_integres_seulement(env, monkeypatch):
    monkeypatch.setenv("ED_PERSO_PASSAGEWEB_ACTIF", "1")
    deja = [{"idPassageWeb": 1, "idPassant": 101, "idPDP": 8, "date": "2026-10-22", "dateAcq": ""},
            {"idPassageWeb": 2, "idPassant": 102, "idPDP": 8, "date": "2026-10-22", "dateAcq": "2026-10-23"}]
    c = FakeClient(deja)
    r = await pw.supprimer(c, 8, "2026-10-22", [1, 2, 3])
    assert r["mode"] == "simulation" and r["a_supprimer"] == 1 and c.suppressions == []
    r = await pw.supprimer(c, 8, "2026-10-22", [1, 2, 3], confirm=True)
    assert c.suppressions == [1] and r["supprimes"] == 1


# --- garde-fous du client ----------------------------------------------------------
def test_chemin_generique_refuse_les_ecritures():
    with pytest.raises(cl.ForbiddenEndpointError):
        cl.check_allowed("PassageWeb/8/recupDesPassagesWeb/2026-10-22", "post")


async def test_chemin_dedie_liste_blanche(monkeypatch):
    c = cl.EcoleDirectePersoClient(auth=_Auth(), http=object())
    monkeypatch.delenv("ED_PERSO_PASSAGEWEB_ACTIF", raising=False)
    with pytest.raises(cl.ForbiddenEndpointError):
        await c._appel_passage_web("post", "PassageWeb/8/recupDesPassagesWeb/2026-10-22", {"passageWeb": {}})
    monkeypatch.setenv("ED_PERSO_PASSAGEWEB_ACTIF", "1")
    for verbe, path, data in (("put", "PassageWeb/8/recupDesPassagesWeb/2026-10-22", {"passageWeb": {}}),
                              ("post", "PassageWeb/8/autreChose/2026-10-22", {"passageWeb": {}}),
                              ("post", "PassageWeb/8/recupDesPassagesWeb/22-10-2026", {"passageWeb": {}}),
                              ("post", "PassageWeb/8/recupDesPassagesWeb/2026-10-22", {"passageWeb": {}, "x": 1}),
                              ("delete", "PassageWeb/abc", {}),
                              ("delete", "PassageWeb/12", {"ids": [1]}),
                              ("delete", "personnels/47/messages", {})):
        with pytest.raises(cl.ForbiddenEndpointError):
            await c._appel_passage_web(verbe, path, data)

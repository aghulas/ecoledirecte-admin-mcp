"""Demande de mode de règlement / RIB (rib.py) — sans réseau, IBAN d'exemple publics."""
from __future__ import annotations

import argparse
import base64
import csv

import pytest

from ecoledirecte_admin_mcp import rib

IBAN_FR = "FR76 3000 6000 0112 3456 7890 189"      # IBAN d'exemple (documentation bancaire)
IBAN_FR2 = "FR14 2004 1010 0505 0001 3M02 606"     # autre exemple public


@pytest.mark.parametrize("v,ok", [(IBAN_FR, True), (IBAN_FR2, True), ("GB82 WEST 1234 5698 7654 32", True),
                                  ("FR76 3000 6000 0112 3456 7890 188", False),  # clé fausse
                                  ("FR76 3000 6000 0112 3456 7890", False), ("", False), ("pas un iban", False)])
def test_iban(v, ok):
    assert rib.iban_valide(v) is ok


def test_masques():
    assert rib.masquer_iban(IBAN_FR) == "FR76 •••• •••• 189"
    assert rib.masquer_iban("") == "(aucun)"
    assert rib.masquer_bic("AGRIFRPP882") == "AGRI••••"
    r = rib.resume_masque({"modedereglement": "Prélèvement", "iban": IBAN_FR, "bic": "AGRIFRPP882"})
    assert "3456" not in str(r) and "FRPP" not in str(r)


@pytest.mark.parametrize("v,ok", [("AGRIFRPP", True), ("agrifrpp882", True), ("AGRIFRP", False), ("AGRI FRPP", False)])
def test_bic(v, ok):
    assert rib.bic_valide(v) is ok


def test_xml_prelevement_et_cheque():
    x = rib.xml_mode_reglement(rib.PRELEVEMENT, IBAN_FR, "agrifrpp", "Banque & Cie", "m ou mme test", "abc¤rib.PDF")
    assert x == ("<demandeModifications><modeReglement>Prélèvement</modeReglement>"
                 "<IBAN>FR7630006000011234567890189</IBAN><BIC>AGRIFRPP</BIC>"
                 "<Domiciliation>Banque &amp; Cie</Domiciliation><Tire>M OU MME TEST</Tire>"
                 "<AvecFichierRIB>1</AvecFichierRIB><Extension>pdf</Extension></demandeModifications>")
    assert rib.xml_mode_reglement(rib.CHEQUE) == \
        "<demandeModifications><modeReglement>Chèque</modeReglement></demandeModifications>"
    with pytest.raises(rib.RibError):
        rib.xml_mode_reglement("Virement")


def test_fichier_rib(tmp_path):
    with pytest.raises(rib.RibError, match="illisible"):
        rib.verifier_fichier_rib(tmp_path / "absent.pdf")
    (tmp_path / "r.docx").write_bytes(b"x")
    with pytest.raises(rib.RibError, match="PDF"):
        rib.verifier_fichier_rib(tmp_path / "r.docx")
    (tmp_path / "r.pdf").write_bytes(b"%PDF-1.4")
    assert rib.verifier_fichier_rib(tmp_path / "r.pdf").name == "r.pdf"


def test_pas_d_outil_mcp():
    src = (rib.Path(rib.__file__).parent / "server.py").read_text(encoding="utf-8")
    assert "rib" not in [w.strip(" ,.") for w in src.split()] and "from .rib" not in src
    assert "famillemodedereglement" not in src and "modeReg" not in src


def test_refus_hors_terminal(monkeypatch, capsys):
    monkeypatch.setattr(rib.sys.stdin, "isatty", lambda: False, raising=False)
    assert rib.main(["--compte", "1", "--etat"]) == 2


# --- déroulé complet avec une fausse session --------------------------------
class FakeResp:
    def __init__(self, payload):
        self.payload, self.headers, self.status_code = payload, {}, 200

    def json(self):
        return self.payload


class FakeHttp:
    def __init__(self):
        self.uploads = []

    async def post(self, url, files=None, headers=None, timeout=None):
        self.uploads.append((url, files))
        return FakeResp({"code": 200, "data": {"unc": "xyz¤RIB.pdf"}})

    async def aclose(self):
        pass


class FakeFam:
    def __init__(self, en_attente=False):
        self.http, self.appels, self.en_attente = FakeHttp(), [], en_attente

    def _headers(self):
        return {}

    def _take_token(self, resp, payload):
        pass

    async def appeler(self, chemin, verbe, data=None):
        self.appels.append((chemin, verbe, data))
        if chemin == "famillemodedereglement":
            return {"code": 200, "data": {"modedereglement": "Chèque", "demandeencours": False}}
        if chemin.startswith("demandemodifications/modeReg/"):
            return {"code": 200, "data": {"id": 5} if self.en_attente else {}}
        return {"code": 200}


class FakeAdmin:
    def __init__(self, *a, **k):
        pass

    async def list_utilisateurs(self, t, f):
        return [{"id": 10, "civilite": "M.", "nom": "DUPONT", "prenom": "Jean", "type": "responsable", "enfants": []}]


@pytest.fixture
def env(tmp_path, monkeypatch):
    fam = FakeFam()
    import ecoledirecte_admin_mcp.client as client_mod
    monkeypatch.setattr(client_mod, "EcoleDirecteAdminClient", FakeAdmin)

    async def superviser(admin, compte):
        return fam
    monkeypatch.setattr(rib, "ouvrir_supervision", superviser)
    monkeypatch.setattr(rib, "JOURNAL", tmp_path / "j.csv")
    (tmp_path / "rib.pdf").write_bytes(b"%PDF-1.4")
    return {"fam": fam, "rib": str(tmp_path / "rib.pdf"), "tmp": tmp_path}


def _saisies(monkeypatch, reponses):
    it = iter(reponses)
    monkeypatch.setattr("builtins.input", lambda q="": next(it))


def _args(**k):
    base = dict(compte=10, cheque=False, etat=False, rib=None, domiciliation="CIC", titulaire="M DUPONT")
    return argparse.Namespace(**{**base, **k})


async def test_envoi_prelevement(env, monkeypatch, capsys):
    _saisies(monkeypatch, [IBAN_FR, IBAN_FR, "AGRIFRPP", "ENVOYER"])
    assert await rib.executer(_args(rib=env["rib"])) == 0
    fam = env["fam"]
    assert len(fam.http.uploads) == 1
    (chemin, verbe, data), = [a for a in fam.appels if a[1] == "post"]
    assert chemin == "demandemodifications/modeReg" and data["modifications"]["uncRIB"] == "xyz¤RIB.pdf"
    xml = base64.b64decode(data["modifications"]["contenu"]).decode()
    assert "<IBAN>FR7630006000011234567890189</IBAN>" in xml and "<AvecFichierRIB>1</AvecFichierRIB>" in xml
    sortie = capsys.readouterr().out
    assert "3456" not in sortie and "FR76 •••• •••• 189" in sortie
    journal = (env["tmp"] / "j.csv").read_text(encoding="utf-8")
    assert "3456" not in journal and "AGRIFRPP" not in journal


async def test_nouvel_iban_sans_rib_refuse(env, monkeypatch):
    _saisies(monkeypatch, [IBAN_FR, IBAN_FR])
    with pytest.raises(rib.RibError, match="RIB"):
        await rib.executer(_args())
    assert not [a for a in env["fam"].appels if a[1] == "post"]


async def test_annulation(env, monkeypatch):
    _saisies(monkeypatch, [IBAN_FR, IBAN_FR, "AGRIFRPP", "non"])
    assert await rib.executer(_args(rib=env["rib"])) == 1
    assert not env["fam"].http.uploads and not [a for a in env["fam"].appels if a[1] == "post"]


async def test_iban_mal_saisi(env, monkeypatch):
    _saisies(monkeypatch, ["FR76 0000"] * 3)
    with pytest.raises(rib.RibError, match="IBAN"):
        await rib.executer(_args(rib=env["rib"]))


async def test_cheque_sans_rib(env, monkeypatch):
    _saisies(monkeypatch, ["ENVOYER"])
    assert await rib.executer(_args(cheque=True)) == 0
    (_, _, data), = [a for a in env["fam"].appels if a[1] == "post"]
    assert data["modifications"]["uncRIB"] == "" and not env["fam"].http.uploads


async def test_demande_en_attente(env, monkeypatch):
    env["fam"].en_attente = True
    assert await rib.executer(_args(rib=env["rib"])) == 1
    assert not [a for a in env["fam"].appels if a[1] == "post"]

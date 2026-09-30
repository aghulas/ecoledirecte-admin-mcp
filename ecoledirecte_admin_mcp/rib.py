"""Demande de modification du MODE DE RÈGLEMENT / RIB d'une famille — commande
lancée À LA MAIN dans un Terminal, jamais exposée comme outil MCP (30/09/2026).

Pourquoi une commande et pas un outil : l'IBAN et le BIC ne doivent jamais passer
par l'assistant (ni saisis par lui, ni affichés dans une conversation). La personne
qui lance la commande tape elle-même l'IBAN et le BIC ; tout ce qui est affiché ou
journalisé est MASQUÉ (FR76 •••• •••• 152).

Usage :
    python -m ecoledirecte_admin_mcp.rib --compte 296 --rib ~/…/RIB.pdf
        [--titulaire "M OU MME DUPONT"] [--domiciliation "CIC FONTAINEBLEAU"]
    python -m ecoledirecte_admin_mcp.rib --compte 296 --cheque
    python -m ecoledirecte_admin_mcp.rib --compte 296 --etat       (lecture seule, masquée)

Protocole (relevé sur le front famille, composant « Mode de règlement ») :
  1. lecture : POST v3/famillemodedereglement.awp?verbe=get
       → {modedereglement, demandeencours, iban, bic, domiciliation, tire}
     demande en attente : POST v3/demandemodifications/modeReg/<idCompte>.awp?verbe=get
  2. RIB (obligatoire dès que l'IBAN change) : POST v3/televersement.awp?verbe=post
       multipart, champ « file », sans paramètre → data.unc
  3. POST v3/demandemodifications/modeReg.awp?verbe=post
       data={"modifications": {"contenu": base64(XML), "uncRIB": unc}}
     XML : <demandeModifications><modeReglement>Prélèvement</modeReglement><IBAN>…</IBAN>
           <BIC>…</BIC><Domiciliation>…</Domiciliation><Tire>…</Tire>
           <AvecFichierRIB>1</AvecFichierRIB><Extension>pdf</Extension></demandeModifications>
     (Chèque : seulement <modeReglement>Chèque</modeReglement>).
La demande arrive dans Charlemagne, où le secrétariat la valide (et vérifie le mandat
SEPA signé pour un passage au prélèvement) : rien n'est modifié directement.

Garde-fous : terminal interactif obligatoire ; IBAN contrôlé (clé mod 97) et saisi deux
fois ; BIC au format 8 ou 11 caractères ; RIB (PDF/JPEG/PNG ≤ 5 Mo) obligatoire pour un
nouvel IBAN ; refus si une demande est déjà en attente ; récapitulatif masqué puis
confirmation en tapant « ENVOYER » ; journal local sans IBAN ni BIC complets.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from .config import SETTINGS
from .depot_pieces import WWW_API_BASE, WWW_API_VERSION, DepotError, ouvrir_supervision

PRELEVEMENT, CHEQUE = "Prélèvement", "Chèque"
JOURNAL = SETTINGS.home_dir / "demandes_mode_reglement.csv"
TYPES_RIB = {".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}
TAILLE_MAX = 5 * 1024 * 1024


class RibError(DepotError):
    """Erreur de la demande de mode de règlement (message sans IBAN complet)."""


# ----------------------------------------------------------------------
# Fonctions pures (testées sans réseau)
# ----------------------------------------------------------------------
def normaliser_iban(v: str) -> str:
    return re.sub(r"[\s-]", "", v or "").upper()


def iban_valide(v: str) -> bool:
    iban = normaliser_iban(v)
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", iban):
        return False
    if iban.startswith("FR") and len(iban) != 27:
        return False
    chiffres = "".join(str(int(c, 36)) for c in iban[4:] + iban[:4])
    return int(chiffres) % 97 == 1


def masquer_iban(v: str | None) -> str:
    iban = normaliser_iban(v or "")
    if not iban:
        return "(aucun)"
    return f"{iban[:4]} •••• •••• {iban[-3:]}" if len(iban) > 7 else "••••"


def masquer_bic(v: str | None) -> str:
    b = (v or "").strip().upper()
    return f"{b[:4]}••••" if b else "(aucun)"


def bic_valide(v: str) -> bool:
    return bool(re.fullmatch(r"[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}([A-Z0-9]{3})?", (v or "").strip().upper()))


def extension_unc(unc: str) -> str:
    m = re.search(r"\.([A-Za-z0-9]+)$", unc or "")
    return m.group(1).lower() if m else ""


def xml_mode_reglement(mode: str, iban: str = "", bic: str = "", domiciliation: str = "",
                       tire: str = "", unc_rib: str = "") -> str:
    """Réplique de modifsToXml du composant « Mode de règlement » du front famille."""
    if mode not in (PRELEVEMENT, CHEQUE):
        raise RibError(f"Mode de règlement inconnu « {mode} ».")
    t = lambda tag, val: f"<{tag}>{escape(val or '')}</{tag}>"
    parts = [t("modeReglement", mode)]
    if mode == PRELEVEMENT:
        parts += [t("IBAN", normaliser_iban(iban)), t("BIC", (bic or "").strip().upper()),
                  t("Domiciliation", domiciliation.strip()), t("Tire", (tire or "").strip().upper()),
                  t("AvecFichierRIB", "1" if unc_rib else "0"), t("Extension", extension_unc(unc_rib))]
    return "<demandeModifications>" + "".join(parts) + "</demandeModifications>"


def resume_masque(m: dict[str, Any]) -> dict[str, str]:
    return {"mode": m.get("modedereglement") or m.get("mode") or "(aucun)",
            "iban": masquer_iban(m.get("iban")), "bic": masquer_bic(m.get("bic")),
            "domiciliation": m.get("domiciliation") or "", "titulaire": m.get("tire") or ""}


def verifier_fichier_rib(p: Path) -> Path:
    p = p.expanduser()
    try:
        taille = p.stat().st_size
    except OSError as exc:
        raise RibError(f"RIB illisible : {p} (fichier absent, ou OneDrive ne l'a pas téléchargé).") from exc
    if p.suffix.lower() not in TYPES_RIB:
        raise RibError("Le RIB doit être un PDF, un JPEG ou un PNG.")
    if not 0 < taille <= TAILLE_MAX:
        raise RibError("Le RIB doit faire moins de 5 Mo.")
    return p


# ----------------------------------------------------------------------
# Accès réseau (session famille en supervision)
# ----------------------------------------------------------------------
async def lire_mode(fam) -> dict[str, Any]:
    r = await fam.appeler("famillemodedereglement", "get")
    if r.get("code") != 200:
        raise RibError(f"Lecture du mode de règlement impossible (code {r.get('code')}).")
    return r.get("data") or {}


async def demande_en_attente(fam, compte_id: int) -> bool:
    r = await fam.appeler(f"demandemodifications/modeReg/{compte_id}", "get")
    d = r.get("data") or {}
    return bool(d.get("id"))


async def televerser_rib(fam, p: Path) -> str:
    url = f"{WWW_API_BASE}televersement.awp?verbe=post&v={WWW_API_VERSION}"
    headers = {**fam._headers(), "Accept": "application/json", "Cache-Control": "no-cache",
               "X-Requested-With": "XMLHttpRequest"}
    files = {"file": (p.name, p.read_bytes(), TYPES_RIB[p.suffix.lower()])}
    resp = await fam.http.post(url, files=files, headers=headers, timeout=120)
    try:
        payload = resp.json()
    except ValueError as exc:
        raise RibError(f"Téléversement du RIB : réponse non JSON (HTTP {resp.status_code}).") from exc
    fam._take_token(resp, payload)
    data = payload.get("data")
    if isinstance(data, list):
        data = data[0] if data else {}
    unc = (data or {}).get("unc") or ""
    if payload.get("code") != 200 or not unc:
        raise RibError(f"Téléversement du RIB refusé (code {payload.get('code')} — {payload.get('message') or ''}).")
    return unc


async def envoyer(fam, contenu_xml: str, unc_rib: str) -> dict[str, Any]:
    corps = {"modifications": {"contenu": base64.b64encode(contenu_xml.encode("utf-8")).decode(),
                               "uncRIB": unc_rib}}
    return await fam.appeler("demandemodifications/modeReg", "post", corps)


def journaliser(row: dict[str, Any]) -> None:
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    new = not JOURNAL.exists()
    with JOURNAL.open("a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(row.keys()))
        if new:
            w.writeheader()
        w.writerow(row)


# ----------------------------------------------------------------------
# Commande interactive
# ----------------------------------------------------------------------
def _demander(question: str) -> str:
    return input(question).strip()


def _saisir_iban() -> str:
    for _ in range(3):
        a = normaliser_iban(_demander("IBAN : "))
        if not iban_valide(a):
            print("  IBAN invalide (clé de contrôle ou longueur). Recommencez.")
            continue
        b = normaliser_iban(_demander("IBAN (à nouveau, pour vérification) : "))
        if a == b:
            return a
        print("  Les deux saisies diffèrent. Recommencez.")
    raise RibError("IBAN non confirmé : abandon.")


def _saisir_bic() -> str:
    for _ in range(3):
        b = _demander("BIC : ").upper()
        if bic_valide(b):
            return b
        print("  BIC invalide (8 ou 11 caractères). Recommencez.")
    raise RibError("BIC invalide : abandon.")


async def executer(args: argparse.Namespace) -> int:
    from .client import EcoleDirecteAdminClient

    admin = EcoleDirecteAdminClient()
    familles = await admin.list_utilisateurs("familles", "")
    compte = next((f for f in familles if int(f.get("id", -1)) == int(args.compte)), None)
    if not compte:
        raise RibError(f"Compte famille {args.compte} introuvable.")
    enfants = ", ".join(f"{e.get('prenom')} ({e.get('libelleClasse')})" for e in compte.get("enfants") or [])
    print(f"\nCompte : {compte.get('civilite', '')} {compte['nom']} {compte['prenom']} (id {compte['id']}) — {enfants}")
    fam = await ouvrir_supervision(admin, compte)
    try:
        actuel = await lire_mode(fam)
        print("Mode de règlement actuel :", json.dumps(resume_masque(actuel), ensure_ascii=False))
        en_attente = await demande_en_attente(fam, compte["id"])
        if en_attente:
            print("Une demande de mode de règlement est déjà en attente : la faire valider dans Charlemagne d'abord.")
        if args.etat or en_attente:
            return 0 if args.etat else 1

        if args.cheque:
            mode, iban, bic, dom, tire, rib = CHEQUE, "", "", "", "", None
        else:
            mode = PRELEVEMENT
            rib = verifier_fichier_rib(Path(args.rib)) if args.rib else None
            iban = _saisir_iban()
            if iban != normaliser_iban(actuel.get("iban") or "") and not rib:
                raise RibError("Nouvel IBAN : le RIB (--rib fichier) est obligatoire.")
            bic = _saisir_bic()
            dom = args.domiciliation or _demander("Domiciliation (banque, agence) : ")
            tire = args.titulaire or _demander("Titulaire du compte : ")

        nouveau = {"modedereglement": mode, "iban": iban, "bic": bic, "domiciliation": dom, "tire": tire}
        print("\nDemande qui sera envoyée :", json.dumps(resume_masque(nouveau), ensure_ascii=False))
        if rib:
            print(f"RIB joint : {rib.name}")
        if mode == PRELEVEMENT:
            print("Rappel : un passage au prélèvement demande un mandat SEPA signé.")
        if _demander("Tapez ENVOYER pour envoyer la demande (autre chose pour annuler) : ") != "ENVOYER":
            print("Annulé : rien n'a été envoyé.")
            return 1

        unc = await televerser_rib(fam, rib) if rib else ""
        r = await envoyer(fam, xml_mode_reglement(mode, iban, bic, dom, tire, unc), unc)
        journaliser({"horodatage": datetime.now().isoformat(timespec="seconds"), "id_compte_famille": compte["id"],
                     "famille": f"{compte['nom']} {compte['prenom']}", "avant": json.dumps(resume_masque(actuel), ensure_ascii=False),
                     "apres": json.dumps(resume_masque(nouveau), ensure_ascii=False),
                     "rib_joint": rib.name if rib else "", "code_api": r.get("code")})
        if r.get("code") != 200:
            raise RibError(f"Demande refusée (code {r.get('code')} — {r.get('message') or ''}).")
        print("Demande envoyée : à valider dans Charlemagne, puis resynchroniser EcoleDirecte.")
        return 0
    finally:
        await fam.http.aclose()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m ecoledirecte_admin_mcp.rib",
                                description="Demande de modification du mode de règlement / RIB d'une famille.")
    p.add_argument("--compte", type=int, required=True, help="id du compte famille EcoleDirecte")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--cheque", action="store_true", help="passer au règlement par chèque / autre moyen")
    g.add_argument("--etat", action="store_true", help="afficher le mode actuel (masqué), sans rien envoyer")
    p.add_argument("--rib", help="RIB (PDF, JPEG ou PNG) — obligatoire pour un nouvel IBAN")
    p.add_argument("--domiciliation", help="banque / agence")
    p.add_argument("--titulaire", help="titulaire du compte, tel que sur le RIB")
    args = p.parse_args(argv)
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("Cette commande doit être lancée à la main dans un Terminal.", file=sys.stderr)
        return 2
    try:
        return asyncio.run(executer(args))
    except (RibError, DepotError) as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nAnnulé : rien n'a été envoyé.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""
Fusionne toutes les sources en deux sorties destinées au site :

1. data/calendrier.ics — le calendrier final, prêt à publier. Contient :
   - tous les événements Plein Soleil (source ICS fiable, jamais de
     validation nécessaire)
   - les entrées Facebook dont le statut a été mis à "approuvé" dans
     data/a_valider.csv (après relecture et complément d'information par
     un humain — voir README)

2. data/evenements.json — la même liste, en JSON trié par date, pensée
   pour être consommée facilement par le site statique (plus simple à
   afficher qu'un fichier ICS côté JS).

Les entrées Facebook encore au statut "à valider" ne sont PAS incluses :
rien de non confirmé n'apparaît jamais sur le site public.
"""
import csv
import json
import sys
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from icalendar import Calendar, Event

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
PLEINSOLEIL_ICS = DATA_DIR / "pleinsoleil.ics"
A_VALIDER_CSV = DATA_DIR / "a_valider.csv"
OUT_ICS = DATA_DIR / "calendrier.ics"
OUT_JSON = DATA_DIR / "evenements.json"

TZ = ZoneInfo("America/Toronto")
STATUTS_PUBLIABLES = {"approuvé", "approuve", "publié", "publie", "ok", "oui"}


def _ouvrir_csv_dict(chemin):
    """Ouvre un CSV en dict, en détectant automatiquement si le séparateur
    est une virgule ou un point-virgule (Excel en réglages français exporte
    souvent avec ';' — sans cette détection, tout le fichier serait lu comme
    une seule colonne et toutes les lignes seraient silencieusement ignorées)."""
    with open(chemin, encoding="utf-8", newline="") as f:
        entete = f.readline()
    delimiteur = ";" if entete.count(";") > entete.count(",") else ","
    return csv.DictReader(open(chemin, encoding="utf-8", newline=""), delimiter=delimiteur)


def charger_pleinsoleil() -> list[dict]:
    """Convertit les VEVENT de Plein Soleil en dicts génériques pour
    qu'on puisse les traiter uniformément avec les entrées Facebook."""
    if not PLEINSOLEIL_ICS.exists():
        print(f"! {PLEINSOLEIL_ICS} introuvable — lance d'abord fetch_pleinsoleil.py",
              file=sys.stderr)
        return []

    cal = Calendar.from_ical(PLEINSOLEIL_ICS.read_bytes())
    evenements = []
    for comp in cal.walk():
        if comp.name != "VEVENT":
            continue
        dtstart = comp.get("dtstart").dt
        dtend = comp.get("dtend").dt if comp.get("dtend") else None
        evenements.append({
            "titre": str(comp.get("summary", "")),
            "debut": dtstart,
            "fin": dtend,
            "lieu": str(comp.get("location", "")),
            "description": str(comp.get("description", "")),
            "source": "Plein Soleil",
            "lien": str(comp.get("url", "")) or None,
            "fiable": True,
        })
    return evenements


def parse_heure(valeur: str) -> time | None:
    """Accepte '19h', '19h30', '19:30', '7:30 PM' — best effort."""
    valeur = (valeur or "").strip().lower().replace("h", ":").rstrip(":")
    if not valeur:
        return None
    for fmt in ("%H:%M", "%H"):
        try:
            return datetime.strptime(valeur, fmt).time()
        except ValueError:
            continue
    return None


def charger_facebook_approuves() -> list[dict]:
    if not A_VALIDER_CSV.exists():
        return []

    evenements = []
    for ligne in _ouvrir_csv_dict(A_VALIDER_CSV):
        statut = (ligne.get("statut") or "").strip().lower()
        if statut not in STATUTS_PUBLIABLES:
            continue

        date_str = (ligne.get("date_detectee") or "").strip()
        if not date_str:
            print(
                f"! entrée approuvée sans date, ignorée : {ligne.get('titre')!r} "
                f"(remplis 'date_detectee' dans a_valider.csv)",
                file=sys.stderr,
            )
            continue

        try:
            jour = date.fromisoformat(date_str)
        except ValueError:
            print(f"! date invalide ignorée : {date_str!r}", file=sys.stderr)
            continue

        heure_debut = parse_heure(ligne.get("heure_debut", "")) or time(19, 0)
        heure_fin = parse_heure(ligne.get("heure_fin", ""))

        debut = datetime.combine(jour, heure_debut, tzinfo=TZ)
        fin = datetime.combine(jour, heure_fin, tzinfo=TZ) if heure_fin else None

        titre = ligne.get("titre") or "Danse extatique"
        dj = (ligne.get("dj_ou_animation") or "").strip()
        if dj:
            titre = f"{titre} — {dj}"

        evenements.append({
            "titre": titre,
            "debut": debut,
            "fin": fin,
            "lieu": (ligne.get("adresse") or "").strip(),
            "description": (ligne.get("texte") or "").strip(),
            "source": ligne.get("source", "Facebook"),
            "lien": ligne.get("lien") or None,
            "fiable": False,
        })
    return evenements


def ecrire_ics(evenements: list[dict]):
    cal = Calendar()
    cal.add("prodid", "-//quebec.extatic.dance//Calendrier fusionné//FR")
    cal.add("version", "2.0")

    for ev in evenements:
        e = Event()
        e.add("summary", ev["titre"])
        e.add("dtstart", ev["debut"])
        if ev["fin"]:
            e.add("dtend", ev["fin"])
        if ev["lieu"]:
            e.add("location", ev["lieu"])
        if ev["description"]:
            e.add("description", ev["description"])
        if ev["lien"]:
            e.add("url", ev["lien"])
        e.add("SOURCE", ev["source"], encode=0)
        cal.add_component(e)

    OUT_ICS.write_bytes(cal.to_ical())


def ecrire_json(evenements: list[dict]):
    def serialiser(ev):
        return {
            "titre": ev["titre"],
            "debut": ev["debut"].isoformat(),
            "fin": ev["fin"].isoformat() if ev["fin"] else None,
            "lieu": ev["lieu"],
            "description": ev["description"],
            "source": ev["source"],
            "lien": ev["lien"],
        }

    data = [serialiser(ev) for ev in evenements]
    OUT_JSON.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main():
    DATA_DIR.mkdir(exist_ok=True)

    ev_pleinsoleil = charger_pleinsoleil()
    ev_facebook = charger_facebook_approuves()
    tous = ev_pleinsoleil + ev_facebook

    # trie par date de début, en gérant les dates naïves vs. avec fuseau
    def cle_tri(ev):
        d = ev["debut"]
        if isinstance(d, datetime) and d.tzinfo is None:
            d = d.replace(tzinfo=TZ)
        return d
    tous.sort(key=cle_tri)

    ecrire_ics(tous)
    ecrire_json(tous)

    print(f"Plein Soleil (fiable, auto)  : {len(ev_pleinsoleil)} événements")
    print(f"Facebook (validés à la main) : {len(ev_facebook)} événements")
    print(f"Total publié                 : {len(tous)} événements")
    print(f"Écrit : {OUT_ICS}")
    print(f"Écrit : {OUT_JSON}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Surveille les pages/groupes Facebook listés dans data/sources.yml via des
flux RSS générés par un service tiers (RSS.app, FetchRSS, etc.) — Facebook
ne publie plus de RSS natif, donc ce pont est nécessaire.

Pour chaque nouveau post qui ressemble à une annonce d'événement (présence
de mots-clés + une date détectable en français), une ligne est ajoutée à
data/a_valider.csv avec le statut "à valider". Rien n'est jamais publié
automatiquement à partir de Facebook : un humain doit relire, corriger et
valider chaque entrée avant qu'elle apparaisse sur le site (voir README).

Ce script ne duplique pas les entrées déjà vues : il garde en mémoire
(data/facebook_vus.txt) les identifiants des posts déjà traités.
"""
import csv
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import dateparser
import feedparser
import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
SOURCES_FILE = DATA_DIR / "sources.yml"
OUTPUT_CSV = DATA_DIR / "a_valider.csv"
SEEN_FILE = DATA_DIR / "facebook_vus.txt"

_MOIS_FR = (
    "janvier|février|fevrier|mars|avril|mai|juin|juillet|août|aout|"
    "septembre|octobre|novembre|décembre|decembre"
)
# Repère "12 octobre" ou "12 octobre 2026" — un jour suivi d'un nom de mois
# en toutes lettres, avec année optionnelle. On ne s'appuie PAS sur
# dateparser.search_dates pour scanner le texte libre : dans nos tests, il
# échoue silencieusement dès qu'une heure ("à 19h") suit la date dans la
# même phrase, et il arrive qu'il "détecte" une date à partir de mots
# relatifs vagues comme "hier" ou "bientôt", ce qui produirait une fausse
# date dans la file de validation. Une regex ciblée sur le format de date
# explicite, suivie d'un parsing du seul fragment trouvé, est plus fiable
# pour ce cas d'usage.
_DATE_RE = re.compile(rf"\d{{1,2}}\s+(?:{_MOIS_FR})(?:\s+\d{{4}})?", re.IGNORECASE)

# Repère "Dj <Nom>" / "DJ <Nom>" — on exige que le nom capturé commence par
# une majuscule (signal de nom propre), peu importe la casse de "dj"
# lui-même, pour éviter de capturer un adjectif comme dans "une dj
# internationale" (observé dans un vrai post lors des tests). C'est une
# SUGGESTION à vérifier, pas une valeur fiable — d'où la colonne séparée
# `dj_detecte` dans le CSV, distincte de `dj_ou_animation` que l'humain
# remplit lui-même.
_DJ_RE = re.compile(r"\b[Dd][Jj]\s+(?:de\s+ce\s+\w+\s+)?([A-ZÀ-Þ][\wÀ-ÿ.'-]*)")


def detecter_dj(texte: str) -> str:
    m = _DJ_RE.search(texte)
    return m.group(1).rstrip(".,!;:") if m else ""

CSV_FIELDS = [
    "id",
    "source",
    "ville",
    "titre",
    "texte",
    "date_detectee",
    "publie_le",
    "dj_detecte",
    "lien",
    "statut",
    "vu_le",
    # Colonnes à remplir à la main lors de la validation (voir README) —
    # le script ne les devine jamais, elles restent vides à la création.
    "heure_debut",
    "heure_fin",
    "adresse",
    "dj_ou_animation",
    "notes_validation",
]


def charger_config():
    with open(SOURCES_FILE, encoding="utf-8") as f:
        return yaml.safe_load(f)


def charger_ids_vus() -> set[str]:
    if not SEEN_FILE.exists():
        return set()
    return set(SEEN_FILE.read_text(encoding="utf-8").splitlines())


def enregistrer_id_vu(post_id: str):
    with open(SEEN_FILE, "a", encoding="utf-8") as f:
        f.write(post_id + "\n")


def ressemble_a_un_evenement(texte: str, mots_cles: dict, date_trouvee: bool) -> bool:
    """Un post est retenu s'il contient un mot-clé "fort" (sans ambiguïté,
    ex. "danse extatique"), ou un mot-clé "faible" (ex. un jour de la
    semaine) combiné à une date explicite détectée dans le texte — ça
    évite de remplir la file de validation avec des posts qui mentionnent
    juste un jour en passant ("merci pour samedi dernier!")."""
    texte_lower = texte.lower()
    if any(mot.lower() in texte_lower for mot in mots_cles.get("forts", [])):
        return True
    if date_trouvee and any(
        mot.lower() in texte_lower for mot in mots_cles.get("faibles", [])
    ):
        return True
    return False


def detecter_date(texte: str, date_publication: datetime | None) -> str:
    """Essaie d'extraire une date probable du texte du post (en français),
    au format "12 octobre" ou "12 octobre 2026". Retourne une chaîne ISO
    si trouvée, sinon une chaîne vide — dans ce cas la date devra être
    remplie à la main lors de la validation.

    Important : on résout les dates sans année ("17 juin", "demain") par
    rapport à la date de PUBLICATION du post, pas par rapport à
    aujourd'hui. Sinon, un vieux post encore visible dans le flux ("demain
    mercredi 17 juin", publié en juin 2026) se ferait réinterpréter comme
    une date future par rapport à la date d'exécution du script (ex.
    "17 juin 2027") — ce bug a été observé concrètement lors des tests."""
    m = _DATE_RE.search(texte)
    if not m:
        return ""
    base = date_publication or datetime.now(timezone.utc)
    base_minuit = base.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)

    # On résout d'abord la date "telle quelle" dans l'année de publication
    # (current_period, pas future) : PREFER_DATES_FROM="future" pousse
    # systématiquement une date tombant le jour même à l'année suivante
    # (ex. post du 5 septembre disant "samedi le 5 septembre" → calculé
    # comme un 5 septembre "pas encore arrivé" par rapport à l'heure exacte
    # de publication, donc roulé à l'année d'après) — comportement observé
    # concrètement lors des tests, et clairement faux ici.
    dt = dateparser.parse(
        m.group(0),
        languages=["fr"],
        settings={"PREFER_DATES_FROM": "current_period", "RELATIVE_BASE": base_minuit},
    )
    if dt is None:
        return ""

    # Si la date obtenue tombe strictement AVANT la publication (ex. post
    # de septembre qui parle du "20 février" — trop tôt dans la même
    # année pour être passé inaperçu), c'est presque certainement une
    # référence à la prochaine occurrence, donc on avance d'un an.
    if dt.date() < base_minuit.date():
        dt = dt.replace(year=dt.year + 1)

    return dt.date().isoformat()


def charger_csv_existant() -> list[dict]:
    if not OUTPUT_CSV.exists():
        return []
    with open(OUTPUT_CSV, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def ecrire_csv(lignes: list[dict]):
    with open(OUTPUT_CSV, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for ligne in lignes:
            writer.writerow(ligne)


def main():
    DATA_DIR.mkdir(exist_ok=True)
    config = charger_config()
    mots_cles = config.get("mots_cles_evenement", [])
    sources = config.get("facebook_sources", [])

    ids_vus = charger_ids_vus()
    lignes_existantes = charger_csv_existant()
    nouvelles_lignes = []

    n_sources_actives = 0
    n_nouveaux = 0

    for source in sources:
        flux_url = (source.get("flux_rss") or "").strip()
        if not flux_url or flux_url.startswith("A_CONFIGURER"):
            print(f"  (ignoré, pas de flux RSS configuré) {source['nom']}")
            continue

        n_sources_actives += 1
        print(f"Lecture du flux : {source['nom']} ...")
        try:
            feed = feedparser.parse(flux_url)
        except Exception as exc:  # noqa: BLE001
            print(f"  ! échec de lecture du flux : {exc}", file=sys.stderr)
            continue

        if feed.bozo and not feed.entries:
            print(f"  ! flux illisible ou vide pour {source['nom']}", file=sys.stderr)
            continue

        for entry in feed.entries:
            post_id = entry.get("id") or entry.get("link")
            if not post_id or post_id in ids_vus:
                continue

            titre = entry.get("title", "").strip()
            texte = entry.get("summary", "") or entry.get("description", "")
            texte_complet = f"{titre}\n{texte}".strip()
            lien = entry.get("link", "")

            # Un lien vers un véritable événement Facebook (/events/...) est
            # toujours pertinent, même sans texte à côté : contrairement à
            # un post normal, la page d'événement elle-même contient
            # presque toujours la date, l'heure et le lieu structurés — on
            # ne peut pas la scraper depuis ce script (Facebook bloque les
            # requêtes non authentifiées), mais on ne veut surtout pas la
            # perdre silencieusement comme le faisait une version
            # précédente du filtre par mots-clés.
            est_lien_evenement = "/events/" in lien

            date_publication = None
            if entry.get("published_parsed"):
                import calendar as _cal
                date_publication = datetime.fromtimestamp(
                    _cal.timegm(entry["published_parsed"]), tz=timezone.utc
                )

            date_detectee = detecter_date(texte_complet, date_publication)

            if not est_lien_evenement and not ressemble_a_un_evenement(
                texte_complet, mots_cles, bool(date_detectee)
            ):
                # on marque quand même comme "vu" pour ne pas le re-scanner
                # indéfiniment, mais on ne l'ajoute pas au fichier à valider
                enregistrer_id_vu(post_id)
                continue

            if date_detectee and date_detectee < datetime.now(timezone.utc).date().isoformat():
                # la date détectée est déjà passée (post au sujet d'un
                # événement qui a déjà eu lieu) — pas utile pour un
                # calendrier d'événements à venir, on ignore silencieusement
                enregistrer_id_vu(post_id)
                continue

            texte_csv = texte_complet.replace("\n", " ")[:500]
            if est_lien_evenement and not texte:
                texte_csv = (
                    "(lien vers une page événement Facebook — ouvre le lien "
                    "pour voir la date, l'heure et l'adresse complètes)"
                )

            nouvelles_lignes.append({
                "id": post_id,
                "source": source["nom"],
                "ville": source.get("ville", ""),
                "titre": titre or "(sans titre)",
                "texte": texte_csv,
                "date_detectee": date_detectee,
                "publie_le": date_publication.date().isoformat() if date_publication else "",
                "dj_detecte": detecter_dj(texte_complet),
                "lien": lien,
                "statut": "à valider",
                "vu_le": datetime.now(timezone.utc).date().isoformat(),
            })
            enregistrer_id_vu(post_id)
            n_nouveaux += 1

    toutes_les_lignes = lignes_existantes + nouvelles_lignes
    ecrire_csv(toutes_les_lignes)

    print(f"\n{n_sources_actives} source(s) Facebook active(s) sur {len(sources)} configurée(s)")
    print(f"{n_nouveaux} nouveau(x) post(s) potentiellement pertinent(s) ajouté(s) à {OUTPUT_CSV}")
    if n_sources_actives == 0:
        print(
            "\nAucune source Facebook n'est encore configurée : ajoute les URLs "
            "de flux RSS dans data/sources.yml (voir le README).",
        )


if __name__ == "__main__":
    main()

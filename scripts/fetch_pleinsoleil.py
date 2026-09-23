#!/usr/bin/env python3
"""
Importe automatiquement tous les événements du calendrier Plein Soleil
(pleinsoleil.club), une source Squarespace qui expose un lien ICS pour
chaque événement individuel.

Étapes :
1. Télécharge la page calendrier (et ses pages suivantes s'il y en a).
2. Repère chaque lien de la forme /calendar/<slug>?format=ical.
3. Télécharge chacun de ces flux ICS individuels.
4. Fusionne tous les événements dans un seul fichier data/pleinsoleil.ics.

Ces événements sont considérés fiables (source structurée, pas de
supposition sur le texte) et n'ont pas besoin de validation manuelle.
"""
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from icalendar import Calendar

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; quebec-extatic-dance-bot/1.0; "
                  "+https://quebec.extatic.dance)"
}

ICS_LINK_RE = re.compile(r"/calendar/[^\"'?]+\?format=ical")


def fetch_calendar_page_urls(base_url: str, session: requests.Session) -> set[str]:
    """Récupère les URLs de tous les liens ICS trouvés sur la page calendrier."""
    resp = session.get(base_url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    resp.encoding = resp.encoding or "utf-8"
    html = resp.content.decode("utf-8", errors="replace")
    soup = BeautifulSoup(html, "html.parser")

    ics_urls = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if ICS_LINK_RE.search(href):
            ics_urls.add(urljoin(base_url, href))

    # filet de sécurité : chercher aussi directement dans le HTML brut,
    # au cas où certains liens seraient injectés par du JS déjà rendu
    # côté serveur (Squarespace le fait souvent)
    for match in ICS_LINK_RE.findall(html):
        ics_urls.add(urljoin(base_url, match))

    return ics_urls


def download_and_merge(ics_urls: set[str], session: requests.Session) -> Calendar:
    merged = Calendar()
    merged.add("prodid", "-//quebec.extatic.dance//Plein Soleil import//FR")
    merged.add("version", "2.0")

    n_ok, n_fail = 0, 0
    for url in sorted(ics_urls):
        try:
            resp = session.get(url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            # on passe les bytes bruts : Calendar.from_ical gère lui-même
            # l'encodage déclaré dans le flux ICS (requests devine parfois
            # mal l'encodage texte, ce qui corrompt les accents)
            cal = Calendar.from_ical(resp.content)
            for component in cal.walk():
                if component.name == "VEVENT":
                    # Marque la source pour traçabilité
                    component.add("SOURCE", "Plein Soleil", encode=0)
                    merged.add_component(component)
            n_ok += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  ! échec sur {url}: {exc}", file=sys.stderr)
            n_fail += 1

    print(f"Plein Soleil : {n_ok} événements importés, {n_fail} échecs")
    return merged


def main():
    DATA_DIR.mkdir(exist_ok=True)
    session = requests.Session()

    base_url = "https://www.pleinsoleil.club/"
    print(f"Lecture de {base_url} ...")
    ics_urls = fetch_calendar_page_urls(base_url, session)
    print(f"  {len(ics_urls)} liens ICS trouvés")

    if not ics_urls:
        print("Aucun lien ICS trouvé — la structure du site a peut-être changé.",
              file=sys.stderr)
        sys.exit(1)

    merged = download_and_merge(ics_urls, session)

    out_path = DATA_DIR / "pleinsoleil.ics"
    out_path.write_bytes(merged.to_ical())
    print(f"Écrit : {out_path}")


if __name__ == "__main__":
    main()

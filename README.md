# Agrégateur de calendrier — quebec.extatic.dance

Ce dossier contient le pipeline qui collecte automatiquement les dates de
danse extatique au Québec depuis plusieurs sources, et produit un
calendrier prêt à afficher sur le site.

## Vue d'ensemble

```
scripts/fetch_pleinsoleil.py   → data/pleinsoleil.ics       (automatique, fiable)
scripts/fetch_facebook_rss.py  → data/a_valider.csv          (nécessite validation manuelle)
scripts/merge_calendar.py      → data/calendrier.ics          (sortie finale : .ics)
                                → data/evenements.json         (sortie finale : JSON pour le site)
```

- **Plein Soleil** (Montréal) expose un lien ICS pour chaque événement.
  Ces événements sont importés et publiés automatiquement, sans relecture
  humaine — la source est structurée, il n'y a rien à deviner.
- **Facebook** (DEQ, Danse Extatique Montréal, Danser à Sherbrooke, OnDanse
  Val-David, Ecstatic Dance Mayhem) est surveillé via des flux RSS générés
  par un service tiers (Facebook ne publie plus de RSS natif). Les posts
  qui ressemblent à une annonce d'événement sont ajoutés à
  `data/a_valider.csv` avec le statut **"à valider"**. Rien de cette
  source n'apparaît sur le site tant qu'un humain n'a pas relu, complété
  et approuvé l'entrée. C'est voulu : les posts Facebook manquent souvent
  de détails (heure exacte, adresse précise, DJ) et le texte est parfois
  ambigu.
- **Sources sans flux automatisable** (`sources_manuelles` dans
  `data/sources.yml`, ex. PrimaStar Productions / TicketTailor) : sites
  protégés contre le scraping automatisé (Cloudflare, etc.) qui n'exposent
  ni ICS public ni RSS. Vérifiées ponctuellement plutôt que chaque nuit —
  voir la section dédiée plus bas.

## Encourager les organisateurs à exposer un flux ICS public

C'est de loin la façon la plus fiable d'ajouter une nouvelle source : une
plateforme qui expose de l'ICS public par événement (comme le fait Plein
Soleil sur Squarespace, ou Eventbrite) permet une importation automatique
sans aucune validation humaine, sans risque de blocage anti-robot, et sans
jamais mal interpréter une date. À l'inverse, chaque source qui n'expose
que du texte libre (Facebook) ou qui bloque le scraping (TicketTailor/
Cloudflare) demande soit une validation manuelle continue, soit une
vérification ponctuelle au navigateur — donc plus de friction pour tout le
monde. Si tu as l'occasion d'en parler aux organisateurs que tu connais :
la plupart des plateformes de billetterie sérieuses (Eventbrite,
Squarespace, Google Calendar public) exposent déjà de l'ICS nativement,
il s'agit souvent juste de le rendre visible/public plutôt que de le
construire.

## Installation initiale

```bash
pip install -r requirements.txt
```

## Configurer les flux RSS Facebook (une fois)

Facebook ne fournit plus de flux RSS pour ses pages. Un service tiers doit
faire le pont :

1. Va sur [rss.app](https://rss.app) (ou [fetchrss.com](https://fetchrss.com))
2. Colle l'URL de la page ou du groupe Facebook
3. Clique "Generate" — tu obtiens une URL de flux RSS (ex.
   `https://rss.app/feeds/xxxxx.xml`)
4. Ouvre `data/sources.yml` et remplace `"A_CONFIGURER"` par cette URL,
   pour la bonne source, dans `flux_rss:`
5. Répète pour chaque page/groupe

**Fréquence de rafraîchissement** : dépend du forfait RSS.app/FetchRSS
choisi. Le forfait gratuit suffit largement pour un usage quotidien (le
workflow automatique tourne 1x/jour, voir plus bas).

**Cas particulier — groupes Facebook** : `OnDanse Val-David` est un
*groupe* (pas une page). RSS.app et FetchRSS savent lire certains groupes
publics, mais pas tous — si la génération du flux échoue pour cette
source, le script l'ignorera simplement (aucune erreur), et il faudra que
quelqu'un ajoute ces dates à la main via le formulaire de soumission (à
construire séparément).

## Lancer le pipeline manuellement

```bash
python3 scripts/fetch_pleinsoleil.py
python3 scripts/fetch_facebook_rss.py
python3 scripts/merge_calendar.py
```

Le résultat final est dans `data/calendrier.ics` (à brancher sur le site,
ou à importer dans Google Calendar) et `data/evenements.json` (à
consommer directement en JS sur le site statique).

## Valider une entrée Facebook

1. Ouvre `data/a_valider.csv` (dans Excel, Google Sheets, ou un éditeur de
   texte — c'est un fichier CSV standard)
2. Pour chaque ligne avec le statut `à valider` :
   - Vérifie le texte original et le lien vers le post (la colonne
     `publie_le` indique quand le post a été publié — utile pour juger si
     une date sans année précise est plausible)
   - Complète les colonnes `heure_debut`, `heure_fin`, `adresse`,
     `dj_ou_animation` si l'information est disponible
   - Corrige `date_detectee` si le script s'est trompé, ou remplis-la si
     elle est vide (format `AAAA-MM-JJ`) — le script ne détecte que les
     dates explicites ("12 octobre"), pas les jours de semaine seuls
     ("samedi") ni les dates relatives ("dans deux semaines")
   - Si tout est bon, change `statut` à `approuvé`
   - Si ce n'est pas un vrai événement (fausse détection), change
     `statut` à `rejeté` (ou laisse tel quel — seul `approuvé`/`publié`
     est repris dans le calendrier final)
3. Relance `python3 scripts/merge_calendar.py` (ou attends le prochain
   passage automatique) pour que l'entrée apparaisse sur le site

### Pourquoi l'heure, l'adresse et le DJ ne sont pas déjà remplis

Le flux RSS (généré par RSS.app) ne contient que le **texte tronqué** de
chaque post (~150 caractères, coupé par "..."). Ce n'est pas une limite du
script : c'est ce que le flux RSS.app expose. Dans le texte tronqué, le
nom du DJ apparaît parfois assez tôt pour être visible — dans ce cas, la
colonne `dj_detecte` propose une suggestion automatique (à vérifier
avant de la recopier dans `dj_ou_animation`). L'heure et l'adresse
complètes sont presque toujours coupées.

**Cas particulier — liens vers un vrai événement Facebook** (`/events/...`,
pas juste un post) : la page d'événement elle-même contient presque
toujours la date, l'heure et l'adresse structurées. Le script ne peut pas
aller les chercher tout seul — une requête automatisée vers Facebook sans
navigateur connecté se fait bloquer (page d'erreur, testé concrètement).
Mais si tu me demandes d'aller vérifier un lien précis pendant qu'on
discute, je peux ouvrir la page avec mon navigateur et t'en extraire les
détails complets en quelques secondes. Ce n'est pas quelque chose que
l'automatisation nocturne (GitHub Actions) peut faire elle-même — ça reste
une étape ponctuelle, sur demande.

## Vérifier les sources manuelles (TicketTailor, etc.)

Les sources listées sous `sources_manuelles` dans `data/sources.yml`
(comme PrimaStar Productions) ne peuvent pas être lues par un script
automatisé simple — leur site bloque les requêtes non émises par un vrai
navigateur. Pour les mettre à jour :

1. Demande à Claude, dans une conversation, de "vérifier les sources
   manuelles de quebec-extatic-dance" (ou donne directement le lien)
2. Claude ouvre la page avec son navigateur, relève les événements à
   venir (date, heure, DJ, lieu général) et les ajoute à
   `data/a_valider.csv`
3. Complète/valide ces entrées comme n'importe quelle entrée Facebook
   (voir plus haut)

Il n'y a pas de fréquence automatique pour cette étape — à faire
ponctuellement (ex. une fois par mois), ou chaque fois que tu sais qu'un
organisateur a publié de nouvelles dates.

## Automatisation (GitHub Actions)

Le fichier `.github/workflows/mise-a-jour-calendrier.yml` exécute tout le
pipeline une fois par jour (9h05 UTC) et commit les fichiers `data/`
mis à jour directement dans le dépôt. Aucune configuration additionnelle
n'est nécessaire côté GitHub — le token par défaut du workflow a les
droits d'écriture (`permissions: contents: write` dans le fichier).

Pour déclencher une exécution manuelle : onglet **Actions** du dépôt
GitHub → "Mise à jour du calendrier" → **Run workflow**.

**Important** : comme `data/a_valider.csv` est commité automatiquement à
chaque passage, si tu valides des entrées entre deux exécutions
automatiques, assure-toi de faire `git pull` avant d'éditer le fichier
localement (pour éviter d'écraser une validation par une exécution
concurrente). En pratique, comme le script ajoute seulement de nouvelles
lignes sans jamais modifier les lignes existantes, les conflits devraient
être rares.

## Brancher sur le site

Le site statique peut lire `data/evenements.json` directement (format
simple, un objet par événement avec `titre`, `debut`, `fin`, `lieu`,
`description`, `source`, `lien`) pour générer sa page calendrier, ou
utiliser `data/calendrier.ics` si tu préfères une librairie de calendrier
JS qui consomme de l'ICS directement.

## Prochaines étapes possibles

- Formulaire de soumission communautaire (Tally/Airtable) pour les
  organisateurs qui veulent ajouter leurs dates directement, sans
  dépendre du scraping Facebook
- Notification automatique (email/Slack) quand une nouvelle entrée
  atterrit dans `a_valider.csv`, pour ne pas avoir à vérifier
  manuellement
- Ajouter d'autres sources ICS si d'autres organisateurs migrent vers
  des plateformes structurées (Eventbrite expose aussi de l'ICS par
  événement, à vérifier)

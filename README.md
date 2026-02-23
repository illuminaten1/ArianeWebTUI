# ArianeWeb — Extraction de jurisprudences

Interface **terminal (TUI)** pour rechercher et récupérer les décisions de
jurisprudence (CE et CAA) depuis
[ArianeWeb](https://www.conseil-etat.fr/arianeweb/#/recherche).

## Prérequis

Python 3.10+

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Lancement

```bash
# Interface interactive
python3 arianeweb.py

# Interface avec requête pré-remplie
python3 arianeweb.py "89-271"
```

## Interface

```
┌─────────────────────────── ArianeWeb ──────────────────────────────┐
│  Requête : [_________________________] [Rechercher] [ ] Méta seul. │
├────────────────────────────────────────────────────────────────────┤
│ ▸ Résultats                                                        │
│ ────────────────────────────────────────────────────────────────── │
│  Type │ Numéro  │ Date       │ Juridiction         │ URL           │
│  CE   │ 461871  │ 06/01/2023 │ Conseil d'État      │ https://…     │
│  CAA  │ 22NT…   │ 14/03/2022 │ CAA de Nantes       │ https://…     │
├────────────────────────────────────────────────────────────────────┤
│ ▸ Journal                                                          │
│  [CE] 55 résultat(s)                                               │
│    1/55 CE 461871 (06/01/2023) ✓ 4 823 car.                        │
└──────────────── F5 Rechercher • Ctrl+S Exporter • Q Quitter ───────┘
```

## Raccourcis clavier

### Interface principale

| Touche      | Action                                        |
|-------------|-----------------------------------------------|
| `F5`        | Lancer la recherche                           |
| `Entrée`    | Lancer la recherche (depuis le champ)         |
| `Échap`     | Annuler la recherche en cours                 |
| `Ctrl+S`    | Exporter les résultats en JSON                |
| `Q`         | Quitter                                       |

### Visualisateur de décision

| Touche          | Action                         |
|-----------------|--------------------------------|
| `Entrée`        | Ouvrir la décision sélectionnée |
| `+` / `=`       | Agrandir (zoom +)              |
| `-`             | Réduire (zoom −)               |
| `0`             | Zoom normal                    |
| `↑ ↓ PgUp PgDn` | Défiler dans le texte          |
| `Échap` / `Q`  | Fermer                         |

## Syntaxe de recherche

La syntaxe est celle d'ArianeWeb (moteur Sinequa).

| Syntaxe                    | Effet                                                      |
|----------------------------|------------------------------------------------------------|
| `terme1 terme2`            | Les deux termes (ET implicite)                             |
| `terme1 ET terme2`         | Les deux termes                                            |
| `terme1 OU terme2`         | L'un ou l'autre (ou les deux)                              |
| `terme1 SAUF terme2`       | `terme1` sans `terme2` (mot exact)                         |
| `"expression exacte"`      | Recherche l'expression entre guillemets mot pour mot       |
| `voi?`                     | Joker sur un seul caractère (`voie`, `voix`, `voir`…)      |
| `t*t`                      | Joker sur 0 à n caractères (`toit`, `totalement`…)         |

> Les opérateurs ET, OU, SAUF ne sont pas sensibles à la casse.
> La recherche n'est pas sensible à la casse ni aux accents.

## Modes de récupération

### Textes intégraux (défaut)

Après la collecte des métadonnées, une confirmation est demandée avant le
téléchargement des textes. Il est possible d'annuler à tout moment avec `Échap`.

### Métadonnées seulement

Cochez **Métadonnées seulement** pour ne récupérer que type, numéro, date et URL,
sans télécharger les textes. Beaucoup plus rapide.

Depuis le visualisateur, un bouton **⬇ Télécharger le texte** permet de récupérer
le texte d'une décision individuelle à la demande.

## Export JSON

`Ctrl+S` génère un fichier `resultats_<requête>.json` dans le répertoire courant.

```json
{
  "requete": "89-271",
  "date_extraction": "2026-02-23 11:14:00",
  "total": 55,
  "decisions": [
    {
      "type": "CE",
      "juridiction": "Conseil d'État",
      "numero": "461871",
      "date": "06/01/2023",
      "url": "https://www.conseil-etat.fr/fr/arianeweb/CE/decision/…",
      "texte": "Conseil d'État\n\nN° 461871\n…"
    }
  ]
}
```

| Champ         | Description                                                   |
|---------------|---------------------------------------------------------------|
| `type`        | `CE` (Conseil d'État) ou `CAA` (Cour administrative d'appel) |
| `juridiction` | Nom complet de la juridiction                                 |
| `numero`      | Numéro de la décision                                         |
| `date`        | Date au format `JJ/MM/AAAA`                                   |
| `url`         | Lien direct vers la décision sur ArianeWeb                    |
| `texte`       | Texte intégral (absent en mode métadonnées)                   |

Les décisions sont triées par date décroissante.

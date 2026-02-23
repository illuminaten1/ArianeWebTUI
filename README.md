# ArianeWeb — Extraction de jurisprudences

Interface **terminal (TUI)** pour récupérer automatiquement les décisions de
jurisprudence (CE et CAA) depuis
[ArianeWeb](https://www.conseil-etat.fr/arianeweb/#/recherche).

## Prérequis

Python 3.10+ et [Textual](https://textual.textualize.io/) (interface TUI).

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install textual
```

## Lancement

```bash
# Interface interactive (recherche vide)
python3 arianeweb.py

# Interface avec requête pré-remplie
python3 arianeweb.py "89-271"
```

## Interface

```
┌─────────────────────────── ArianeWeb ──────────────────────────────┐
│  Requête : [_________________________] [Rechercher] [ ] Méta seul. │
├────────────────────────────────────────────────────────────────────┤
│ ▸ Résultats                                                         │
│ ─────────────────────────────────────────────────────────────────  │
│  Type │ Numéro  │ Date       │ Juridiction         │ URL           │
│  CE   │ 461871  │ 06/01/2023 │ Conseil d'État      │ https://…     │
│  CAA  │ 22NT… │ 14/03/2022 │ CAA de Nantes       │ https://…     │
├────────────────────────────────────────────────────────────────────┤
│ ▸ Journal                                                           │
│  [CE] 55 résultat(s)                                                │
│    1/55 CE 461871 (06/01/2023) ✓ 4 823 car.                        │
└──────────────────────── F5 Rechercher • Ctrl+S Exporter • Q Quit ──┘
```

### Raccourcis clavier

| Touche   | Action                         |
|----------|--------------------------------|
| `F5`     | Lancer la recherche            |
| `Entrée` | Lancer la recherche (dans le champ) |
| `Ctrl+S` | Exporter les résultats en JSON |
| `Échap`  | Annuler la recherche en cours  |
| `Q`      | Quitter                        |

### Option « Métadonnées seulement »

Cochez la case pour ne récupérer que les métadonnées (type, numéro, date, URL)
sans télécharger les textes intégraux. Beaucoup plus rapide.

## Résultat JSON exporté

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

### Champs

| Champ        | Description                                          |
|--------------|------------------------------------------------------|
| `type`       | `CE` (Conseil d'État) ou `CAA` (Cour administrative d'appel) |
| `juridiction`| Nom complet de la juridiction                        |
| `numero`     | Numéro de la décision                                |
| `date`       | Date au format `JJ/MM/AAAA`                          |
| `url`        | Lien direct vers la décision sur ArianeWeb           |
| `texte`      | Texte intégral (absent en mode métadonnées)          |

Les décisions sont triées par date décroissante.

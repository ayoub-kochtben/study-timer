# Study Timer

Chronomètre d'étude local : la webcam décide si le temps compte.

## Règle de comptage

Le chrono compte si un visage est détecté **et** qu'aucun objet de la
liste noire (le téléphone au départ) n'est tenu en main. Un changement
d'état n'est appliqué qu'après `frames_to_change_state` images
consécutives allant dans le même sens (anti-clignotement). Aucune image
n'est jamais enregistrée : seuls des intervalles de temps sont stockés
dans `data/study_timer.db`.

## Lancement

```bat
.venv\Scripts\python main.py
```

Si vous partez de zéro :

```bat
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

Les modèles se téléchargent automatiquement au premier lancement
(YOLOv8n ; les deux fichiers MediaPipe sont dans `models/`, déjà
téléchargés). Tout tourne à 100 % en local.

## Configuration — `config.json`

Créé au premier lancement, modifiable à la main :

- `blacklist_classes` : classes YOLO interdites. Par défaut
  `["cell phone"]` ; ajoutez tout label COCO (`book`, `laptop`…).
- `frames_to_change_state` : images consécutives exigées pour un
  changement d'état (3 par défaut ; mettre 1 pour un arrêt instantané).
- `analysis_fps` : cadence d'analyse de la webcam.
- `hand_overlap_threshold` / `hand_overlap_margin` : sensibilité de la
  détection « objet en main ».

## Structure

- `camera.py` — capture + thread d'analyse (hors interface)
- `detection.py` — visage MediaPipe, mains MediaPipe, YOLOv8n
- `engine.py` — machine à états pure (compter ou pas, anti-clignotement)
- `database.py` — intervalles SQLite + statistiques
- `ui_widget.py` — widget flottant (voyant, temps du jour, boutons)
- `ui_stats.py` — fenêtre statistiques (jour / semaine / mois + série)
- `main.py` — câblage de tout le monde

## Tests

```bat
.venv\Scripts\python -m pytest tests\ -q
```

Le moteur et la base sont entièrement testés automatiquement ; la
détection et l'interface se vérifient manuellement (voir ci-dessous).

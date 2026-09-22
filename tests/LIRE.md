# Les essais

| Fichier | Lance | Couvre |
|---|---|---|
| `inverse.js` | `node tests/inverse.js template/_app/app.html` | vitesse signée, lecture inversée, découpe et rognage à l'envers (26) |
| `rangement.js` | `node tests/rangement.js template/_app/app.html` | dossiers virtuels : créer, ranger, renommer, effacer (18) |
| `serveur_essais.py` | `python tests/serveur_essais.py "<racine>"` | le vrai serveur d'une bibliothèque installée, sur ses vrais rushes (20) |
| `installeur_essais.py` | `python tests/installeur_essais.py` | analyse, installation et mise à jour des trois genres de bibliothèque, racine à onglets, mise en ligne (172) |
| `maj_editeur_essais.py` | `python tests/maj_editeur_essais.py` | la mise à jour de Library Editor lui-même, sur une copie et un dépôt local (10) |

Les deux premiers **extraient le code d'`app.html`** par des ancres de texte : ils éprouvent le fichier livré, pas une copie.

`serveur_essais.py` lance le serveur de la bibliothèque sur son port, **sauvegarde puis restaure** le rangement,
et **échoue si un seul fichier de rushes a changé** (nom, taille ou date). Il neutralise `webbrowser.open` pour ne pas
ouvrir d'onglet.

`installeur_essais.py` fabrique ses propres données (ffmpeg) dans un dossier temporaire et détourne les réglages de
l'application vers ce dossier : il n'écrit jamais ailleurs. `maj_editeur_essais.py` demande une application construite
(`python source/build.py`) ; il en copie une, la met à jour depuis un dépôt local (`file://`), et ne remplace qu'un
dossier d'essai.

Pour éprouver toute la chaîne de mise à jour sans réseau : `LIBRARY_EDITOR_DEPOT=file:///…/Library-Editor/` — le dépôt
local tient alors lieu de GitHub.

Node et Python 3.8+ suffisent. Aucune dépendance.

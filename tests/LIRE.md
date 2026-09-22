# Les essais

| Fichier | Lance | Couvre |
|---|---|---|
| `inverse.js` | `node tests/inverse.js template/_app/app.html` | vitesse signée, lecture inversée, découpe et rognage à l'envers (26) |
| `rangement.js` | `node tests/rangement.js template/_app/app.html` | dossiers virtuels : créer, ranger, renommer, effacer (18) |
| `serveur_essais.py` | `python tests/serveur_essais.py "<racine>"` | le vrai serveur d'une bibliothèque installée, sur ses vrais rushes (19) |

Les deux premiers **extraient le code d'`app.html`** par des ancres de texte : ils éprouvent le fichier livré, pas une copie.

`serveur_essais.py` lance le serveur de la bibliothèque sur son port, **sauvegarde puis restaure** le rangement,
et **échoue si un seul fichier de rushes a changé** (nom, taille ou date). Il neutralise `webbrowser.open` pour ne pas
ouvrir d'onglet.

Node et Python 3.8+ suffisent. Aucune dépendance.

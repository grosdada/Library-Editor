# `monteur.py` — monter dans une bibliothèque sans passer par la page

Un outil en ligne de commande **et** un serveur MCP, dans le même fichier. Il lit les catalogues d'une
bibliothèque vidéo et y **écrit des séquences**. Toute séquence écrite ici porte le préfixe **`claude - `** :
dans la liste des séquences, on voit d'un coup d'œil ce qui ne vient pas de David.

## Comment il trouve les bibliothèques

`%APPDATA%\Library Editor\reglages.json` → `recents` : chemin, titre, genre, port de tout ce que Library
Editor a créé ou ouvert. Un chemin complet marche aussi, pour une bibliothèque qui n'y serait pas.

Aucun serveur n'est démarré, aucun port n'est ouvert : le `_app/serveur.py` **de la bibliothèque visée** est
importé comme module (il n'est que configuration tant qu'on n'appelle pas `demarrer()`) et ce sont **ses**
fonctions qui disent où sont les catalogues et les séquences. Une seule vérité sur les chemins : la sienne.

## En ligne de commande

```
python outils/monteur.py bibliotheques
python outils/monteur.py projets   "EP-06"
python outils/monteur.py catalogue "EP-06" --cherche roubax        # toute la bibliothèque
python outils/monteur.py catalogue "EP-06" --projet bambozoo-Render --genre video
python outils/monteur.py sequences "EP-06"
python outils/monteur.py lire      "EP-06" --nom "claude - ouverture"
python outils/monteur.py ecrire    "EP-06" plan.json --nom "ouverture"
```

`--json` rend la réponse brute. Chaque commande refuse en une phrase quand la demande est ambiguë
(deux rushes portent le même morceau de nom, projet inconnu, séquence déjà là…).

## Le plan

```json
{
 "theme": "ouverture : trois plans, nappe dessous",
 "format": [1920, 1080], "fps": 24,
 "plans": [
  {"rush": "plan 01", "piste": "V1", "sortie": 1.8, "fondu_in": 0.4},
  {"rush": "plan 02", "piste": "V1", "entree": 0.3, "duree": 1.5},
  {"rush": "de roubax (3)", "piste": "M1", "debut": 0, "duree": 7.4, "gain": 0.5, "fondu_out": 1},
  {"texte": "GROUND RUN", "piste": "V2", "duree": 3},
  {"fond": "#000000", "piste": "V2", "duree": 1}
 ]
}
```

- **`rush`** : un identifiant, un nom exact, ou un morceau de nom — cherché dans **toute** la bibliothèque
  (l'image dans les rushes, la musique dans le dossier de musique). `"projet"` limite la recherche.
- **`debut`** absent : le bloc se pose à la suite du dernier de sa piste.
- **`sortie`**, ou **`duree`** (durée sur la timeline, la vitesse est prise en compte), sinon le rush entier.
- **`fondu_in`** / **`fondu_out`**, **`vitesse`**, **`opacite`**, **`gain`**, **`couleur`** (0–5),
  **`cadrage`** (`contain`/`cover`), **`envers`**.
- Une **image fixe** n'a pas de durée derrière : elle s'étire librement, comme un calque.

La séquence s'enregistre dans le projet du premier plan image — jamais dans une bibliothèque partagée
(musique) : c'est la règle de l'application, tenue ici aussi. `--projet` impose l'hôte.

## En MCP

```
claude mcp add --scope user bibliotheques-video -- python "K:\Claude-projets\Library-Editor\outils\monteur.py" --mcp
```

Outils exposés : `bibliotheques`, `projets`, `catalogue`, `sequences`, `lire_sequence`, `ecrire_sequence`.
Le dialogue JSON-RPC est écrit à la main (bibliothèque standard uniquement) et **forcé en UTF-8** : sous
Windows, un seul « dans une phrase suffisait à casser le flux.

## Ce qu'il ne fait pas

Rien dans les dossiers de rushes, rien dans les catalogues, aucune séquence sans le préfixe. Il n'écrase une
séquence existante que si on le demande, et garde alors l'ancienne en `.avant-claude`.

**Une séquence ouverte dans la page appartient à la page** : le montage y vit en mémoire et s'enregistre tout
seul. Écrire une séquence *neuve* (ce que fait le préfixe) ne croise jamais ce chemin.

Éprouvé par `python tests/installeur_essais.py` (section « monteur »), sur une vraie bibliothèque installée.

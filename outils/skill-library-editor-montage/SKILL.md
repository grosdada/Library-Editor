---
name: library-editor-montage
description: Piloter la table de montage des bibliothèques vidéo de David (Library Editor) — sur le PC (LANCER-LA-BIBLIOTHEQUE.exe, serveur.py local) ou en ligne (placenta.tv/montage-cdc, montage-mode, mode-cringe-telenovela, ground-run.placenta.tv/ep-NN). Utiliser dès qu'il faut lire une vidéothèque, chercher des rushes, monter ou modifier une séquence, poser des blocs, des fondus, des effets, des masques, des images clés, des sous-titres, couper aux changements de plan, mixer le son, exporter un MP4, ou expliquer une fonction de l'interface (« la bibli de montage », « la timeline », « Sequence », « Rushes », « monte-moi », « fais une séquence avec », « claude - »). Ne pas utiliser pour les banques d'images (NAVIGATEUR.html) ni pour fabriquer/publier une bibliothèque (c'est Library Editor lui-même).
---

# Piloter la table de montage (Library Editor)

Une seule page (`_app/app.html`) sert sur le bureau et en ligne. Le manuel complet, à lire pour tout détail
d'interface : `K:\Claude-projets\Library-Editor\docs\MANUEL-MONTAGE.html` (sections 1–15 : barre du haut,
colonne, grille, moniteur, timeline, réglages, effets, masques, clés, séquences, export, raccourcis, modèle de
données, routes). Le code fait foi : `K:\Claude-projets\Library-Editor\template\_app\app.html`,
`serveur.py`, `modeles\enligne\films\api.php`.

## Règles non négociables

1. **Préfixe `claude - `** sur toute séquence que tu crées. Ne jamais écrire sous le nom d'une séquence de David.
2. **Ne jamais écrire une séquence ouverte dans une page** : la page l'enregistre toute seule toutes les 4 s et
   écraserait ton travail (ou toi le sien). Écris sous un nom neuf, puis ouvre-la.
3. **Rien dans les dossiers de rushes** : pas de renommage, déplacement, suppression de fichiers, pas de
   `api/renommer`, `deplacer`, `dossier/*`, `purger`, `scan` sans demande explicite de David.
4. **Jamais de mot de passe** : en ligne, travailler dans l'onglet où David s'est déjà connecté. Ne jamais
   remplir la porte « Sign in » ni `api/entrer`, ni la boîte « Sign in to the website » du Sync.
5. **Ne pas lancer de rendu, de Sync online ni d'Update** sans que David le demande.
6. Un processus ne s'arrête que par nom exact puis PID (jamais « tout python »).

## Où sont les bibliothèques

- Liste du PC : `%APPDATA%\Library Editor\reglages.json` → `recents` (chemin, titre, port), ou
  `python K:\Claude-projets\Library-Editor\outils\monteur.py bibliotheques`.
- Une bibliothèque = un dossier racine avec `_app\` (`bibliotheque.json`, `serveur.py`, `app.html`,
  `_donnees\<projet>\catalogue.json`, `_donnees\<projet>\_montages\<nom>.json`, `_presets\`).
- En ligne (SSH `ssh -i ~/.ssh/hostinger_groundrun -p 65002 u335969729@46.202.158.181`, racine
  `~/domains/placenta.tv/public_html/`) : `<site>/_data/<projet>/catalogue.json`,
  `_data/<projet>/_montages/commun/<nom>.json`, `_data/projets.json`, médias `_media/` (proxys).
  Écrire en ligne par SSH seulement si David le demande ; préférer l'API depuis sa page connectée.

## Choisir la voie

| Besoin | Voie |
|---|---|
| Lire : projets, rushes, séquences | **A** monteur.py (bureau) ou **B** GET API |
| Monter une séquence simple (plans bout à bout, fondus, musique, textes) sur le PC | **A** `monteur.py ecrire` |
| Monter avec son lié, effets, masques, clés, secousse, échelle/position, marqueurs, ou en ligne | **B** écrire le JSON complet par `POST api/montage` |
| Rendu MP4, Auto cut, Mix sound, Cache, capture, export XML, retoucher la séquence ouverte | **C** piloter la page |

### A · `outils/monteur.py` (CLI + MCP « bibliotheques-video »)

Le MCP est enregistré dans Claude Code (`claude mcp list` → `bibliotheques-video … ✔ Connected`) et dans Codex (`codex mcp list`) : s'il est chargé, appeler ses outils (`bibliotheques`, `projets`, `catalogue`, `sequences`, `lire_sequence`, `ecrire_sequence`) plutôt que la ligne de commande.

Depuis la 1.3.67, le serveur de bureau refuse toute requête d'un navigateur venue d'une autre page (Origin / Sec-Fetch-Site / Host) : écrire par script (Python, curl) ou depuis l'onglet de la bibliothèque, jamais par `fetch` depuis un autre site.

```
python K:\Claude-projets\Library-Editor\outils\monteur.py bibliotheques
python …\monteur.py projets   "EP-06"
python …\monteur.py catalogue "EP-06" --cherche roubax [--projet X --genre video|son|image]
python …\monteur.py sequences "EP-06"
python …\monteur.py lire      "EP-06" --nom "claude - ouverture"
python …\monteur.py ecrire    "EP-06" plan.json --nom "ouverture"     # écrit « claude - ouverture »
```
MCP : `claude mcp add --scope user bibliotheques-video -- python "K:\Claude-projets\Library-Editor\outils\monteur.py" --mcp`
(outils `bibliotheques`, `projets`, `catalogue`, `sequences`, `lire_sequence`, `ecrire_sequence`).
Plan : `{"format":[1920,1080],"fps":24,"plans":[{"rush":"morceau de nom","piste":"V1","entree":0.3,"duree":1.5,"fondu_in":0.4}, {"rush":"musique","piste":"M1","debut":0,"duree":7.4,"gain":0.5,"fondu_out":1}, {"texte":"TITRE","piste":"V2","duree":3}, {"fond":"#000000","piste":"V2","duree":1}]}`
— champs : `rush`, `projet`, `piste`, `debut` (absent = à la suite), `entree`, `sortie` | `duree`,
`fondu_in`/`fondu_out`, `vitesse`, `opacite`, `gain`, `couleur` (0–5), `cadrage` (contain/cover), `envers`,
`texte` (+`police`, `taille`, `teinte`), `fond`. Détails : `K:\Claude-projets\Library-Editor\outils\LIRE.md`.
**Il ne sait pas** : son lié d'un rush vidéo (les pistes A/M n'acceptent que des fichiers son), effets, masques,
clés, échelle/position, retournements, secousse, gel, réglages de piste, marqueurs de bloc ; il ne remplit pas
`rendu`. Pour tout cela → voie B.

### B · Écrire la séquence en JSON (API)

- **Bureau** : la bibliothèque doit tourner (port dans `bibliotheque.json` / `reglages.json`).
  `GET http://127.0.0.1:<port>/api/projets`, `api/catalogue?projet=`, `api/montages?projet=`,
  `api/montage?projet=&nom=` ; écrire : `POST api/montage {"projet": hôte, "nom": "claude - …", "montage": {…}}`.
- **En ligne** : depuis l'onglet connecté de David (navigateur), en JS dans la page :
  `await api('api/montages?projet=Vids')`, `await api('api/montage', {projet, nom, montage})`.
  `api(route, corps)` est la fonction de la page (GET sans corps, POST JSON avec).
- Vérifier d'abord que le nom n'existe pas (`api/montages`). Hôte = le projet `Vids` s'il existe, sinon le projet
  vidéo des rushes ; jamais une bibliothèque partagée (musique) ni Screenshots.
- Ensuite ouvrir la séquence dans la page (clic dans la colonne ou `await ouvrirMontage(pj, nom)`) et faire une
  petite modification annulée n'est pas nécessaire : la page recalcule tout à l'ouverture ; elle réécrit le champ
  `rendu` à la première modification. Pour un rendu bureau, ouvrir puis modifier/enregistrer (Ctrl+S).

Squelette (format exact de `objetProjet()`) :
```json
{"version":5,"projet":{"nom":"claude - essai","w":1920,"h":1080,"fps":24},"hote":"Vids",
 "projets":["Vids","GR-MUSIC"],"fps":24,"format":{"w":1920,"h":1080},"tIn":null,"tOut":null,"PPS":40,
 "marqueurs":[],
 "pistes":[{"id":"V1","type":"v","mute":false,"solo":false},{"id":"A1","type":"a","mute":false,"solo":false,"vol":1},
           {"id":"M1","type":"m","mute":false,"solo":false,"vol":1}],
 "clips":[
  {"uid":1,"piste":"V1","film":"<id>","pj":"Vids","fichier":"<rel>","t0":0,"e":2.0,"o":5.0,"vitesse":1,"lien":"L1",
   "fi":0,"fo":0,"gain":1,"opac":1,"ech":1,"dx":0,"dy":0,"mode":"contain","couleur":0},
  {"uid":2,"piste":"A1","film":"<id>","pj":"Vids","fichier":"<rel>","t0":0,"e":2.0,"o":5.0,"vitesse":1,"lien":"L1",
   "fi":0,"fo":0,"gain":1,"opac":1,"ech":1,"dx":0,"dy":0,"mode":"contain","couleur":0}]}
```
Champs d'un bloc (unités) : `t0` début timeline (s) ; `e`/`o` entrée/sortie **source** (s) — durée timeline =
(o−e)/vitesse ; `vitesse` > 0, `rev` envers ; `lien` "L<n>" commun à l'image et à son son (le son d'un rush
vidéo = un 2e bloc même `film`, même `t0/e/o`, piste A) ; `fi`/`fo` fondus (s) ; `gain` 0–2 ; `opac` 0–1 ;
`ech` échelle, `dx`/`dy` −100…100 (100 = demi-cadre) ; `mode` contain|cover ; `fh`/`fv` ; `couleur` 0–5 ;
`gel` (s source) ; `mq` [s source] ; `anim` `{ech|dx|dy|opac|gain:[{t,v,i?,o?}]}` (t depuis le début du bloc) ;
`fx` `[{t:"flou"|"etal"|"nb"|"vignette"|"grain"|"halation"|"aberration", on:true, …}]` ; `masque`
`{forme:"libre"|"rect"|"ellipse", pts:[[x,y]…] (0–1), plume, inv, on}` ; `shk` + `shks:[{f,a,r,i,o,on}]` ;
synthétiques : `genre:"couleur"` + `fond`, `genre:"texte"` + `txt, police ("noir"=Arial Black, "sans"…), teinte,
taille (% hauteur), ombre`, `genre:"reglage"` + `fx` (calque d'effet). `film:""`, `e:0`, `o:durée` pour eux.
Paramètres d'effets, plages et défauts : manuel §8. Pistes : `V*` image (V1 au fond), `A*` son, `M*` musique ;
toujours au moins une de chaque.
Les rushes : `api/catalogue` → `films[]` : `id`, `nom`, `rel` (= `fichier`), `s` (durée), `w`, `h`, `a` (a du
son), `image`, `absent`.

### C · Piloter la page

Bureau : `http://127.0.0.1:<port>/` (lancer `LANCER-LA-BIBLIOTHEQUE.exe` de la bibliothèque, ou
`python _app\serveur.py`). En ligne : l'URL du site, onglet déjà connecté par David. Navigateur : Chrome.

Fonctions de la page utilisables en JS (même code bureau/en ligne) :
- État : `CLIPS`, `PISTES`, `clipsSel` (Set d'uid), `tLect` (tête), `PAR_ID[id]` (rushes), `OUVERTS`,
  `PROJET`, `projetNom`.
- Mode : `mode('edit')` / `mode('rush')`. Outil : `setOutil('V'|'C'|'A')`.
- Ouvrir : `await ouvrirMontage(pj, nom)`. Enregistrer : `await assurerSauvegarde()`.
- Modifier proprement : `memoriser()` **avant** toute modification (annulation + enregistrement auto),
  puis changer `CLIPS`/`PISTES`, puis `rendreTimeline(); resynchroniser(true);`.
- Poser : `ajouterAuMontage(ids, pisteId, t0)` (son lié créé tout seul), `nouveauClip(film, piste, t0)`,
  `poserSynth({genre, …}, duree)`, `ajouterPiste('v'|'a'|'m')`.
- Éditer : `couper(c, t)`, `await couperAuxPlans()` (sur `clipsSel`), `mixerSon()` (sur `clipsSel`),
  `dupliquerBlocs()`, `clonerBlocs(n)`, `retirerSelection()`, `figerSelection()`, `vitesseSelection(v)`,
  `couleurSelection(i)`, `delier()`, `relier()`.
- Temps : `allerAuTemps(t)`, `poserIn()`, `poserOut()` (à la tête).
- Groupes : `groupeLie(c)`, `fin(c)`, `dur(c)`, `srcA(c,t)`, `tlA(c,s)`.
Préférer ces fonctions aux clics simulés ; vérifier le résultat en relisant `CLIPS` et la ligne d'état
(`#mDuree` : « · » final = pas encore écrit, « NOT SAVED » = échec).

Raccourcis (si l'on pilote au clavier) : Espace lecture, V/C/A outils, I/O points, M marqueur, E éditeur de
clés, Tab réglages, Ctrl+Z (pas de rétablir), Ctrl+C/V (collé à la tête), Ctrl+D ou Ctrl seul = dupliquer,
Ctrl+glisser = dupliquer en glissant, Ctrl au lâcher = pousser derrière, Maj = aimant, Alt+clic = bloc sans
son lié, ↑/↓ coupes, ←/→ 1/24 s. Tableau complet : manuel §11.

## Pièges

- Pas d'insertion ni de ripple : poser par-dessus un bloc le recouvre ; deux blocs qui se chevauchent sur une
  piste = fondu enchaîné. Calculer les `t0` soi-même.
- Le rendu ffmpeg (bureau) **ne rend pas** les images clés d'échelle, position, opacité (il rend celles du
  volume et des effets). L'export en ligne (temps réel dans le navigateur) rend tout ce que montre le moniteur.
- Le rendu bureau cuit le son lié dans le plan image tant que ses bornes et fondus sont ceux de l'image ;
  sinon (Mix sound, son rogné à part) il le mixe à part avec ses fondus.
- `Edit sequence…` → Apply ne renomme pas : un nouveau nom crée un 2e fichier. `Clear` garde le nom.
- `↓ JSON` de l'export crée une entrée illisible dans la liste des séquences.
- En ligne, toutes les séquences sont partagées par tous les comptes (`_montages/commun`) ; dernier qui écrit gagne.
- Le navigateur plafonne le volume à 100 % sur le moniteur ; au-delà, seul le rendu bureau l'entend.
- Après avoir modifié `template/_app/app.html` de Library Editor, la chaîne de publication (CLAUDE.md du dépôt)
  pousse la page dans les 16 bibliothèques PC et les 16 sites : ne jamais éditer un `app.html` installé à la main.

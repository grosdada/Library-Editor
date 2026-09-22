# Library Editor

Une application Windows qui construit des bibliothèques locales à partir de
dossiers d'images ou de rushes vidéo, **sans jamais toucher aux fichiers
d'origine** : tout ce qui est écrit va dans un dossier `serveur\` (images) ou
`_app\` (films), et chaque installation le prouve par une empreinte (nom,
taille, date de chaque fichier) relevée avant et après.

Ce dépôt sert aussi de **source des mises à jour** : les bibliothèques déjà
installées y lisent `version.json` et remplacent leur propre programme, à la
demande, depuis leur bouton « Mettre à jour ».

## Ce que l'application fabrique

**Bibliothèque d'images.** Le dossier choisi devient une *bibliothèque
générale à onglets* : chaque sous-dossier coché devient une *banque* (favoris,
pastilles de couleur, recherche, fiches détaillées, téléchargement ZIP), et
un préparateur posé à côté (`Preparer une bibliotheque`) permet d'en ajouter
d'autres et de les ranger en onglets, sans repasser par Library Editor. Une
fiche est, au choix, un sous-dossier (sa vignette est l'image dont le nom
finit par `_clean`, `_def`…) ou une image.

**Bibliothèque de films.** Catalogue des rushes avec vignettes et sondage des
médias, puis une table de montage dans le navigateur : pistes, fondus,
vitesse, images-clés, rendu MP4 par ffmpeg et export XML pour Premiere. Les
dossiers de rushes sont en lecture seule ; le rangement se fait dans des
dossiers virtuels.

**Mise en ligne.** Un module à part prépare un paquet prêt à envoyer chez un
hébergeur mutualisé (Hostinger), avec un guide pas à pas. Aucun mot de passe
n'est demandé, reçu, écrit ni stocké.

## Construire

Windows, Python 3.10+, PyInstaller, Pillow. Depuis la racine du dépôt :

    python source/build.py          # moteur Python embarqué, puis l'application, puis le zip
    python source/build.py app      # seulement l'application
    python source/build.py zip      # seulement l'archive de distribution

La construction produit `dist/Library Editor/Library Editor.exe` (mode
« onedir »), `build/Library-Editor-<version>.zip`, et régénère `version.json`.

Les essais (il leur faut ffmpeg dans le PATH) :

    python tests/installeur_essais.py     # installation, mise à jour, mise en ligne
    python tests/serveur_essais.py <bibliothèque de films>
    node tests/inverse.js <app.html>      # montage : inversion, vitesse
    node tests/rangement.js <app.html>    # dossiers virtuels

## Les mises à jour

`version.json` décrit, pour chaque genre de bibliothèque (`films`, `racine`
d'images à onglets, `banque`), les fichiers de **programme** : leur chemin
dans le dépôt, leur empreinte SHA-256, et celles de toutes les versions
officielles précédentes (`historique.json`).

Le moteur commun ([`modeles/commun/_maj.py`](modeles/commun/_maj.py)) est
déposé dans chaque bibliothèque. Ses règles :

- un fichier n'est remplacé que si sa version est **reconnue** — une version
  officielle, ou celle inscrite dans `_version.json` à la dernière
  installation. Un fichier retouché à la main est laissé tel quel et signalé ;
- tout est téléchargé et **vérifié** (SHA-256) avant la première écriture ;
- chaque fichier remplacé est **sauvegardé** en `.avant-maj-<version>-<date>` ;
- les **données** (catalogues, séquences, favoris, pastilles, vignettes) ne
  sont jamais touchées : elles ne sont pas dans le manifeste ;
- les lanceurs `.bat` ne sont pas remplacés pendant qu'une bibliothèque est
  ouverte : une console les relit au fil de l'eau ;
- les fichiers sont lus à un **commit fixe** (champ `commit` du manifeste) :
  un dépôt qui change pendant un téléchargement ne peut pas mélanger deux
  versions.

## Publier une version

1. `python source/build.py` (application + archive) ;
2. commit et push de tout le dépôt ;
3. `python source/publier.py <sha du commit>` : régénère `version.json` avec
   le commit et la section `installeur` (URL, taille et empreinte de
   l'archive), puis l'ajoute à `historique.json` ;
4. commit et push de `version.json` seul, et publication de l'archive en
   *release* `v<version>`.

## Organisation

    source/           l'application (serveur local, interface, installation, mises à jour)
    source/ui/        l'interface, une page
    modeles/images/   le programme d'une banque d'images
    modeles/racine/   la bibliothèque générale à onglets et son préparateur
    modeles/films/    les lanceurs d'une bibliothèque de films
    modeles/commun/   le moteur de mise à jour déposé dans les bibliothèques
    modeles/lanceur/  le petit .exe à icône qui lance le .bat du même nom
    modeles/enligne/  le site PHP des bibliothèques mises en ligne
    template/_app/    le serveur et l'application des bibliothèques de films
    tests/            les essais

Windows uniquement pour l'instant.

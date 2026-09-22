# -*- coding: utf-8 -*-
"""Publier une version : le manifeste que les bibliotheques liront.

    python source/publier.py <sha du commit> [chemin de l archive] [notes]

Ecrit version.json a la racine du depot avec :
  - « commit » : le commit ou se trouvent les fichiers listes. Les
    bibliotheques les lisent A CE COMMIT, jamais a la branche : un depot qui
    bouge pendant un telechargement ne peut pas melanger deux versions ;
  - « installeur » : l adresse, la taille et l empreinte de l archive de
    l application, pour que Library Editor se mette a jour lui-meme.

Puis ajoute les empreintes de cette version a historique.json : la version
SUIVANTE saura les reconnaitre, et pourra donc les remplacer.

L ordre de publication est donc : commit de tout le depot, puis ce script
avec le sha de ce commit, puis un second commit de version.json seul (il ne
change aucun fichier liste, le commit epingle reste juste).
"""
import hashlib
import json
import os
import sys

ICI = os.path.dirname(os.path.abspath(__file__))
PROJET = os.path.dirname(ICI)
sys.path.insert(0, ICI)

import le_commun as C          # noqa: E402
import manifeste as M          # noqa: E402

DEPOT = C.DEPOT_GITHUB


def empreinte(chemin):
    h = hashlib.sha256()
    with open(chemin, "rb") as f:
        for bloc in iter(lambda: f.read(1 << 20), b""):
            h.update(bloc)
    return h.hexdigest()


def archive_par_defaut():
    return os.path.join(PROJET, "build", "Library-Editor-%s.zip" % C.VERSION)


def publier(commit, archive=None, notes=""):
    if not commit or len(commit) < 7:
        raise SystemExit("Donnez le sha du commit qui porte les fichiers.")
    archive = archive or archive_par_defaut()
    installeur = None
    if os.path.isfile(archive):
        installeur = {
            "version": C.VERSION,
            "url": "%s/releases/download/v%s/%s" % (DEPOT, C.VERSION,
                                                    os.path.basename(archive)),
            "octets": os.path.getsize(archive),
            "sha256": empreinte(archive),
        }
    else:
        print("Archive absente (%s) : le manifeste n aura pas de section "
              "« installeur », et le bouton « Mettre a jour Library Editor » "
              "ne proposera rien." % archive)
    m = M.generer(installeur=installeur, commit=commit, notes=notes)
    chemin = os.path.join(PROJET, "version.json")
    with open(chemin, "w", encoding="utf-8", newline="\n") as f:
        json.dump(m, f, ensure_ascii=False, indent=1)
        f.write("\n")
    n = sum(len(g["fichiers"]) for g in m["genres"].values())
    print("version.json : version %s, commit %s, %d fichiers"
          % (m["version"], commit[:12], n))
    if installeur:
        print("  archive %s (%d octets)" % (os.path.basename(archive),
                                            installeur["octets"]))
    h = M.ajouter_a_l_historique()
    print("historique.json : %d fichiers suivis" % len(h))
    print("\nIl reste a : commit de version.json et historique.json, push, "
          "puis la release v%s avec l archive." % C.VERSION)
    return m


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    publier(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None,
            sys.argv[3] if len(sys.argv) > 3 else "")

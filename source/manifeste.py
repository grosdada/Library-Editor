# -*- coding: utf-8 -*-
"""Le manifeste version.json : ce qu est le programme de chaque genre de
bibliotheque, fichier par fichier.

    python source/manifeste.py            ecrit version.json a la racine du depot

Pour chaque fichier : son chemin DANS la bibliotheque, son chemin dans le
depot, son empreinte SHA-256, et l historique des empreintes officielles
precedentes (historique.json, que la publication complete a chaque version).
Un fichier dont l empreinte n est ni l actuelle ni dans l historique est
considere comme modifie a la main, et n est jamais remplace sans demande.

Drapeaux :
  lanceur    un .bat qu une console peut etre en train de lire : jamais
             remplace depuis une bibliotheque ouverte ;
  cache      le .bat est cache (son .exe a icone le remplace a l ecran) ;
  si_jumeau  a installer seulement si ce fichier existe (un .exe a icone
             n a de sens qu a cote de son .bat).
"""
import hashlib
import json
import os
import time

ICI = os.path.dirname(os.path.abspath(__file__))
PROJET = os.path.dirname(ICI)
VERSION_FICHIER = os.path.join(ICI, "le_commun.py")

L, LC = {"lanceur": True}, {"lanceur": True, "cache": True}
EXE = "modeles/lanceur/lanceur.exe"

GENRES = {
    "films": {
        "_app/serveur.py": ("template/_app/serveur.py", {}),
        "_app/app.html": ("template/_app/app.html", {}),
        "_app/_maj.py": ("modeles/commun/_maj.py", {}),
        "_app/LANCER.bat": ("modeles/films/LANCER.bat", L),
        "LANCER-LA-BIBLIOTHEQUE.bat": ("modeles/films/LANCER-LA-BIBLIOTHEQUE.bat", LC),
        "LANCER-LA-BIBLIOTHEQUE.exe": (EXE, {"si_jumeau": "LANCER-LA-BIBLIOTHEQUE.bat"}),
    },
    "racine": {
        "serveur/_serveur.py": ("modeles/racine/serveur/_serveur.py", {}),
        "serveur/NAVIGATEUR.html": ("modeles/racine/serveur/NAVIGATEUR.html", {}),
        "serveur/_maj.py": ("modeles/commun/_maj.py", {}),
        "serveur/LISEZ-MOI.txt": ("modeles/racine/serveur/LISEZ-MOI.txt", {}),
        "serveur/biblio-generale.bat": ("modeles/racine/serveur/biblio-generale.bat", L),
        "serveur/preparateur/_preparateur.py":
            ("modeles/racine/serveur/preparateur/_preparateur.py", {}),
        "serveur/preparateur/PREPARER.html":
            ("modeles/racine/serveur/preparateur/PREPARER.html", {}),
        "serveur/preparateur/LISEZ-MOI.txt":
            ("modeles/racine/serveur/preparateur/LISEZ-MOI.txt", {}),
        "serveur/preparateur/preparer.bat":
            ("modeles/racine/serveur/preparateur/preparer.bat", L),
        # Les modeles que le preparateur copie dans chaque nouvelle banque.
        "serveur/preparateur/modeles/_serveur.py": ("modeles/images/_serveur.py", {}),
        "serveur/preparateur/modeles/_scan.py": ("modeles/images/_scan.py", {}),
        "serveur/preparateur/modeles/NAVIGATEUR.html": ("modeles/images/NAVIGATEUR.html", {}),
        "serveur/preparateur/modeles/biblio.bat": ("modeles/images/biblio.bat", {}),
        "Bibliotheque generale.bat": ("modeles/racine/Bibliotheque generale.bat", LC),
        "Preparer une bibliotheque.bat": ("modeles/racine/Preparer une bibliotheque.bat", LC),
        "Bibliotheque generale.exe": (EXE, {"si_jumeau": "Bibliotheque generale.bat"}),
        "Preparer une bibliotheque.exe": (EXE, {"si_jumeau": "Preparer une bibliotheque.bat"}),
    },
    "banque": {
        "serveur/_serveur.py": ("modeles/images/_serveur.py", {}),
        "serveur/_scan.py": ("modeles/images/_scan.py", {}),
        "serveur/NAVIGATEUR.html": ("modeles/images/NAVIGATEUR.html", {}),
        "serveur/biblio.bat": ("modeles/images/biblio.bat", L),
        "LANCER-LA-BIBLIOTHEQUE.bat": ("modeles/images/LANCER-LA-BIBLIOTHEQUE.bat",
                                       dict(LC, si_present=True)),
        "LANCER-LA-BIBLIOTHEQUE.exe": (EXE, {"si_jumeau": "LANCER-LA-BIBLIOTHEQUE.bat"}),
    },
}


def sha256(chemin):
    h = hashlib.sha256()
    with open(chemin, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def version():
    with open(VERSION_FICHIER, encoding="utf-8") as f:
        for l in f:
            if l.startswith("VERSION = "):
                return l.split("=", 1)[1].strip().strip('"')
    raise RuntimeError("VERSION introuvable dans le_commun.py")


def historique():
    try:
        with open(os.path.join(PROJET, "historique.json"), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def fichiers_du_depot():
    """Tous les chemins de depot cites par le manifeste."""
    return sorted({d for g in GENRES.values() for d, _ in g.values()})


def generer(installeur=None, commit=None, notes=""):
    h = historique()
    genres = {}
    for g, fichiers in GENRES.items():
        out = {}
        for rel, (dep, drapeaux) in fichiers.items():
            s = sha256(os.path.join(PROJET, *dep.split("/")))
            info = {"depot": dep, "sha256": s,
                    "historique": [x for x in h.get(dep, []) if x != s]}
            info.update(drapeaux)
            out[rel] = info
        genres[g] = {"fichiers": out}
    m = {"version": version(), "date": time.strftime("%Y-%m-%d"),
         "notes": notes, "genres": genres}
    if commit:
        m["commit"] = commit
    if installeur:
        m["installeur"] = installeur
    return m


def ajouter_a_l_historique():
    """Apres une publication : les empreintes actuelles rejoignent
    l historique, pour etre reconnues quand la version suivante sortira."""
    h = historique()
    for dep in fichiers_du_depot():
        s = sha256(os.path.join(PROJET, *dep.split("/")))
        h.setdefault(dep, [])
        if s not in h[dep]:
            h[dep].append(s)
    with open(os.path.join(PROJET, "historique.json"), "w", encoding="utf-8",
              newline="\n") as f:
        json.dump(h, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")
    return h


if __name__ == "__main__":
    m = generer()
    with open(os.path.join(PROJET, "version.json"), "w", encoding="utf-8",
              newline="\n") as f:
        json.dump(m, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print("version.json %s : %d fichiers" % (
        m["version"], sum(len(g["fichiers"]) for g in m["genres"].values())))

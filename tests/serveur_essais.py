# -*- coding: utf-8 -*-
"""Essais du serveur d une bibliotheque INSTALLEE, sur ses vrais rushes.

    python tests/serveur_essais.py "Y:/chemin/de/la/bibliotheque"

Ne modifie rien de durable :
  - le rangement virtuel du premier projet est sauvegarde avant, restaure apres ;
  - les dossiers de rushes sont releves (nom, taille, date) avant et apres,
    et l essai ECHOUE si une seule entree a change.
Lance le vrai serveur.py de la bibliotheque, sur son vrai port, dans un fil.
"""
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser

RACINE = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else ".")
APP = os.path.join(RACINE, "_app")
sys.path.insert(0, APP)
webbrowser.open = lambda *a, **k: None      # pas d onglet pendant un essai
import serveur                                                 # noqa: E402

ok = ko = 0


def v(nom, cond, detail=""):
    global ok, ko
    if cond:
        ok += 1
        print("  ok    " + nom)
    else:
        ko += 1
        print("  ECHEC " + nom + ("   " + str(detail)[:240] if detail else ""))


def empreinte(dossier):
    out = []
    for rep, sous, fics in os.walk(dossier):
        for n in sous + fics:
            p = os.path.join(rep, n)
            st = os.stat(p)
            out.append("%s|%d|%.6f" % (os.path.relpath(p, dossier),
                                       st.st_size if n in fics else 0,
                                       st.st_mtime))
    return sorted(out)


def req(route, corps=None):
    r = urllib.request.Request(
        "http://127.0.0.1:%d%s" % (serveur.PORT, route),
        method="POST" if corps is not None else "GET",
        data=json.dumps(corps).encode() if corps is not None else None,
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=30) as x:
            return x.status, json.loads(x.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


projets = serveur.projets_disque()
avant = {p: empreinte(serveur.media_de(p)) for p in projets}
threading.Thread(target=serveur.demarrer, daemon=True).start()
time.sleep(2.5)

print("--- ce que le serveur annonce (port %d) ---" % serveur.PORT)
c, l = req("/api/projets")
v("repond", c == 200, c)
v("rangement annonce", l.get("rangement") is True, l.get("rangement"))
v("projets = ceux du disque", [p["nom"] for p in l["projets"]] == projets
  + serveur.biblis_disque(), [p["nom"] for p in l["projets"]])
print("    titre=%r lecture_seule=%r format=%r" % (
    l.get("titre"), l.get("lecture_seule"), l.get("format")))

if projets:
    PR = projets[0]
    c, cat = req("/api/catalogue?projet=" + PR)
    films = cat.get("films") or []
    print("--- %s : %d fiches ---" % (PR, len(films)))
    v("racine_abs pointe le dossier de rushes",
      os.path.normcase(cat.get("racine_abs", "")) ==
      os.path.normcase(serveur.media_de(PR)), cat.get("racine_abs"))
    v("identifiants de 12 caracteres hexadecimaux",
      all(len(f["id"]) == 12 for f in films))

    print("--- rangement virtuel ---")
    c, sauve = req("/api/rangement?projet=" + PR)
    v("lecture", c == 200, sauve)
    ids = [f["id"] for f in films[:3]]
    try:
        c, r = req("/api/rangement", {"projet": PR,
                   "dossiers": ["Essai/Sous", "../../evade"],
                   "ou": {i: "Essai/Sous" for i in ids[:1]}
                   if ids else {}})
        v("ecriture", c == 200, r)
        v("parent cree tout seul", "Essai" in r.get("dossiers", []), r)
        v("../../evade refuse",
          not any(".." in x for x in r.get("dossiers", [])), r)
    finally:
        req("/api/rangement", {"projet": PR,
                               "dossiers": sauve.get("dossiers") or [],
                               "ou": sauve.get("ou") or {}})
    c, r2 = req("/api/rangement?projet=" + PR)
    v("rangement d origine restaure", r2.get("ou") == (sauve.get("ou") or {})
      and r2.get("dossiers") == (sauve.get("dossiers") or []))

    if serveur.LECTURE_SEULE:
        print("--- lecture seule ---")
        for route in sorted(serveur.ECRIT_DANS_LES_RUSHES):
            c, r = req(route, {"projet": PR, "ids": ids[:1], "id": ids[0]
                               if ids else "", "nom": "x", "dossier": "x",
                               "source": PR})
            v("%-22s -> 403" % route, c == 403, (c, r))
        try:
            serveur._destination(PR, "essai",
                                 os.path.join(serveur.media_de(PR), "x.mp4"),
                                 "mp4")
            v("rendu dans les rushes refuse", False, "accepte")
        except ValueError:
            v("rendu dans les rushes refuse", True)

print("--- les dossiers de rushes n ont pas bouge ---")
for p in projets:
    apres = empreinte(serveur.media_de(p))
    v("%s : %d entrees identiques" % (p, len(apres)), apres == avant[p],
      set(apres) ^ set(avant[p]))

print("\n%d reussites, %d echec(s)" % (ok, ko))
sys.exit(1 if ko else 0)

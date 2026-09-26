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

print("--- l onde d un son (/api/onde) ---")
v("onde annoncee quand ffmpeg est la",
  l.get("onde") == bool(serveur.FFMPEG), l.get("onde"))
v("liste de tous les dossiers annoncee", l.get("dossiers") is True,
  l.get("dossiers"))

print("--- tous les dossiers (/api/dossiers) ---")
c, dos = req("/api/dossiers")
v("repond", c == 200, c)
noms = [x["nom"] for x in dos.get("dossiers", [])]
v("les projets du disque y sont, marques comme tels",
  all(n in noms for n in projets)
  and all(x["projet"] for x in dos.get("dossiers", []) if x["nom"] in projets),
  noms[:8])
v("un dossier non declare n est pas marque projet",
  all(not x["projet"] for x in dos.get("dossiers", [])
      if x["nom"] not in projets + serveur.biblis_disque()), noms[:8])

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

    print("--- onde d un media sonore ---")
    # Le premier projet n a pas forcement du son : on cherche dans tous.
    pr_son, sonore = PR, next(
        (f for f in films if f.get("son_seul") or f.get("a")), None)
    if not sonore:
        for autre in projets:
            if autre == PR:
                continue
            _, c_autre = req("/api/catalogue?projet=" + autre)
            sonore = next((f for f in (c_autre.get("films") or [])
                           if f.get("son_seul") or f.get("a")), None)
            if sonore:
                pr_son = autre
                break
    if not serveur.FFMPEG:
        print("    ffmpeg absent : onde non eprouvee")
    elif not sonore:
        print("    aucun media sonore dans ce projet : onde non eprouvee")
    else:
        cache = os.path.join(serveur.ondes_de(pr_son), sonore["id"] + ".json")
        deja = os.path.isfile(cache)
        c, o = req("/api/onde?projet=%s&id=%s" % (pr_son, sonore["id"]))
        v("l onde arrive", c == 200 and len(o.get("pics") or []) > 3, (c, o))
        v("un pic toutes les 20 ms", abs((o.get("pas") or 0) - 0.02) < 1e-9,
          o.get("pas"))
        v("autant de pics que de secondes de son",
          abs(len(o.get("pics") or []) / 50.0 - (o.get("s") or 0)) < 0.5,
          (len(o.get("pics") or []), o.get("s")))
        v("gardee en cache dans _donnees", os.path.isfile(cache), cache)
        c2, o2 = req("/api/onde?projet=%s&id=%s" % (pr_son, sonore["id"]))
        v("relue sans refaire le travail", c2 == 200
          and o2.get("pics") == o.get("pics"))
        c3, _ = req("/api/onde?projet=%s&id=%s" % (pr_son, "0" * 12))
        v("identifiant inconnu : 404", c3 == 404, c3)
        if not deja:
            try:
                os.remove(cache)          # rien de durable : on remet en etat
            except OSError:
                pass

    print("--- montrer un fichier dans l explorateur (/api/reveler) ---")
    v("le serveur annonce savoir le faire", l.get("reveler") is True,
      l.get("reveler"))
    # On remplace le geste : un essai n ouvre pas de fenetre sur le poste.
    vrai_montrer, montres = serveur.montrer_sur_le_disque, []
    serveur.montrer_sur_le_disque = lambda p: (montres.append(p) or p)
    try:
        f0 = films[0]
        attendu = serveur.sur(PR, f0["rel"])
        c, d = req("/api/reveler", {"projet": PR, "id": f0["id"]})
        v("la route rend le chemin du fichier", c == 200 and
          os.path.normcase(d.get("chemin") or "") == os.path.normcase(attendu),
          (c, d, attendu))
        v("c est ce fichier qui a ete montre", len(montres) == 1 and
          os.path.normcase(montres[0]) == os.path.normcase(attendu), montres)
        v("il n est pas annonce manquant", d.get("manquant") is False, d)
        c2, _ = req("/api/reveler", {"projet": PR, "id": "0" * 12})
        v("identifiant inconnu : 404", c2 == 404, c2)
        v("et rien n a ete montre pour lui", len(montres) == 1, montres)
    finally:
        serveur.montrer_sur_le_disque = vrai_montrer

    print("--- une image fixe se rend comme un plan ---")
    fixe = next((f for f in films if f.get("image")), None)
    if not serveur.FFMPEG:
        print("    ffmpeg absent : rendu d image non eprouve")
    elif not fixe:
        print("    aucune image dans ce projet : rendu non eprouve")
    else:
        import shutil as _sh
        import subprocess as _sp
        import tempfile as _tf
        d = _tf.mkdtemp(prefix="essai-image-")
        try:
            plan = {"projet": PR, "fichier": fixe["rel"], "entree": 0.0,
                    "sortie": 2.5, "vitesse": 1, "rev": False,
                    "cadrage": {"mode": "contain", "echelle": 1}}
            chemin, duree = serveur._segment(plan, d, 0, False)
            v("segment fabrique, a la duree du bloc",
              bool(chemin) and abs(duree - 2.5) < 0.01,
              (chemin, duree, serveur.RENDU.get("message")))
            if chemin:
                r = _sp.run([serveur.FFPROBE or "ffprobe", "-v", "error",
                             "-show_entries", "format=duration", "-of",
                             "default=nw=1:nk=1", chemin],
                            capture_output=True, text=True)
                try:
                    vraie = float((r.stdout or "0").strip())
                except ValueError:
                    vraie = 0.0
                v("le fichier dure vraiment 2,5 s", abs(vraie - 2.5) < 0.15, vraie)
        finally:
            _sh.rmtree(d, ignore_errors=True)

    print("--- rack d effets : chaque effet se rend ---")
    video = next((f for f in films if not f.get("image")
                  and not f.get("son_seul") and not f.get("absent")), None)
    if not serveur.FFMPEG:
        print("    ffmpeg absent : rack non eprouve")
    elif not video:
        print("    aucune video dans ce projet : rack non eprouve")
    else:
        import shutil as _sh
        import tempfile as _tf
        d = _tf.mkdtemp(prefix="essai-rack-")
        # Le rendu lit ces dimensions dans le montage ; ici on les pose.
        serveur.LARGE, serveur.HAUT, serveur.FPS_SORTIE = 320, 240, 24
        serveur.MODE = "video"
        piles = [
            ("flou gaussien", [{"t": "flou", "mode": "gauss", "force": 1}]),
            ("flou directionnel", [{"t": "flou", "mode": "dir", "force": 1.5,
                                    "angle": 30}]),
            ("tilt-shift", [{"t": "flou", "mode": "tilt", "force": 2,
                             "centre": 40, "largeur": 20, "fondu": 15,
                             "angle": 20}]),
            ("couleur", [{"t": "etal", "expo": 0.5, "contraste": 20,
                          "satu": -30, "temp": 40}]),
            ("N&B, sepia, virage", [{"t": "nb", "mode": "nb"},
                                    {"t": "nb", "mode": "sepia", "dose": 50},
                                    {"t": "nb", "mode": "virage",
                                     "teinte": "#3a7bd5", "dose": 60}]),
            ("vignette et grain", [{"t": "vignette", "force": 60},
                                   {"t": "grain", "force": 40}]),
            ("halation et aberration", [{"t": "halation", "force": 50},
                                        {"t": "aberration", "force": 0.6}]),
            ("effet eteint : ignore", [{"t": "flou", "on": False, "force": 3}]),
        ]
        try:
            for i, (nom, fx) in enumerate(piles):
                plan = {"projet": PR, "fichier": video["rel"], "entree": 0.0,
                        "sortie": 1.0, "vitesse": 1, "rev": False,
                        "opacite": 0.8, "cadrage": {"mode": "contain",
                                                    "echelle": 1}, "fx": fx}
                chemin, duree = serveur._segment(plan, d, i, False, 0.2, 0.2)
                v("rack « %s » : le segment se fabrique" % nom,
                  bool(chemin) and abs(duree - 1.0) < 0.01,
                  serveur.RENDU.get("message"))
            base, _ = serveur._segment(
                {"projet": PR, "fichier": video["rel"], "entree": 0.0,
                 "sortie": 2.0, "vitesse": 1, "rev": False,
                 "cadrage": {"mode": "contain", "echelle": 1}},
                d, 90, False)
            sortie = os.path.join(d, "incruste.mp4")
            calque = {"genre": "reglage", "position": 0.5, "duree": 1.0,
                      "opacite": 0.9, "fondu_entree": 0.2,
                      "fx": [{"t": "nb", "mode": "sepia"},
                             {"t": "flou", "mode": "tilt", "force": 1.5}]}
            ok_inc = bool(base) and serveur._incruster(base, sortie, [calque],
                                                      0.0, 2.0, d)
            v("calque d effet incruste sur le montage", ok_inc
              and os.path.isfile(sortie), serveur.RENDU.get("message"))
        finally:
            _sh.rmtree(d, ignore_errors=True)

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

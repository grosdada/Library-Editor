# -*- coding: utf-8 -*-
"""Essais de Library Editor : installer, mettre a jour, mettre en ligne.

    python tests/installeur_essais.py [dossier de travail]

Fabrique ses propres donnees (videos testsrc par ffmpeg, images avec
suffixes, un doublon, un dossier sans vignette) dans un dossier de travail
neuf, et n ecrit rien ailleurs : les reglages de l application (recents,
ports) sont detournes vers ce dossier. Eprouve le code livre (source/ et
modeles/, template/_app), pas une copie.

Couvre, dans l ordre :
  films   analyse, installation, arborescence, bibliotheque.json, catalogue,
          vignettes, empreinte avant/apres, serveur_essais.py (Python du poste
          ET moteur embarque), essais node sur l app.html installe,
          mise a jour (code remplace et sauvegarde, donnees intactes, projet
          ajoute), bibliotheque neuve (projets/ + bibliotheques/)
  images  suffixes, verification (doublon, dossier sans vignette),
          installation, empreinte, serveur de la banque (donnees, marques,
          vignette, ZIP), mode « une fiche par image », mise a jour
  ligne   paquet films (proxys, catalogues, zips), paquet images (routes
          relatives), paquet « seulement les changements »
"""
import http.client
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import zipfile

ICI = os.path.dirname(os.path.abspath(__file__))
PROJET = os.path.dirname(ICI)
TRAVAIL = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else tempfile.mkdtemp(prefix="le-essais-")
if os.path.isdir(TRAVAIL):
    shutil.rmtree(TRAVAIL)
os.makedirs(TRAVAIL)
# Les reglages de l application (recents, ports) : dans le dossier d essai.
os.environ["APPDATA"] = os.path.join(TRAVAIL, "_appdata")
os.environ["LOCALAPPDATA"] = os.path.join(TRAVAIL, "_localappdata")
sys.path.insert(0, os.path.join(PROJET, "source"))
import le_commun as C          # noqa: E402
import le_films as F           # noqa: E402
import le_images as I          # noqa: E402
import le_enligne as E         # noqa: E402

ok = ko = 0
FFMPEG = shutil.which("ffmpeg")


def v(nom, cond, detail=""):
    global ok, ko
    if cond:
        ok += 1
        print("  ok    " + nom)
    else:
        ko += 1
        print("  ECHEC " + nom + ("   " + str(detail)[:300] if detail else ""))


def tache():
    return C.Tache("essai", "essai", None)


def ff(*args):
    subprocess.run([FFMPEG, "-v", "error", "-y"] + list(args), check=True)


def octets(p):
    with open(p, "rb") as f:
        return f.read()


def vieille_version(dossier_version, chemin, cle):
    """Fabrique une version PRECEDENTE d un fichier de programme : le contenu
    change, et _version.json dit que c est celui qui avait ete installe — ce
    qu une bibliotheque d une version anterieure presente. `dossier_version`
    porte _version.json, `cle` est le nom du fichier dans le manifeste.
    Renvoie le contenu de cette vieille version."""
    import hashlib
    with io.open(chemin, "a", encoding="utf-8") as f:
        f.write("\n<!-- version precedente -->\n")
    contenu = octets(chemin)
    vj = os.path.join(dossier_version, "_version.json")
    d = C.lire_json(vj, {}) or {}
    d.setdefault("fichiers", {})[cle] = hashlib.sha256(contenu).hexdigest()
    C.ecrire_json(vj, d)
    return contenu


# ---------------------------------------------------------------------------
#  Donnees d essai
# ---------------------------------------------------------------------------
def donnees():
    F_ = os.path.join(TRAVAIL, "Film essai")
    for d in ("Rushes-A", os.path.join("Rushes-B", "jour 2"), "persos-select",
              "_outils", "prompts"):
        os.makedirs(os.path.join(F_, d), exist_ok=True)
    for i in range(1, 4):
        ff("-f", "lavfi", "-i", "testsrc=size=640x480:rate=24:duration=2",
           "-f", "lavfi", "-i", "sine=frequency=%d:duration=2" % (300 + 100 * i),
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
           os.path.join(F_, "Rushes-A", "plan 0%d (essai).mp4" % i))
    for i in (1, 2):
        ff("-f", "lavfi", "-i", "testsrc2=size=640x480:rate=24:duration=3",
           "-c:v", "libx264", "-pix_fmt", "yuv420p",
           os.path.join(F_, "Rushes-B", "jour 2", "prise_%d.mp4" % i))
    ff("-f", "lavfi", "-i", "sine=frequency=440:duration=3",
       os.path.join(F_, "Rushes-B", "ambiance.wav"))
    ff("-f", "lavfi", "-i", "testsrc=size=320x240:rate=24:duration=1",
       "-c:v", "libx264", "-pix_fmt", "yuv422p", os.path.join(F_, "Rushes-B", "422.mp4"))
    for i in (1, 2):
        ff("-f", "lavfi", "-i", "color=c=0x336699:s=400x300", "-frames:v", "1",
           os.path.join(F_, "persos-select", "perso_%d.jpg" % i))
    io.open(os.path.join(F_, "prompts", "p.html"), "w").write("x")
    io.open(os.path.join(F_, "_outils", "o.py"), "w").write("x")

    B = os.path.join(TRAVAIL, "Banque essai")
    for a in ("alpha", "beta", "gamma", "delta", "epsilon"):
        d = os.path.join(B, "sheets", a)
        os.makedirs(d)
        ff("-f", "lavfi", "-i", "testsrc=s=600x800", "-frames:v", "1",
           os.path.join(d, a + "_clean.jpg"))
        ff("-f", "lavfi", "-i", "testsrc2=s=600x800", "-frames:v", "1",
           os.path.join(d, a + "_def.png"))
        ff("-f", "lavfi", "-i", "testsrc2=s=800x600", "-frames:v", "1",
           os.path.join(d, a + "-grid.webp"))
    os.makedirs(os.path.join(B, "sheets", "zeta"))
    ff("-f", "lavfi", "-i", "testsrc=s=300x300", "-frames:v", "1",
       os.path.join(B, "sheets", "zeta", "zeta_def.png"))
    os.makedirs(os.path.join(B, "sheets", "eta"))
    for x in ("A", "B"):
        ff("-f", "lavfi", "-i", "testsrc=s=300x300", "-frames:v", "1",
           os.path.join(B, "sheets", "eta", "eta-%s_clean.jpg" % x))

    V = os.path.join(TRAVAIL, "Vrac essai")
    os.makedirs(os.path.join(V, "sous"))
    for i in range(1, 4):
        ff("-f", "lavfi", "-i", "testsrc2=s=500x%d" % (300 + 50 * i), "-frames:v", "1",
           os.path.join(V, "image %d.jpg" % i))
    ff("-f", "lavfi", "-i", "testsrc=s=500x500", "-frames:v", "1",
       os.path.join(V, "sous", "autre.png"))
    return F_, B, V


def lancer_essai_node(app_html):
    for js, attendu in (("inverse.js", "26"), ("rangement.js", "18")):
        r = subprocess.run(["node", os.path.join(ICI, js), app_html],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace")
        derniere = (r.stdout.strip().splitlines() or [""])[-1]
        v("node %s sur l app.html installe : %s" % (js, derniere),
          r.returncode == 0, r.stdout[-400:] + r.stderr[-400:])


# ---------------------------------------------------------------------------
#  Films
# ---------------------------------------------------------------------------
def essais_films(racine):
    print("\n=== FILMS : analyse ===")
    a = F.analyser(tache(), racine)
    lignes = {l["nom"]: l for l in a["lignes"]}
    v("4 dossiers vus (_outils ignore)", set(lignes) ==
      {"persos-select", "prompts", "Rushes-A", "Rushes-B"}, sorted(lignes))
    v("Rushes-A : 3 videos, cochee", lignes["Rushes-A"]["videos"] == 3
      and lignes["Rushes-A"]["coche"], lignes["Rushes-A"])
    v("Rushes-B : 3 videos + 1 son (sous-dossier compris)",
      lignes["Rushes-B"]["videos"] == 3 and lignes["Rushes-B"]["sons"] == 1,
      lignes["Rushes-B"])
    v("persos-select et prompts non coches", not lignes["persos-select"]["coche"]
      and not lignes["prompts"]["coche"])
    v("H.264 4:2:2 parmi des lisibles : « en partie »",
      lignes["Rushes-B"]["lisible"] == "partiel", lignes["Rushes-B"])
    v("Rushes-A lisible, 640x480", lignes["Rushes-A"]["lisible"] == "oui"
      and lignes["Rushes-A"]["resolution"] == "640x480", lignes["Rushes-A"])
    v("format propose 640x480", a["proposition"]["format"] == [640, 480],
      a["proposition"])
    port = a["proposition"]["port"]
    v("port propose hors 8779/8780, dans la plage", port and 8781 <= port < 8880
      and port not in (8779, 8780), port)

    print("\n=== FILMS : installation ===")
    t = tache()
    r = F.installer(t, racine, {"titre": "Film d'essai", "disposition": "existante",
                                "projets": ["Rushes-A", "Rushes-B"], "port": port,
                                "format": [640, 480], "lecture_seule": True,
                                "moteur": True, "raccourci": False})
    app = os.path.join(racine, "_app")
    v("serveur.py = celui du modele", octets(os.path.join(app, "serveur.py")) ==
      octets(os.path.join(PROJET, "template", "_app", "serveur.py")))
    v("app.html = celui du modele", octets(os.path.join(app, "app.html")) ==
      octets(os.path.join(PROJET, "template", "_app", "app.html")))
    b = octets(os.path.join(racine, C.NOM_LANCEUR))
    v("lanceur a la racine, en CRLF, LANCER.bat par son chemin complet",
      b"\r\n" in b and b'call "%~dp0_app\\LANCER.bat"' in b)
    v("LANCER.bat en CRLF, moteur en premier",
      b"_python\\python.exe" in octets(os.path.join(app, "LANCER.bat"))
      and b"\r\n" in octets(os.path.join(app, "LANCER.bat")))
    regl = C.lire_json(os.path.join(app, "bibliotheque.json"))
    v("bibliotheque.json", regl == {"titre": "Film d'essai", "projets_dans": ".",
                                    "projets": ["Rushes-A", "Rushes-B"],
                                    "donnees": "_app/_donnees", "lecture_seule": True,
                                    "port": port, "format": [640, 480]}, regl)
    v("moteur embarque present", os.path.isfile(os.path.join(app, "_python", "python.exe")))
    v("aucun dossier provisoire restant", not [n for n in os.listdir(racine)
                                             if n.startswith(".installation")])
    for p, n in (("Rushes-A", 3), ("Rushes-B", 4)):
        cat = C.lire_json(os.path.join(app, "_donnees", p, "catalogue.json"), {})
        films = cat.get("films", [])
        v("%s : %d fiches" % (p, n), len(films) == n, len(films))
        v("%s : identifiants de 12 hexadecimaux" % p,
          all(len(f["id"]) == 12 and all(c in "0123456789abcdef" for c in f["id"])
              for f in films))
        v("%s : durees sondees" % p, all(f.get("s", 0) > 0 for f in films))
        videos = [f for f in films if not f.get("son_seul")]
        faits = [f for f in videos if os.path.isfile(os.path.join(
            app, "_donnees", p, "_posters", f["id"] + ".jpg"))]
        v("%s : %d vignettes" % (p, len(videos)), len(faits) == len(videos),
          (len(faits), len(videos)))
    v("rien d ecrit dans les rushes (pas de _projet)",
      not os.path.exists(os.path.join(racine, "Rushes-A", "_projet")))
    v("preuve : 2 dossiers identiques", len(r["preuve"]) == 2 and
      all(x["identiques"] for x in r["preuve"]), r["preuve"])
    v("recents : la bibliotheque y est", any(
        os.path.normcase(x["chemin"]) == os.path.normcase(racine)
        for x in C.reglages()["recents"]))
    v("port memorise pour cette bibliotheque",
      C.port_pour_bibliotheque(racine) == port)
    # Le raccourci, pose dans un faux Bureau : rien sur le vrai.
    faux_bureau = os.path.join(TRAVAIL, "_bureau")
    os.makedirs(faux_bureau, exist_ok=True)
    vrai_bureau, C.bureau = C.bureau, lambda: faux_bureau
    try:
        lnk = C.raccourci_bureau(racine, "Film d'essai",
                                 os.path.join(app, "_python", "python.exe"))
    finally:
        C.bureau = vrai_bureau
    v("raccourci .lnk cree (faux Bureau)", os.path.isfile(lnk)
      and os.path.dirname(lnk) == faux_bureau, lnk)
    v("une autre bibliotheque aurait un autre port",
      C.port_pour_bibliotheque(os.path.join(TRAVAIL, "autre")) != port)

    print("\n=== FILMS : serveur_essais.py (Python du poste) ===")
    r1 = subprocess.run([sys.executable, os.path.join(ICI, "serveur_essais.py"), racine],
                        capture_output=True, text=True, encoding="utf-8", errors="replace")
    print("\n".join("    " + l for l in r1.stdout.strip().splitlines()[-4:]))
    v("serveur_essais.py : aucun echec", r1.returncode == 0, r1.stdout[-600:] + r1.stderr[-600:])
    moteur = os.path.join(app, "_python", "python.exe")
    print("\n=== FILMS : serveur_essais.py (moteur embarque) ===")
    r2 = subprocess.run([moteur, os.path.join(ICI, "serveur_essais.py"), racine],
                        capture_output=True, text=True, encoding="utf-8", errors="replace")
    print("\n".join("    " + l for l in r2.stdout.strip().splitlines()[-4:]))
    v("serveur_essais.py sous le moteur embarque : aucun echec", r2.returncode == 0,
      r2.stdout[-600:] + r2.stderr[-600:])
    rc = subprocess.run([moteur, "-c", "import sys; print(sys.argv[1])", "arg"],
                        capture_output=True, text=True)
    v("moteur : -c et ses arguments (selecteur de dossier)", rc.stdout.strip() == "arg",
      rc.stdout + rc.stderr)

    print("\n=== FILMS : essais node sur l app.html installe ===")
    lancer_essai_node(os.path.join(app, "app.html"))

    print("\n=== FILMS : mise a jour ===")
    cat_a = octets(os.path.join(app, "_donnees", "Rushes-A", "catalogue.json"))
    v("_version.json ecrit a l installation",
      C.lire_json(os.path.join(app, "_version.json"), {}).get("version") == C.VERSION,
      C.lire_json(os.path.join(app, "_version.json"), {}))
    v("lanceur a icone + .bat cache",
      os.path.isfile(os.path.join(racine, "LANCER-LA-BIBLIOTHEQUE.exe"))
      and C.attribut_cache(os.path.join(racine, C.NOM_LANCEUR)))
    # Une version precedente du programme : le fichier est different, mais
    # c est celui que cette bibliotheque avait (il est dans _version.json).
    vieille = vieille_version(app, os.path.join(app, "app.html"), "_app/app.html")
    os.makedirs(os.path.join(racine, "Rushes-C"))
    ff("-f", "lavfi", "-i", "testsrc=size=640x480:rate=24:duration=1", "-c:v", "libx264",
       "-pix_fmt", "yuv420p", os.path.join(racine, "Rushes-C", "c.mp4"))
    e = F.etat_mise_a_jour(racine)
    etats = {x["fichier"]: x["etat"] for x in e["fichiers"]}
    v("etat : app.html a remplacer, serveur.py a jour",
      etats.get("_app/app.html") == "a_remplacer"
      and etats.get("_app/serveur.py") == "a_jour", etats)
    v("etat : version installee et version de l editeur",
      e["version_locale"] == C.VERSION and e["version_distante"] == C.VERSION, e)
    v("etat : bibliotheque fermee, lanceurs compris", e["ouverte"] is False
      and not e["lanceurs_en_attente"], e["lanceurs_en_attente"])
    v("etat : Rushes-C propose, non coche", any(c["nom"] == "Rushes-C" and not c["coche"]
                                               for c in e["candidats"]), e["candidats"])
    r = F.mettre_a_jour(tache(), racine, {"projets": ["Rushes-C"], "moteur": False})
    v("app.html remplace", octets(os.path.join(app, "app.html")) ==
      octets(os.path.join(PROJET, "template", "_app", "app.html")))
    sauv = [n for n in os.listdir(app) if n.startswith("app.html.avant-maj-")]
    v("sauvegarde app.html.avant-maj-…", len(sauv) == 1 and
      octets(os.path.join(app, sauv[0])) == vieille, sauv)
    v("catalogue de Rushes-A intact", octets(os.path.join(
        app, "_donnees", "Rushes-A", "catalogue.json")) == cat_a)
    regl2 = C.lire_json(os.path.join(app, "bibliotheque.json"))
    v("Rushes-C ajoute a la liste blanche", regl2["projets"] ==
      ["Rushes-A", "Rushes-B", "Rushes-C"] and regl2["port"] == port, regl2)
    v("Rushes-C scanne, preuve identique", r["projets"] and r["projets"][0]["fiches"] == 1
      and r["preuve"] and r["preuve"][0]["identiques"], r)
    r3 = F.etat_mise_a_jour(racine)
    v("tout est a jour ensuite", r3["a_jour"], r3["a_faire"])

    # Une retouche a la main n est jamais ecrasee sans le demander.
    with io.open(os.path.join(app, "app.html"), "a", encoding="utf-8") as f:
        f.write("\n<!-- retouche maison -->\n")
    e4 = F.etat_mise_a_jour(racine)
    v("retouche maison : signalee, rien a faire",
      e4["modifies"] == ["_app/app.html"] and not e4["a_faire"], e4)
    F.mettre_a_jour(tache(), racine, {"moteur": False})
    v("retouche maison gardee telle quelle",
      b"retouche maison" in octets(os.path.join(app, "app.html")))
    F.mettre_a_jour(tache(), racine, {"moteur": False, "forcer": True})
    v("« forcer » la remplace, avec une deuxieme sauvegarde",
      octets(os.path.join(app, "app.html")) ==
      octets(os.path.join(PROJET, "template", "_app", "app.html"))
      and len([n for n in os.listdir(app) if n.startswith("app.html.avant-maj-")]) == 2)

    essais_purge(racine, app)

    print("\n=== FILMS : bibliotheque neuve ===")
    neuve = os.path.join(TRAVAIL, "Nouvelle bibliotheque")
    os.makedirs(neuve)
    a2 = F.analyser(tache(), neuve)
    v("dossier vide : disposition neuve proposee",
      a2["proposition"]["disposition"] == "neuve", a2["proposition"])
    r = F.installer(tache(), neuve, {"titre": "Neuve", "disposition": "neuve",
                                     "premier_projet": "Rushes", "port": a2["proposition"]["port"],
                                     "lecture_seule": True, "moteur": False})
    regl3 = C.lire_json(os.path.join(neuve, "_app", "bibliotheque.json"))
    v("projets\\Rushes et bibliotheques\\ crees",
      os.path.isdir(os.path.join(neuve, "projets", "Rushes"))
      and os.path.isdir(os.path.join(neuve, "bibliotheques")))
    v("bibliotheque.json : projets_dans = projets, sans liste blanche",
      regl3.get("projets_dans") == "projets" and "projets" not in regl3, regl3)
    v("port different de la premiere", regl3["port"] != port, regl3["port"])
    mod = F.charger_serveur(neuve)
    v("le serveur y voit le projet Rushes", mod.projets_disque() == ["Rushes"],
      mod.projets_disque())
    return racine


def essais_purge(racine, app):
    """Retirer les fiches manquantes, par le vrai serveur, en HTTP."""
    print("\n=== FILMS : retirer les fiches manquantes ===")
    mod = F.charger_serveur(racine)
    srv = mod.Serveur(("127.0.0.1", 0), mod.Poste)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    def req(methode, chemin, corps=None):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=120)
        c.request(methode, chemin,
                  body=json.dumps(corps) if corps is not None else None,
                  headers={"Content-Type": "application/json"})
        r = c.getresponse()
        return r.status, json.loads(r.read() or b"{}")

    donnees = os.path.join(app, "_donnees", "Rushes-A")
    catf = os.path.join(donnees, "catalogue.json")
    try:
        c, l = req("GET", "/api/projets")
        v("le serveur annonce « purge »", l.get("purge") is True, l.get("purge"))
        films = C.lire_json(catf)["films"]
        f3 = next(f for f in films if f["rel"] == "plan 03 (essai).mp4")
        f2 = next(f for f in films if f["rel"] == "plan 02 (essai).mp4")
        # f3 : un doublon efface, range dans un dossier virtuel.
        req("POST", "/api/rangement", {"projet": "Rushes-A", "dossiers": ["Tri"],
                                       "ou": {f3["id"]: "Tri"}})
        os.remove(os.path.join(racine, "Rushes-A", "plan 03 (essai).mp4"))
        # f2 : efface aussi, mais une sequence l utilise.
        os.makedirs(mod.montages_de("Rushes-A"), exist_ok=True)
        with io.open(os.path.join(mod.montages_de("Rushes-A"), "essai.json"), "w",
                     encoding="utf-8") as fh:
            json.dump({"clips": [{"uid": 1, "film": f2["id"], "pj": "Rushes-A",
                                  "fichier": f2["rel"]}]}, fh)
        os.remove(os.path.join(racine, "Rushes-A", "plan 02 (essai).mp4"))
        c, cat = req("GET", "/api/scan?projet=Rushes-A")
        absents = {f["id"] for f in cat["films"] if f.get("absent")}
        v("rescan : les deux fichiers effaces sont MISSING", absents == {f2["id"], f3["id"]},
          absents)
        journal = os.path.join(donnees, "journal.jsonl")
        journal_avant = octets(journal) if os.path.isfile(journal) else None
        rushes_avant = C.empreinte(os.path.join(racine, "Rushes-A"))
        c, r = req("POST", "/api/purger", {"projet": "Rushes-A"})
        v("purger : 1 retiree, 1 gardee car utilisee par une sequence",
          c == 200 and r["retires"] == 1 and [g["id"] for g in r["gardes"]] == [f2["id"]]
          and r["gardes"][0]["sequences"] == ["Rushes-A/essai"], (c, r))
        ids = [f["id"] for f in C.lire_json(catf)["films"]]
        v("catalogue : f3 parti, f2 garde, plan 01 intact",
          f3["id"] not in ids and f2["id"] in ids and len(ids) == 2, ids)
        v("reponse : les fiches restantes, pour l application",
          sorted(f["id"] for f in r["films"]) == sorted(ids))
        v("vignette de la fiche retiree effacee",
          not os.path.isfile(os.path.join(donnees, "_posters", f3["id"] + ".jpg")))
        v("sauvegarde catalogue.json.avant-purge (avec f3)",
          f3["id"] in json.dumps(C.lire_json(catf + ".avant-purge")))
        derniere = io.open(os.path.join(donnees, "purges.jsonl"),
                           encoding="utf-8").read().strip().splitlines()[-1]
        v("trace dans purges.jsonl", f3["id"] in derniere and "plan 03" in derniere)
        v("journal.jsonl (Undo on disk) pas touche", (octets(journal) if
          os.path.isfile(journal) else None) == journal_avant)
        c, rg = req("GET", "/api/rangement?projet=Rushes-A")
        v("rangement : f3 n y est plus", f3["id"] not in rg.get("ou", {}), rg)
        v("les rushes n ont pas bouge pendant le retrait",
          C.empreinte(os.path.join(racine, "Rushes-A")) == rushes_avant)
        c, r = req("POST", "/api/purger", {"projet": "Rushes-A"})
        v("second retrait : rien de plus (f2 toujours utilise)",
          c == 200 and r["retires"] == 0 and len(r["gardes"]) == 1, r)

        # Disque injoignable : le seul fichier de Rushes-C disparait.
        cache = os.path.join(TRAVAIL, "_hors-bibliotheque")
        os.makedirs(cache, exist_ok=True)
        src_c = os.path.join(racine, "Rushes-C", "c.mp4")
        shutil.move(src_c, os.path.join(cache, "c.mp4"))
        c, cat = req("GET", "/api/scan?projet=Rushes-C")
        catc = os.path.join(app, "_donnees", "Rushes-C", "catalogue.json")
        avant_c = octets(catc)
        c, r = req("POST", "/api/purger", {"projet": "Rushes-C"})
        v("aucun fichier visible : refus 409, rien retire",
          c == 409 and "disconnected" in r.get("erreur", "") and octets(catc) == avant_c,
          (c, r))
        # Le fichier revient avant tout rescan : la fiche est gardee.
        shutil.move(os.path.join(cache, "c.mp4"), src_c)
        c, r = req("POST", "/api/purger", {"projet": "Rushes-C"})
        v("fichier revenu : fiche gardee (« revenus »)",
          c == 200 and r["retires"] == 0 and r["revenus"] == 1, r)
    finally:
        srv.shutdown()
        srv.server_close()
    r = subprocess.run([sys.executable, "serveur.py", "--purger", "Rushes-C"],
                       cwd=app, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=120)
    v("ligne de commande : serveur.py --purger", r.returncode == 0 and
      "PURGE Rushes-C : 0 retirees, 0 gardees (sequences), 1 revenues" in r.stdout,
      r.stdout[-300:] + r.stderr[-300:])


# ---------------------------------------------------------------------------
#  Images
# ---------------------------------------------------------------------------
class ServeurBanque:
    """Le _serveur.py d une banque, servi dans ce processus sur un port libre."""

    def __init__(self, racine):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "banque_essai_%d" % id(self), os.path.join(racine, "serveur", "_serveur.py"))
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)
        from http.server import ThreadingHTTPServer
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), self.mod.Handler)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def req(self, methode, chemin, corps=None, type_="application/json"):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        h = {"Content-Type": type_, "Origin": "http://127.0.0.1:%d" % self.port,
             "Host": "127.0.0.1:%d" % self.port}
        c.request(methode, chemin, body=corps, headers=h)
        r = c.getresponse()
        return r.status, r.read(), r.getheader("Content-Type")

    def fermer(self):
        self.srv.shutdown()
        self.srv.server_close()


def essais_images(banque, vrac):
    print("\n=== IMAGES : analyse ===")
    a = I.analyser_dossier(banque)
    v("18 images dans 7 dossiers", a["images"] == 18 and a["dossiers"] == 7,
      (a["images"], a["dossiers"]))
    tete = a["candidats"][0]
    v("meilleur suffixe : _def (6 dossiers, sans doublon)", tete["suffixe"] == "_def"
      and tete["uniques"] == 6 and tete["multiples"] == 0, a["candidats"][:3])
    clean = next(c for c in a["candidats"] if c["suffixe"] == "_clean")
    v("_clean : 5 dossiers + 1 en double", clean["uniques"] == 5
      and clean["multiples"] == 1, clean)
    v("mode propose : dossier, _def", a["proposition"] == {"mode": "dossier",
                                                          "vignette": "_def"},
      a["proposition"])
    vc = I.verifier(banque, {"mode": "dossier", "vignette": "_clean"})
    v("_clean : bloque (eta a deux vignettes)", not vc["creable"] and vc["multiples"] == 1)
    v("diagnostic : les deux fichiers d eta", vc["diag_multiples"] == [
        {"dossier": "sheets/eta", "fichiers": ["eta-A_clean.jpg", "eta-B_clean.jpg"]}],
      vc["diag_multiples"])
    vd = I.verifier(banque, {"mode": "dossier", "vignette": "_def"})
    v("_def : 6 fiches, eta sans vignette, creable", vd["creable"] and vd["assets"] == 6
      and vd["sans_vignette"] == 1, vd)
    v("diagnostic : eta sans vignette, ses fichiers listes",
      vd["diag_absents"] and vd["diag_absents"][0]["dossier"] == "sheets/eta",
      vd["diag_absents"])

    print("\n=== IMAGES : installation ===")
    r = I.installer(tache(), banque, {"mode": "dossier", "vignette": "_def",
                                      "moteur": True, "raccourci": False})
    serv = os.path.join(banque, "serveur")
    for f in ("_serveur.py", "_scan.py", "NAVIGATEUR.html", "biblio.bat"):
        v("serveur/%s = modele" % f, octets(os.path.join(serv, f)) ==
          octets(os.path.join(PROJET, "modeles", "images", f)))
    v("_configuration.json", C.lire_json(os.path.join(serv, "_configuration.json")) ==
      {"type": "bibliotheque-configurable-v1", "mode": "dossier", "vignette": "_def"})
    d = C.lire_json(os.path.join(serv, "_donnees.json"))
    v("6 fiches indexees", len(d["items"]) == 6, len(d["items"]))
    vign = [n for n in os.listdir(os.path.join(serv, "_vignettes")) if n.endswith(".jpg")]
    v("6 vignettes", len(vign) == 6, vign)
    alpha = next(x for x in d["items"] if x["nom"] == "alpha")
    v("alpha : 3 images accessibles, vignette _def", len(alpha["fichiers"]) == 3
      and alpha["vignette"].endswith("alpha_def.png"), alpha)
    v("preuve : images identiques", r["preuve"][0]["identiques"], r["preuve"])
    v("moteur embarque", os.path.isfile(os.path.join(serv, "_python", "python.exe")))
    v("lanceur racine", b"serveur\\biblio.bat" in octets(os.path.join(banque, C.NOM_LANCEUR)))
    v("lanceur a icone + .bat cache",
      os.path.isfile(os.path.join(banque, "LANCER-LA-BIBLIOTHEQUE.exe"))
      and C.attribut_cache(os.path.join(banque, C.NOM_LANCEUR)))
    v("detection : bibliotheque d images compatible",
      C.detecter(banque)["genre"] == "images" and C.detecter(banque)["compatible"])

    print("\n=== IMAGES : le serveur de la banque ===")
    s = ServeurBanque(banque)
    try:
        c, corps, _ = s.req("GET", "/donnees")
        v("GET /donnees", c == 200 and len(json.loads(corps)["items"]) == 6, c)
        c, corps, _ = s.req("POST", "/marques", json.dumps({alpha["id"]: {
            "fav": True, "coul": 3, "t": int(time.time() * 1000)}}))
        v("POST /marques", c == 200 and json.loads(corps)[alpha["id"]]["coul"] == 3, corps[:200])
        c, corps, t = s.req("GET", "/vignette?id=" + alpha["miniature"])
        v("GET /vignette", c == 200 and corps[:3] == b"\xff\xd8\xff", (c, t))
        c, corps, t = s.req("GET", "/fichier?p=" + alpha["vignette"])
        v("GET /fichier (image d origine)", c == 200 and corps[:4] == b"\x89PNG", (c, t))
        import urllib.parse
        formulaire = urllib.parse.urlencode({"d": json.dumps({"fichiers": alpha["fichiers"]})})
        c, corps, t = s.req("POST", "/zip", formulaire, "application/x-www-form-urlencoded")
        noms = zipfile.ZipFile(io.BytesIO(corps)).namelist() if c == 200 else []
        v("POST /zip : les 3 images d alpha", sorted(noms) == sorted(alpha["fichiers"]), noms)
    finally:
        s.fermer()
    apres = C.empreinte(banque, exclure=["serveur", C.NOM_LANCEUR])
    v("images toujours identiques apres le serveur",
      C.comparer(C.empreinte(banque, exclure=["serveur", C.NOM_LANCEUR]), apres)["identiques"])

    print("\n=== IMAGES : une fiche par image ===")
    a2 = I.analyser_dossier(vrac)
    v("vrac : mode image propose", a2["proposition"]["mode"] == "image", a2["proposition"])
    r = I.installer(tache(), vrac, {"mode": "image", "moteur": False})
    d2 = C.lire_json(os.path.join(vrac, "serveur", "_donnees.json"))
    v("4 fiches, une par image, sous-dossier compris", len(d2["items"]) == 4
      and {x["nom"] for x in d2["items"]} == {"image 1", "image 2", "image 3", "autre"},
      [x["nom"] for x in d2["items"]])
    v("identifiants de 24 hexadecimaux (format des vignettes)",
      all(len(x["id"]) == 24 for x in d2["items"]))
    v("preuve vrac identique", r["preuve"][0]["identiques"])

    print("\n=== IMAGES : mise a jour ===")
    vieille_version(serv, os.path.join(serv, "NAVIGATEUR.html"),
                    "serveur/NAVIGATEUR.html")
    marques = octets(os.path.join(serv, "_marques.json"))
    donnees_avant = octets(os.path.join(serv, "_donnees.json"))
    e = I.etat_mise_a_jour(banque)
    v("etat : banque reconnue, NAVIGATEUR.html a remplacer", e["genre"] == "banque"
      and "serveur/NAVIGATEUR.html" in e["a_faire"], e["a_faire"])
    r = I.mettre_a_jour(tache(), banque, {"moteur": False})
    v("NAVIGATEUR.html remplace et sauvegarde",
      r["remplaces"] == ["serveur/NAVIGATEUR.html"]
      and octets(os.path.join(serv, "NAVIGATEUR.html")) ==
      octets(os.path.join(PROJET, "modeles", "images", "NAVIGATEUR.html"))
      and any(n.startswith("NAVIGATEUR.html.avant-maj-") for n in os.listdir(serv)), r)
    v("marques et index intacts", octets(os.path.join(serv, "_marques.json")) == marques
      and octets(os.path.join(serv, "_donnees.json")) == donnees_avant)
    v("tout est a jour ensuite", I.etat_mise_a_jour(banque)["a_jour"])

    # Une bibliotheque plus recente que le manifeste ne recule JAMAIS : le
    # cache de GitHub sert parfois l ancien version.json apres une publication.
    vieille_version(serv, os.path.join(serv, "_scan.py"), "serveur/_scan.py")
    vj = os.path.join(serv, "_version.json")
    enregistre = C.lire_json(vj, {})
    C.ecrire_json(vj, dict(enregistre, version="99.0.0"))
    e = I.etat_mise_a_jour(banque)
    v("plus recente que le manifeste : rien a faire", not e["a_faire"]
      and e["plus_recent"] and any(x["etat"] == "plus_recent" for x in e["fichiers"]),
      (e["a_faire"], e.get("plus_recent")))
    garde = octets(os.path.join(serv, "_scan.py"))
    I.mettre_a_jour(tache(), banque, {"moteur": False, "forcer": True})
    v("meme en forcant, aucun fichier ne recule",
      octets(os.path.join(serv, "_scan.py")) == garde)
    C.ecrire_json(vj, dict(enregistre, version=C.VERSION))
    I.mettre_a_jour(tache(), banque, {"moteur": False})
    v("et la mise a jour normale reprend son cours",
      I.etat_mise_a_jour(banque)["a_jour"])

    print("\n=== IMAGES : le bouton « Programme » de la banque ===")
    v("_maj.py depose dans une banque seule",
      os.path.isfile(os.path.join(serv, "_maj.py")))
    # Le depot local tient lieu de GitHub : meme code, meme verification des
    # empreintes, sans reseau.
    import pathlib
    os.environ["LIBRARY_EDITOR_DEPOT"] = pathlib.Path(PROJET).as_uri() + "/"
    s = ServeurBanque(banque)
    try:
        c, corps, _ = s.req("GET", "/maj")
        etat = json.loads(corps or b"{}")
        v("GET /maj : a jour", c == 200 and not etat.get("a_faire")
          and etat.get("version_distante") == C.VERSION, (c, etat))
        vieux = vieille_version(serv, os.path.join(serv, "_scan.py"),
                                "serveur/_scan.py")
        c, corps, _ = s.req("GET", "/maj")
        etat = json.loads(corps or b"{}")
        v("GET /maj : _scan.py a remplacer",
          etat.get("a_faire") == ["serveur/_scan.py"], etat.get("a_faire"))
        c, corps, _ = s.req("POST", "/maj", "{}")
        r = json.loads(corps or b"{}")
        v("POST /maj : remplace et sauvegarde", c == 200
          and r.get("faits") == ["serveur/_scan.py"]
          and octets(os.path.join(serv, "_scan.py")) ==
          octets(os.path.join(PROJET, "modeles", "images", "_scan.py"))
          and any(n.startswith("_scan.py.avant-maj-") for n in os.listdir(serv)),
          (c, r))
        v("l ancienne version est bien dans la sauvegarde",
          any(octets(os.path.join(serv, n)) == vieux for n in os.listdir(serv)
              if n.startswith("_scan.py.avant-maj-")))
    finally:
        s.fermer()
        os.environ.pop("LIBRARY_EDITOR_DEPOT", None)
    return banque


# ---------------------------------------------------------------------------
#  Racine a onglets (bibliotheque generale + banques)
# ---------------------------------------------------------------------------
def image_essai(chemin, couleur, taille="240x320"):
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    ff("-f", "lavfi", "-i", "color=c=%s:s=%s" % (couleur, taille), "-frames:v", "1", chemin)


def essais_racine():
    """Le dossier choisi devient une bibliotheque generale a onglets. Cas le
    plus delicat : il etait deja une banque unique (« biscuit multishots »)."""
    print("\n=== RACINE : preparation d un dossier comme « biscuit » ===")
    R = os.path.join(TRAVAIL, "Racine essai")
    for i, nom in enumerate(("batch-A", "batch-B", "elephants")):
        for j in range(3):
            image_essai(os.path.join(R, nom, "vue-%d.jpg" % j),
                        "0x%02d%02d99" % (20 + 10 * i, 30 + 20 * j))
    for a in ("alpha", "beta"):
        image_essai(os.path.join(R, "sheets", a, a + "_clean.jpg"), "0x228844")
        image_essai(os.path.join(R, "sheets", a, a + "_source.jpg"), "0x112244")
    image_essai(os.path.join(R, "a-la-racine.jpg"), "0xcccc11")
    os.makedirs(os.path.join(R, "vide"))
    # 1. l ancienne banque unique, celle de Library Editor 1.0
    res = I.installer(tache(), R, {"mode": "image", "moteur": False, "raccourci": False})
    v("ancienne banque : 14 fiches", res["fiches"] == 14, res["fiches"])
    serv0 = os.path.join(R, "serveur")
    d0 = C.lire_json(os.path.join(serv0, "_donnees.json"))
    par_vignette = {x["vignette"]: x["id"] for x in d0["items"]}
    C.ecrire_json(os.path.join(serv0, "_marques.json"), {
        par_vignette["batch-A/vue-1.jpg"]: {"fav": True, "coul": 0, "t": 1},
        par_vignette["sheets/alpha/alpha_clean.jpg"]: {"fav": False, "coul": 3, "t": 2},
        par_vignette["a-la-racine.jpg"]: {"fav": True, "coul": 0, "t": 3}})

    print("\n=== RACINE : analyse ===")
    a = I.analyser(tache(), R)
    v("sous-dossiers listes", [l["nom"] for l in a["lignes"]] ==
      ["batch-A", "batch-B", "elephants", "sheets", "vide"], [l["nom"] for l in a["lignes"]])
    v("racine conseillee", a["conseil"] == "racine", a["conseil"])
    v("ancienne banque reperee, marques comptees", a["ancienne_banque"] ==
      {"fiches": 14, "marques": 3}, a["ancienne_banque"])
    v("1 image a la racine signalee", a["a_la_racine"] == 1, a["a_la_racine"])
    v("dossier vide non coche", a["lignes"][-1]["coche"] is False)
    sheets = next(l for l in a["lignes"] if l["nom"] == "sheets")
    v("sheets : mode dossier, suffixe devine", sheets["proposition"]["mode"] == "dossier"
      and sheets["proposition"]["vignette"] in ("_clean", "_source"), sheets["proposition"])
    batch = next(l for l in a["lignes"] if l["nom"] == "batch-A")
    v("batch-A : images en vrac, mode image", batch["proposition"]["mode"] == "image"
      and batch["images"] == 3, batch)

    print("\n=== RACINE : installation (et conversion de la banque unique) ===")
    lignes = [{"nom": l["nom"], "coche": l["coche"],
               "mode": (l.get("proposition") or {}).get("mode", "image"),
               "vignette": (l.get("proposition") or {}).get("vignette", "")}
              for l in a["lignes"]]
    r = I.installer_racine(tache(), R, {"lignes": lignes, "moteur": False,
                                        "raccourci": False})
    v("4 banques preparees", [b["nom"] for b in r["banques"]] ==
      ["batch-A", "batch-B", "elephants", "sheets"], r["banques"])
    v("11 fiches en tout (sheets en mode dossier)", r["fiches"] == 11, r["fiches"])
    v("aucun echec", not r["echecs"], r["echecs"])
    v("empreintes identiques (racine et chaque banque)",
      len(r["preuve"]) == 5 and all(p["identiques"] for p in r["preuve"]),
      [p for p in r["preuve"] if not p["identiques"]])
    serv = os.path.join(R, "serveur")
    for f in ("_serveur.py", "NAVIGATEUR.html", "biblio-generale.bat", "_maj.py"):
        v("serveur/%s en place" % f, os.path.isfile(os.path.join(serv, f)))
    for f in ("_preparateur.py", "PREPARER.html", "preparer.bat"):
        v("preparateur/%s en place" % f, os.path.isfile(os.path.join(serv, "preparateur", f)))
    for f in ("_serveur.py", "_scan.py", "NAVIGATEUR.html", "biblio.bat"):
        v("modele %s = celui des banques" % f,
          octets(os.path.join(serv, "preparateur", "modeles", f)) ==
          octets(os.path.join(PROJET, "modeles", "images", f)))
    v("les deux lanceurs a icone, .bat caches",
      os.path.isfile(os.path.join(R, "Bibliotheque generale.exe"))
      and os.path.isfile(os.path.join(R, "Preparer une bibliotheque.exe"))
      and C.attribut_cache(os.path.join(R, "Bibliotheque generale.bat"))
      and C.attribut_cache(os.path.join(R, "Preparer une bibliotheque.bat")))
    v("ancien lanceur de banque retire de la racine",
      not os.path.exists(os.path.join(R, C.NOM_LANCEUR)))
    v("ancienne banque mise de cote, entiere",
      r["sauvegarde"] and os.path.isfile(os.path.join(r["sauvegarde"], "_donnees.json"))
      and os.path.isfile(os.path.join(r["sauvegarde"], C.NOM_LANCEUR)), r["sauvegarde"])
    v("2 marques reportees (celle de l image a la racine n a plus de banque)",
      r["marques_reportees"] == 2, r["marques_reportees"])
    mb = C.lire_json(os.path.join(R, "batch-A", "serveur", "_marques.json"), {})
    db = C.lire_json(os.path.join(R, "batch-A", "serveur", "_donnees.json"), {})
    id1 = next((x["id"] for x in db["items"] if x["vignette"] == "vue-1.jpg"), None)
    v("le favori de batch-A a suivi", mb.get(id1, {}).get("fav") is True, mb)
    ms = C.lire_json(os.path.join(R, "sheets", "serveur", "_marques.json"), {})
    v("la pastille de sheets a suivi", any(x.get("coul") == 3 for x in ms.values()), ms)
    v("images intactes", os.path.isfile(os.path.join(R, "a-la-racine.jpg"))
      and os.path.isfile(os.path.join(R, "batch-A", "vue-1.jpg")))
    v("dossier vide laisse tel quel", os.listdir(os.path.join(R, "vide")) == [])
    det = C.detecter(R)
    v("detection : racine a onglets, 4 banques",
      det["genre"] == "racine" and len(det["banques"]) == 4, det)
    v("recents : genre racine", any(x.get("genre") == "racine" and
      os.path.normcase(x["chemin"]) == os.path.normcase(R) for x in C.reglages()["recents"]))

    print("\n=== RACINE : la bibliotheque generale ouvre ses banques ===")
    import importlib.util
    spec = importlib.util.spec_from_file_location("racine_essai", os.path.join(serv, "_serveur.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    vues = mod.actualiser()
    v("4 banques servies, sans erreur", len(vues) == 4
      and all(x.get("url") and not x.get("erreur") for x in vues), vues)
    c = http.client.HTTPConnection(*vues[0]["url"].split("/")[2].split(":"), timeout=20)
    c.request("GET", "/donnees")
    rep = c.getresponse()
    corps = json.loads(rep.read())
    v("la premiere banque repond ses fiches", rep.status == 200 and corps["items"], rep.status)
    for s in mod.ACTIFS.values():
        s.shutdown()
        s.server_close()

    print("\n=== RACINE : mise a jour (racine + banques) ===")
    e = I.etat_mise_a_jour(R)
    v("etat : genre racine, tout a jour", e["genre"] == "racine" and e["a_jour"], e["a_faire"])
    v("le plan couvre les banques",
      any(x["fichier"].startswith("batch-A/") for x in e["fichiers"]),
      [x["fichier"] for x in e["fichiers"]][:6])
    vieille_version(serv, os.path.join(R, "sheets", "serveur", "_scan.py"),
                    "sheets/serveur/_scan.py")
    vieille_version(serv, os.path.join(serv, "NAVIGATEUR.html"), "serveur/NAVIGATEUR.html")
    e2 = I.etat_mise_a_jour(R)
    v("etat : le _scan.py d une banque et l accueil sont a remplacer",
      sorted(e2["a_faire"]) == ["serveur/NAVIGATEUR.html", "sheets/serveur/_scan.py"],
      e2["a_faire"])
    marques_sheets = octets(os.path.join(R, "sheets", "serveur", "_marques.json"))
    r2 = I.mettre_a_jour(tache(), R, {"moteur": False})
    v("les deux remplaces", sorted(r2["remplaces"]) ==
      ["serveur/NAVIGATEUR.html", "sheets/serveur/_scan.py"], r2["remplaces"])
    v("le _scan.py de la banque est celui du modele",
      octets(os.path.join(R, "sheets", "serveur", "_scan.py")) ==
      octets(os.path.join(PROJET, "modeles", "images", "_scan.py")))
    v("marques de la banque intactes",
      octets(os.path.join(R, "sheets", "serveur", "_marques.json")) == marques_sheets)
    v("sauvegarde dans la banque", any(n.startswith("_scan.py.avant-maj-")
      for n in os.listdir(os.path.join(R, "sheets", "serveur"))))
    v("tout est a jour ensuite", I.etat_mise_a_jour(R)["a_jour"])
    return R


# ---------------------------------------------------------------------------
#  Mise en ligne
# ---------------------------------------------------------------------------
def essais_enligne(film, banque):
    print("\n=== EN LIGNE : films ===")
    e = E.etat(film)
    v("etat : 3 projets scannes", len(e["projets"]) == 3, e["projets"])
    r = E.preparer(tache(), film, {"site": "https://montage.exemple.fr"})
    v("paquet : 1-site.zip + medias", [z["nom"] for z in r["zips"]][:2] ==
      ["1-site.zip", "2-medias-01.zip"], r["zips"])
    with zipfile.ZipFile(os.path.join(r["paquet"], "1-site.zip")) as z1:
        n1 = set(z1.namelist())
        cat = json.loads(z1.read("_data/Rushes-A/catalogue.json"))
    for f in ("app.html", "api.php", "config.php", ".htaccess", "_data/.htaccess",
              "_data/projets.json", "_data/Rushes-A/catalogue.json"):
        v("site : %s" % f, f in n1)
    # Ce qui doit partir : les fiches PRESENTES seulement (les manquantes ne
    # sont jamais publiees). Compte depuis les catalogues, pas en dur.
    donnees = os.path.join(film, "_app", "_donnees")
    presentes = {p: [f for f in C.lire_json(os.path.join(donnees, p, "catalogue.json"))["films"]
                     if not f.get("absent")]
                 for p in ("Rushes-A", "Rushes-B", "Rushes-C")}
    v("catalogue en ligne : proxy .mp4, seulement les fiches presentes",
      all(f["proxy"].endswith(".mp4") for f in cat["films"])
      and sorted(f["id"] for f in cat["films"]) == sorted(f["id"] for f in presentes["Rushes-A"]),
      [f["rel"] for f in cat["films"]])
    v("aucun chemin absolu en ligne", ":\\" not in json.dumps(cat) and
      TRAVAIL.replace("\\", "/") not in json.dumps(cat))
    with zipfile.ZipFile(os.path.join(r["paquet"], "2-medias-01.zip")) as z2:
        n2 = z2.namelist()
    attendus = sum(len(x) for x in presentes.values())
    v("medias : %d proxys, un par fiche presente (son en .m4a)" % attendus,
      len(n2) == attendus and any(n.endswith("ambiance.m4a") for n in n2), n2)
    deb = io.open(os.path.join(r["paquet"], "_deballer.php"), encoding="utf-8").read()
    v("_deballer.php : cle tiree", r["cle"] in deb and "%%CLE%%" not in deb)
    v("url de deballage", r["url_deballer"] == "https://montage.exemple.fr/_deballer.php?cle="
      + r["cle"], r["url_deballer"])
    v("LISEZ-MOI et GUIDE", os.path.isfile(os.path.join(r["paquet"], "LISEZ-MOI.txt"))
      and os.path.isfile(os.path.join(r["paquet"], "GUIDE.html")))
    r2 = E.preparer(tache(), film, {"seulement_changes": True})
    v("seulement les changements : aucun media ne repart",
      [z["nom"] for z in r2["zips"]] == ["1-site.zip"], r2["zips"])

    print("\n=== EN LIGNE : images ===")
    r = E.preparer(tache(), banque, {})
    with zipfile.ZipFile(os.path.join(r["paquet"], "1-site.zip")) as z:
        idx = z.read("index.html").decode("utf-8")
        noms = set(z.namelist())
    v("index.html : routes relatives", all(x not in idx for x in E.ROUTES_IMAGES)
      and "'donnees'" in idx and "'fichier?p='" in idx)
    v("site images : api.php, .htaccess, _data protege, index, marques",
      {"api.php", ".htaccess", "_data/.htaccess", "_data/_donnees.json",
       "_data/_marques.depot.json"} <= noms)
    with zipfile.ZipFile(os.path.join(r["paquet"], "2-medias-01.zip")) as z3:
        medias = z3.namelist()
    v("16 images publiees (celles des 6 fiches)", len(medias) == 16, len(medias))
    v("rien d ecrit hors de serveur/_enligne", not os.path.exists(os.path.join(banque, "_enligne")))


if __name__ == "__main__":
    if not FFMPEG:
        sys.exit("ffmpeg est necessaire pour fabriquer les donnees d essai.")
    print("Dossier de travail : %s" % TRAVAIL)
    film, banque, vrac = donnees()
    essais_films(film)
    essais_images(banque, vrac)
    essais_racine()
    essais_enligne(film, banque)
    print("\n%d reussites, %d echec(s)" % (ok, ko))
    sys.exit(1 if ko else 0)

# -*- coding: utf-8 -*-
"""Bibliotheques de films : analyse, installation, mise a jour, premier scan.

Le modele (template/_app : serveur.py, app.html) n est pas reecrit : on le
depose, on le regle par bibliotheque.json, et on appelle SES fonctions
scanner() et fabriquer_posters() pour le premier scan. Les invariants du
brief (section 12) tiennent par construction :

  1. rien n est ecrit dans un dossier de rushes : donnees dans
     _app/_donnees, lecture seule cochee par defaut, empreinte avant/apres ;
  2. les identifiants sont ceux que fabrique serveur.py, jamais les notres ;
  7. un port par bibliotheque, choisi et memorise ici.
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
import uuid

import le_commun as C

# Ce que Chrome sait lire (piege 2 du brief).
LISIBLES = {"h264", "vp8", "vp9", "av1"}
SELON_MACHINE = {"hevc"}
PIX_LISIBLES = {"yuv420p", "yuvj420p", "", None}
# Noms de dossiers qui ne sont jamais des rushes.
TECHNIQUES = {"_app", "serveur", "node_modules", "__pycache__", "$recycle.bin",
              "system volume information"}

FORMATS = [[1920, 1080], [3840, 2160], [1280, 720], [2048, 858], [1920, 1440],
           [1440, 1080], [1080, 1920], [1080, 1350], [1080, 1080]]


def ffprobe():
    return shutil.which("ffprobe")


def ffmpeg():
    return shutil.which("ffmpeg")


# ---------------------------------------------------------------------------
#  Analyse
# ---------------------------------------------------------------------------
def sonder_video(chemin):
    """Codec, taille d image, cadence et format de pixels du premier flux."""
    fp = ffprobe()
    if not fp:
        return None
    try:
        r = subprocess.run([fp, "-v", "error", "-select_streams", "v:0",
                            "-show_entries",
                            "stream=codec_name,width,height,r_frame_rate,pix_fmt",
                            "-of", "json", chemin],
                           capture_output=True, timeout=25,
                           creationflags=C.SANS_CONSOLE)
        s = (json.loads(r.stdout or b"{}").get("streams") or [{}])[0]
    except Exception:
        return None
    fps = 0.0
    try:
        a, b = str(s.get("r_frame_rate", "0/1")).split("/")
        fps = round(int(a) / int(b), 3) if int(b) else 0.0
    except Exception:
        pass
    return {"codec": s.get("codec_name") or "?", "w": s.get("width"),
            "h": s.get("height"), "fps": fps, "pix": s.get("pix_fmt") or ""}


def lisibilite(sonde):
    if not sonde:
        return "?"
    c = sonde["codec"]
    if c in LISIBLES:
        # Le H.264 10 bits ou 4:2:2 ne se lit pas dans Chrome.
        if c == "h264" and sonde.get("pix") not in PIX_LISIBLES:
            return "non"
        return "oui"
    if c in SELON_MACHINE:
        return "selon"
    return "non"


def compter(dossier, tache=None):
    """Parcourt un dossier comme le scan de serveur.py : les sous-dossiers
    qui commencent par _ ou . sont ignores."""
    n = {"videos": 0, "sons": 0, "images": 0, "ignorees": 0, "autres": 0,
         "octets": 0}
    videos = []
    for rep, sous, noms in os.walk(dossier):
        sous[:] = sorted(x for x in sous if not x.startswith((".", "_")))
        for nom in noms:
            if nom.startswith("._"):
                continue
            ext = os.path.splitext(nom)[1].lower()
            p = os.path.join(rep, nom)
            if ext in C.EXT_VIDEO:
                n["videos"] += 1
                videos.append(p)
            elif ext in C.EXT_AUDIO:
                n["sons"] += 1
            elif ext in C.EXT_IMAGE:
                n["images"] += 1
                continue
            elif ext in C.EXT_VIDEO_IGNOREES:
                n["ignorees"] += 1
                continue
            else:
                n["autres"] += 1
                continue
            try:
                n["octets"] += os.path.getsize(p)
            except OSError:
                pass
        if tache:
            tache.verifier()
    return n, sorted(videos)


def echantillon(videos, k=3):
    if len(videos) <= k:
        return videos
    return [videos[0], videos[len(videos) // 2], videos[-1]]


def ligne_dossier(chemin, nom, tache=None):
    n, videos = compter(chemin, tache)
    sondes = [s for s in (sonder_video(v) for v in echantillon(videos)) if s]
    codecs, tailles, cadences = {}, {}, {}
    lisible = "?"
    for s in sondes:
        codecs[s["codec"]] = codecs.get(s["codec"], 0) + 1
        if s["w"] and s["h"]:
            k = "%dx%d" % (s["w"], s["h"])
            tailles[k] = tailles.get(k, 0) + 1
        if s["fps"]:
            cadences[s["fps"]] = cadences.get(s["fps"], 0) + 1
    if sondes:
        vus = {lisibilite(s) for s in sondes}
        # Un dossier ou certaines videos seulement ne se liront pas : « en
        # partie », pas « illisible » — le mot ferait peur pour rien.
        if vus == {"non"}:
            lisible = "non"
        elif "non" in vus:
            lisible = "partiel"
        elif "selon" in vus:
            lisible = "selon"
        else:
            lisible = "oui"
    dominant = lambda d: max(d, key=d.get) if d else ""
    return dict(n, nom=nom, codec=dominant(codecs), resolution=dominant(tailles),
                fps=dominant(cadences) or 0, lisible=lisible,
                sondes=len(sondes), coche=bool(n["videos"] or n["sons"]))


def analyser(tache, racine):
    """Liste les sous-dossiers au fur et a mesure : sur un disque reseau,
    peser mille fichiers prend une demi-minute (piege 4)."""
    racine = os.path.abspath(racine)
    tache.etape_suivante("Inventaire des sous-dossiers")
    noms = []
    for n in sorted(os.listdir(racine), key=lambda x: x.lower()):
        p = os.path.join(racine, n)
        if (os.path.isdir(p) and not n.startswith((".", "_"))
                and n.lower() not in TECHNIQUES):
            noms.append(n)
    # Des medias poses directement a la racine : ils ne seraient vus par
    # aucun projet (un projet est un sous-dossier).
    a_la_racine = {"videos": 0, "sons": 0}
    for n in os.listdir(racine):
        e = os.path.splitext(n)[1].lower()
        if os.path.isfile(os.path.join(racine, n)):
            if e in C.EXT_VIDEO:
                a_la_racine["videos"] += 1
            elif e in C.EXT_AUDIO:
                a_la_racine["sons"] += 1
    resultat = {"racine": racine, "nom": os.path.basename(racine) or racine,
                "lignes": [], "a_la_racine": a_la_racine,
                "ffprobe": bool(ffprobe()), "ffmpeg": bool(ffmpeg()),
                "existante": C.detecter(racine),
                "parent": os.path.dirname(racine)}
    tache.resultat_partiel = resultat
    tache.etape_suivante("Analyse de %d dossier(s)" % len(noms), len(noms))
    for i, nom in enumerate(noms):
        tache.verifier()
        tache.ligne("Analyse de %s..." % nom)
        ligne = ligne_dossier(os.path.join(racine, nom), nom, tache)
        resultat["lignes"].append(ligne)
        tache.progres(i + 1)
    resultat["proposition"] = proposer(resultat)
    tache.terminer_etapes()
    return resultat


def proposer(analyse):
    """Titre, disposition, format et port proposes."""
    lignes = [l for l in analyse["lignes"] if l["coche"]]
    poids = {}
    for l in lignes:
        if l["resolution"]:
            poids[l["resolution"]] = poids.get(l["resolution"], 0) + max(1, l["videos"])
    fmt = None
    if poids:
        w, h = max(poids, key=poids.get).split("x")
        fmt = [int(w), int(h)]
    try:
        port = C.port_pour_bibliotheque(analyse["racine"])
    except Exception:
        port = None
    return {"titre": analyse["nom"], "format": fmt, "port": port,
            "disposition": "existante" if lignes else "neuve",
            "lecture_seule": True}


# ---------------------------------------------------------------------------
#  Installation
# ---------------------------------------------------------------------------
def charger_serveur(racine):
    """Importe le serveur.py de CETTE bibliotheque, comme le fait
    tests/serveur_essais.py : on eprouve le vrai code, pas une copie."""
    chemin = os.path.join(racine, "_app", "serveur.py")
    nom = "serveur_%s" % uuid.uuid4().hex[:8]
    spec = importlib.util.spec_from_file_location(nom, chemin)
    mod = importlib.util.module_from_spec(spec)
    sys.dont_write_bytecode = True
    spec.loader.exec_module(mod)
    return mod


def reglages_json(r):
    """Le bibliotheque.json de cette bibliotheque (brief, section 5)."""
    out = {"titre": r["titre"].strip() or r["nom"]}
    if r["disposition"] == "neuve":
        out["projets_dans"] = "projets"
        out["bibliotheques_dans"] = "bibliotheques"
    else:
        out["projets_dans"] = "."
        out["projets"] = list(r["projets"])
    out["donnees"] = "_app/_donnees"
    out["lecture_seule"] = bool(r.get("lecture_seule", True))
    out["port"] = int(r["port"])
    if r.get("format"):
        out["format"] = [int(r["format"][0]), int(r["format"][1])]
    return out


def installer(tache, racine, r):
    racine = os.path.abspath(racine)
    r = dict(r)
    r["nom"] = os.path.basename(racine)
    t0 = time.time()

    # ---- controles : on refuse avant d avoir rien ecrit -------------------
    tache.etape_suivante("Contrôles")
    if not os.path.isdir(racine):
        raise ValueError("Dossier introuvable : %s" % racine)
    if os.path.exists(os.path.join(racine, "_app")):
        raise ValueError("Ce dossier contient déjà un _app : utilisez "
                         "« Mettre à jour » pour ne pas écraser ses données.")
    if not C.ecriture_possible(racine):
        raise ValueError("Impossible d'écrire dans ce dossier.")
    r["port"] = int(r.get("port") or C.port_pour_bibliotheque(racine))
    if r["port"] in C.PORTS_RESERVES:
        raise ValueError("Le port %d est déjà celui d'une autre bibliothèque."
                         % r["port"])
    projets = [p for p in (r.get("projets") or []) if p]
    if r["disposition"] == "existante":
        for p in projets:
            if (p.startswith((".", "_")) or os.sep in p or "/" in p
                    or not os.path.isdir(os.path.join(racine, p))):
                raise ValueError("Dossier de rushes invalide : %s" % p)
        if not projets:
            raise ValueError("Cochez au moins un dossier de rushes.")
    else:
        premier = (r.get("premier_projet") or "Rushes").strip()
        if (not premier or premier.startswith((".", "_"))
                or any(c in premier for c in '<>:"/\\|?*')):
            raise ValueError("Nom de premier projet invalide.")
        projets = [premier]
    r["projets"] = projets
    tache.ligne("Port %d, %d projet(s), lecture seule : %s"
                % (r["port"], len(projets),
                   "oui" if r.get("lecture_seule", True) else "non"))

    # ---- empreinte avant --------------------------------------------------
    avant = {}
    if r["disposition"] == "existante":
        tache.etape_suivante("Empreinte des dossiers de rushes (avant)",
                             len(projets))
        for i, p in enumerate(projets):
            avant[p] = C.empreinte(os.path.join(racine, p), annule=tache.annulee)
            tache.ligne("%s : %d entrées relevées" % (p, len(avant[p])))
            tache.progres(i + 1)
            tache.verifier()

    # ---- l application, dans un dossier provisoire puis publiee d un coup --
    tache.etape_suivante("Copie de l'application")
    provisoire = os.path.join(racine, ".installation-" + uuid.uuid4().hex[:8])
    os.makedirs(provisoire)
    try:
        for f in ("serveur.py", "app.html", "LANCER.bat"):
            shutil.copy2(C.modele_films(f), os.path.join(provisoire, f))
        # La mise a jour depuis GitHub (bouton « Update » de la bibliotheque).
        shutil.copy2(C.maj_py(), os.path.join(provisoire, "_maj.py"))
        os.makedirs(os.path.join(provisoire, "_polices"), exist_ok=True)
        os.makedirs(os.path.join(provisoire, "_donnees"), exist_ok=True)
        C.ecrire_json(os.path.join(provisoire, "bibliotheque.json"),
                      reglages_json(r))
        tache.ligne("serveur.py, app.html, LANCER.bat, _maj.py, bibliotheque.json")
        if r.get("moteur", True):
            tache.etape_suivante("Moteur Python embarqué")
            n = C.poser_moteur(os.path.join(provisoire, "_python"),
                               lambda f, t: tache.progres(f, t))
            tache.ligne("Moteur Python : %d fichiers" % n if n else
                        "Moteur Python indisponible dans cette version : "
                        "la bibliothèque utilisera le Python installé.",
                        "info" if n else "alerte")
        tache.verifier()
        os.rename(provisoire, os.path.join(racine, "_app"))
    finally:
        if os.path.isdir(provisoire):
            shutil.rmtree(provisoire, ignore_errors=True)
    lanceur = os.path.join(racine, C.NOM_LANCEUR)
    C.sauvegarder(lanceur, "installation")
    # Le lanceur .bat (cache) et son .exe a l icone de Library Editor.
    C.poser_lanceur(racine, C.NOM_LANCEUR, C.modele_films("LANCER-LA-BIBLIOTHEQUE.bat"))
    import le_maj
    le_maj.marquer_installe("films", racine)
    if r["disposition"] == "neuve":
        os.makedirs(os.path.join(racine, "projets", projets[0]), exist_ok=True)
        os.makedirs(os.path.join(racine, "bibliotheques"), exist_ok=True)
        tache.ligne("Dossiers créés : projets\\%s et bibliotheques\\" % projets[0])
    C.noter_recent(racine, "films", r["titre"], r["port"])

    # ---- premier scan, avec le vrai serveur.py ----------------------------
    fiches = premier_scan(tache, racine, projets)

    # ---- la preuve ----------------------------------------------------------
    preuve = []
    if avant:
        tache.etape_suivante("Empreinte des dossiers de rushes (après)",
                             len(projets))
        for i, p in enumerate(projets):
            apres = C.empreinte(os.path.join(racine, p))
            cmp_ = C.comparer(avant[p], apres)
            cmp_["projet"] = p
            preuve.append(cmp_)
            tache.ligne("%s : %d entrées, %s" % (
                p, cmp_["entrees"],
                "identiques" if cmp_["identiques"] else "DIFFERENCES"),
                "ok" if cmp_["identiques"] else "erreur")
            tache.progres(i + 1)

    raccourci = None
    if r.get("raccourci"):
        tache.etape_suivante("Raccourci sur le Bureau")
        try:
            icone = os.path.join(racine, "_app", "_python", "python.exe")
            raccourci = C.raccourci_bureau(
                racine, r["titre"], icone if os.path.isfile(icone) else None)
            tache.ligne("Raccourci : %s" % raccourci, "ok")
        except Exception as e:
            tache.ligne("Raccourci non créé : %s" % e, "alerte")
    tache.terminer_etapes()
    return {"genre": "films", "racine": racine, "titre": r["titre"],
            "port": r["port"], "url": "http://127.0.0.1:%d/" % r["port"],
            "projets": fiches, "preuve": preuve, "raccourci": raccourci,
            "disposition": r["disposition"],
            "moteur": os.path.isfile(os.path.join(racine, "_app", "_python",
                                                  "python.exe")),
            "ffmpeg": bool(ffmpeg()), "duree": round(time.time() - t0)}


def premier_scan(tache, racine, projets):
    """Sondage des medias puis vignettes, projet par projet, avec une vraie
    progression. Reprenable : un catalogue existant est fusionne, une
    vignette deja faite n est jamais refaite (brief, section 6)."""
    import threading
    mod = charger_serveur(racine)
    bilan = []
    for p in projets:
        tache.verifier()
        tache.etape_suivante("Scan de %s" % p)
        fin = {"ok": False}

        def suivre():
            while not fin["ok"]:
                s = mod.SCAN
                if s.get("projet") == p:
                    tache.progres(s.get("fait", 0), s.get("total", 0))
                time.sleep(0.25)
        threading.Thread(target=suivre, daemon=True).start()
        try:
            cat = mod.scanner(p, bavard=False)
        finally:
            fin["ok"] = True
        films = [f for f in cat.get("films", []) if not f.get("absent")]
        tache.progres(len(films), len(films))
        tache.ligne("%s : %d fiches" % (p, len(films)), "ok")

        a_faire = [f for f in films if not f.get("son_seul")]
        posters = 0
        if a_faire and mod.FFMPEG:
            tache.etape_suivante("Vignettes de %s" % p, len(a_faire))
            # fabriquer_posters() compte un essai rate comme fait, et le
            # retente a l appel suivant : on s arrete quand deux tours de
            # suite n ajoutent plus une seule vignette (video illisible).
            sans_progres = 0
            while True:
                tache.verifier()
                avant_tour = posters
                faits = mod.fabriquer_posters(p, budget=4, bavard=False)
                posters = sum(1 for f in a_faire
                              if os.path.isfile(mod.poster_de(p, f)))
                tache.progres(posters, len(a_faire))
                if not faits:
                    break
                sans_progres = sans_progres + 1 if posters == avant_tour else 0
                if sans_progres >= 2:
                    break
            manque = len(a_faire) - posters
            tache.ligne("%s : %d vignettes%s" % (
                p, posters, (", %d impossible(s) : vidéo illisible par "
                             "ffmpeg ?" % manque) if manque else ""),
                "ok" if not manque else "alerte")
        elif a_faire:
            tache.ligne("ffmpeg introuvable : les vignettes seront faites par "
                        "le navigateur à la première ouverture.", "alerte")
        bilan.append({"projet": p, "fiches": len(films),
                      "videos": len(a_faire), "posters": posters,
                      "duree_totale": round(sum(f.get("s") or 0 for f in films))})
    return bilan


# ---------------------------------------------------------------------------
#  Mise a jour d une bibliotheque existante (decision D du brief)
# ---------------------------------------------------------------------------
def etat_mise_a_jour(racine):
    """Ce que la mise a jour ferait, sans rien faire (moteur commun : voir
    le_maj et modeles/commun/_maj.py)."""
    import le_maj
    d = C.detecter(racine)
    if not d or d["genre"] != "films":
        raise ValueError("Ce dossier n'est pas une bibliothèque de films.")
    return le_maj.etat(racine)


def mettre_a_jour(tache, racine, options):
    """Met le programme a jour (sauvegarde .avant-maj-… d abord) et ajoute
    les dossiers coches. Ne touche JAMAIS _donnees, _polices, _presets, ni
    aucun dossier de rushes."""
    import le_maj
    return le_maj.appliquer(tache, racine, options)


def ajouter_projets(tache, racine, nouveaux, motif):
    """Ajoute des dossiers de rushes a la liste blanche, les scanne, et
    prouve qu ils n ont pas bouge. bibliotheque.json est sauvegarde avant."""
    app = os.path.join(racine, "_app")
    regl_chemin = os.path.join(app, "bibliotheque.json")
    regl = C.lire_json(regl_chemin, None)
    ajoutes = []
    if regl is not None and regl.get("projets_dans") == "." and nouveaux:
        deja = list(regl.get("projets") or [])
        ajoutes = [p for p in nouveaux if p not in deja
                   and os.path.isdir(os.path.join(racine, p))
                   and not p.startswith((".", "_"))]
        if ajoutes:
            tache.etape_suivante("Ajout de %d dossier(s)" % len(ajoutes))
            C.sauvegarder(regl_chemin, motif)
            regl["projets"] = deja + ajoutes
            C.ecrire_json(regl_chemin, regl)
            tache.ligne("Dossiers ajoutés : %s" % ", ".join(ajoutes), "ok")
    preuve, fiches = [], []
    if ajoutes:
        avant = {p: C.empreinte(os.path.join(racine, p)) for p in ajoutes}
        fiches = premier_scan(tache, racine, ajoutes)
        for p in ajoutes:
            cmp_ = C.comparer(avant[p], C.empreinte(os.path.join(racine, p)))
            cmp_["projet"] = p
            preuve.append(cmp_)
    return ajoutes, fiches, preuve

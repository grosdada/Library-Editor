# -*- coding: utf-8 -*-
"""Bibliotheques d images : analyse, suffixe de vignette, installation.

Le systeme deposé est celui des banques d assets de David (serveur/ :
_serveur.py, _scan.py, NAVIGATEUR.html) : favoris, pastilles de couleur,
recherche, fiches detaillees, ZIP. Aucune image n est deplacee, renommee ni
supprimee ; tout ce qui est ecrit va dans serveur/, et l installation le
prouve par une empreinte avant / apres.

Deux facons de faire une fiche :
  - « dossier » : un sous-dossier = un asset, sa vignette est l image dont
    le nom finit par un suffixe (_clean, _def, _source…) — le mode des banques ;
  - « image »   : une fiche par image, pour un dossier d images en vrac.
"""
import importlib.util
import os
import shutil
import threading
import time
import uuid

import le_commun as C
import le_maj

MODELE = ("_serveur.py", "_scan.py", "NAVIGATEUR.html", "biblio.bat")
SEPARATEURS = "_-. "
CONNUS = ("_clean", "_def", "_source", "_sheet", "_grid", "_base",
          "_miniature", "_knoll", "_thumb", "_vignette", "_main", "_cover")

_INDEXEUR = None


def charger_indexeur(chemin=None):
    """Le _scan.py du modele (ou celui d une bibliotheque) comme module."""
    global _INDEXEUR
    if chemin is None and _INDEXEUR is not None:
        return _INDEXEUR
    src = chemin or C.modele_images("_scan.py")
    spec = importlib.util.spec_from_file_location(
        "indexeur_%s" % uuid.uuid4().hex[:8], src)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if chemin is None:
        _INDEXEUR = mod
    return mod


# ---------------------------------------------------------------------------
#  Analyse
# ---------------------------------------------------------------------------
def suffixes_de(stem):
    """Les fins de nom candidates : a partir des trois derniers separateurs.
    « avenue-des-monolithes-A_def » -> _def, -A_def, -monolithes-A_def."""
    pos = [i for i, c in enumerate(stem) if c in SEPARATEURS and i > 0]
    out = []
    for i in reversed(pos[-3:]):
        s = stem[i:]
        if 2 <= len(s) <= 40 and not s[1:].isdigit():
            out.append(s)
    return out


def classer_suffixes(par_dossier):
    """Pour chaque suffixe : dans combien de dossiers il designe UNE seule
    image (bon), et dans combien plusieurs (bloquant a la creation)."""
    uniques, multiples, forme = {}, {}, {}
    for images in par_dossier.values():
        compte = {}
        for p in images:
            vus = set()
            for s in suffixes_de(p.stem):
                k = s.casefold()
                if k in vus:
                    continue
                vus.add(k)
                forme.setdefault(k, s)
                compte[k] = compte.get(k, 0) + 1
        for k, n in compte.items():
            if n == 1:
                uniques[k] = uniques.get(k, 0) + 1
            else:
                multiples[k] = multiples.get(k, 0) + 1
    connus = {c.casefold() for c in CONNUS}
    cles = sorted(set(uniques) | set(multiples),
                  key=lambda k: (-uniques.get(k, 0), multiples.get(k, 0),
                                 k not in connus, len(k)))
    return [{"suffixe": forme[k], "uniques": uniques.get(k, 0),
             "multiples": multiples.get(k, 0)} for k in cles[:8]]


TECHNIQUES = {"serveur", "node_modules", "__pycache__", "$recycle.bin",
              "system volume information"}


def analyser(tache, racine):
    """La racine a onglets : chaque sous-dossier est une banque possible,
    avec son suffixe de vignette devine. Les lignes arrivent au fil de
    l eau (un disque reseau est lent)."""
    racine = os.path.abspath(racine)
    det = C.detecter(racine)
    if det and det["genre"] == "films":
        raise ValueError("Ce dossier est une bibliothèque de films.")
    tache.etape_suivante("Inventaire des sous-dossiers")
    noms = [n for n in sorted(os.listdir(racine), key=str.lower)
            if os.path.isdir(os.path.join(racine, n))
            and not n.startswith((".", "_")) and n.lower() not in TECHNIQUES]
    ancienne = None
    if det and det["genre"] == "images":
        # Une banque UNIQUE installee dans ce dossier (Library Editor 1.0) :
        # elle sera mise de cote, et chaque sous-dossier deviendra une banque.
        serv = os.path.join(racine, "serveur")
        donnees = C.lire_json(os.path.join(serv, "_donnees.json"), {}) or {}
        marques = C.lire_json(os.path.join(serv, "_marques.json"), {}) or {}
        ancienne = {"fiches": len(donnees.get("items") or []),
                    "marques": sum(1 for v in marques.values()
                                   if isinstance(v, dict) and (v.get("fav") or v.get("coul")))}
    ix = charger_indexeur()
    a_la_racine = sum(1 for n in os.listdir(racine)
                      if os.path.splitext(n)[1].lower() in ix.EXTENSIONS
                      and os.path.isfile(os.path.join(racine, n)))
    resultat = {"racine": racine, "nom": os.path.basename(racine) or racine,
                "lignes": [], "existante": det, "ancienne_banque": ancienne,
                "a_la_racine": a_la_racine}
    tache.resultat_partiel = resultat
    tache.etape_suivante("Analyse de %d dossier(s)" % len(noms), len(noms))
    for i, n in enumerate(noms):
        tache.verifier()
        p = os.path.join(racine, n)
        if C.est_banque(p):
            conf = C.lire_json(os.path.join(p, "serveur", "_configuration.json"), None)
            ligne = {"nom": n, "etat": "banque", "configuration": conf, "coche": False,
                     "compatible": bool(conf and conf.get("type") == ix.TYPE)}
        else:
            a = analyser_dossier(p)
            ligne = {"nom": n, "etat": "nouvelle" if a["images"] else "vide",
                     "images": a["images"], "dossiers": a["dossiers"],
                     "taille": a["taille"], "octets": a["octets"],
                     "candidats": a["candidats"][:6], "proposition": a["proposition"],
                     "coche": bool(a["images"])}
        resultat["lignes"].append(ligne)
        tache.progres(i + 1)
    # Une racine a onglets n a de sens que s il y a des banques a y mettre :
    # sinon, ce dossier est lui-meme une banque (images en vrac a la racine).
    avec = [l for l in resultat["lignes"] if l.get("images") or l["etat"] == "banque"]
    resultat["racine_possible"] = bool(avec)
    resultat["conseil"] = "racine" if avec else "banque"
    resultat["banque"] = analyser_dossier(racine) if not avec else None
    tache.terminer_etapes()
    return resultat


def analyser_dossier(racine):
    """Un dossier = une banque possible : ses images, son suffixe devine."""
    racine = os.path.abspath(racine)
    ix = charger_indexeur()
    chemins, erreurs = ix.fichiers(racine)
    par_dossier = {}
    octets = 0
    for p in chemins:
        par_dossier.setdefault(p.parent, []).append(p)
        try:
            octets += p.stat().st_size
        except OSError:
            pass
    from pathlib import Path
    racine_p = Path(racine).resolve()
    a_la_racine = len(par_dossier.get(racine_p, []))
    candidats = classer_suffixes(par_dossier)
    n_dossiers = len(par_dossier)
    meilleur = candidats[0] if candidats else None
    # Le mode dossier n a de sens que si un suffixe designe une vignette
    # unique dans au moins la moitie des dossiers d images.
    mode = "dossier" if (meilleur and n_dossiers > 1
                         and meilleur["uniques"] >= max(2, n_dossiers / 2)) else "image"
    serveur = os.path.join(racine, "serveur")
    exemples = sorted({p.parent.relative_to(racine_p).as_posix()
                       for p in chemins})[:6]
    return {"racine": racine, "nom": os.path.basename(racine) or racine,
            "images": len(chemins), "dossiers": n_dossiers,
            "a_la_racine": a_la_racine, "octets": octets,
            "taille": C.taille_humaine(octets), "erreurs": erreurs[:10],
            "candidats": candidats, "exemples_dossiers": exemples,
            "existante": C.detecter(racine),
            "serveur_present": os.path.exists(serveur),
            "proposition": {"mode": mode,
                            "vignette": meilleur["suffixe"] if meilleur else ""}}


def verifier(racine, reglage):
    """« Verifier les correspondances » : exactement ce que fera la
    creation, et pour chaque dossier a probleme, les fichiers en cause."""
    racine = os.path.abspath(racine)
    ix = charger_indexeur()
    config = ix.configuration(reglage_config(reglage))
    d = ix.analyser(racine, config)
    st = d["stats"]
    diag_absents, diag_multiples = [], []
    if config.get("mode") == "dossier":
        from pathlib import Path
        base = Path(racine).resolve()
        chemins, _ = ix.fichiers(racine)
        par = {}
        for p in chemins:
            par.setdefault(p.parent.relative_to(base).as_posix(), []).append(p)
        s = config["vignette"].casefold()
        for dos in st.get("sans_vignette", [])[:60]:
            diag_absents.append({"dossier": dos, "fichiers":
                                 [p.name for p in sorted(par.get(dos, []))][:10]})
        for dos in st.get("vignettes_multiples", [])[:60]:
            diag_multiples.append({"dossier": dos, "fichiers": [
                p.name for p in sorted(par.get(dos, []))
                if p.stem.casefold().endswith(s)][:10]})
    exemples = [{"nom": x["nom"], "vignette": x["vignette"],
                 "images": len(x["fichiers"])} for x in d["items"][:18]]
    return {"config": config, "assets": len(d["items"]), "images": st["images"],
            "sans_vignette": len(st.get("sans_vignette", [])),
            "multiples": len(st.get("vignettes_multiples", [])),
            "diag_absents": diag_absents, "diag_multiples": diag_multiples,
            "exemples": exemples, "erreurs": st.get("erreurs", [])[:10],
            "creable": bool(d["items"]) and not st.get("vignettes_multiples")}


def reglage_config(reglage):
    if (reglage or {}).get("mode") == "image":
        return {"mode": "image"}
    return {"mode": "dossier", "vignette": (reglage or {}).get("vignette", "")}


# ---------------------------------------------------------------------------
#  Installation
# ---------------------------------------------------------------------------
def installer(tache, racine, r, dans_racine=False, etiquette=""):
    """Une banque : le systeme dans `racine`/serveur. `dans_racine` = cette
    banque est un sous-dossier d une racine a onglets : pas de lanceur, pas
    de moteur ni de raccourci a elle (ceux de la racine servent), et les
    etapes portent son nom."""
    racine = os.path.abspath(racine)
    t0 = time.time()

    def etape(libelle, total=0):
        tache.etape_suivante(etiquette + libelle, total)

    etape("Contrôles")
    if not os.path.isdir(racine):
        raise ValueError("Dossier introuvable : %s" % racine)
    if os.path.exists(os.path.join(racine, "serveur")):
        raise ValueError("Ce dossier contient déjà un dossier serveur : aucun "
                         "fichier ne sera remplacé. Utilisez « Mettre à jour ».")
    if not C.ecriture_possible(racine):
        raise ValueError("Impossible d'écrire dans ce dossier.")
    controle = verifier(racine, r)
    if not controle["creable"]:
        raise ValueError("Plusieurs miniatures correspondent dans un même "
                         "dossier : précisez le suffixe." if controle["multiples"]
                         else "Aucune image ne correspond : rien à créer.")
    config = controle["config"]
    tache.ligne("%d fiche(s) à créer, %d image(s)" % (controle["assets"],
                                                      controle["images"]))

    etape("Empreinte des images (avant)")
    # Ce que l installation ajoute a la racine, et seulement cela.
    ajoutes = ["serveur"]
    if not dans_racine:
        ajoutes += [C.NOM_LANCEUR, C.NOM_LANCEUR + ".avant-installation",
                    os.path.splitext(C.NOM_LANCEUR)[0] + ".exe"]
    avant = C.empreinte(racine, exclure=ajoutes, annule=tache.annulee,
                        progres=lambda n: tache.progres(n))
    tache.ligne("%d entrées relevées" % len(avant))
    tache.verifier()

    etape("Copie du système de bibliothèque")
    provisoire = os.path.join(racine, ".preparation-" + uuid.uuid4().hex[:8])
    os.makedirs(provisoire)
    try:
        for f in MODELE:
            shutil.copy2(C.modele_images(f), os.path.join(provisoire, f))
        C.ecrire_json(os.path.join(provisoire, "_configuration.json"), config, 2)
        C.ecrire_texte(os.path.join(provisoire, "_marques.json"), "{}")
        tache.ligne("_serveur.py, _scan.py, NAVIGATEUR.html, biblio.bat, "
                    "_configuration.json")

        # L index et les vignettes, par le _scan.py qu on vient de deposer.
        etape("Index et vignettes", controle["assets"])
        ix = charger_indexeur(os.path.join(provisoire, "_scan.py"))
        fini = {"ok": False, "erreur": None, "donnees": None}

        def travail():
            try:
                fini["donnees"] = ix.enregistrer(racine, config, provisoire)
            except Exception as e:
                fini["erreur"] = e
            fini["ok"] = True
        threading.Thread(target=travail, daemon=True).start()
        vign = os.path.join(provisoire, "_vignettes")
        while not fini["ok"]:
            time.sleep(0.4)
            try:
                n = sum(1 for x in os.listdir(vign) if x.endswith(".jpg"))
            except OSError:
                n = 0
            tache.progres(n, controle["assets"])
        if fini["erreur"]:
            raise fini["erreur"]
        donnees = fini["donnees"]
        if not donnees["items"]:
            raise ValueError("Les images ont changé pendant la préparation.")
        tache.progres(len(donnees["items"]), len(donnees["items"]))
        n_vign = len([x for x in os.listdir(vign) if x.endswith(".jpg")]) \
            if os.path.isdir(vign) else 0
        tache.ligne("%d fiches, %d vignettes" % (len(donnees["items"]), n_vign),
                    "ok")
        if not n_vign:
            tache.ligne("Pillow absent : les vignettes seront les images "
                        "entières (plus lent à l'affichage).", "alerte")

        if r.get("moteur", True) and not dans_racine:
            etape("Moteur Python embarqué")
            n = C.poser_moteur(os.path.join(provisoire, "_python"),
                               lambda f, t: tache.progres(f, t))
            tache.ligne("Moteur Python : %d fichiers" % n if n else
                        "Moteur Python indisponible : le Python installé "
                        "sera utilisé.", "info" if n else "alerte")
        tache.verifier()
        if os.path.exists(os.path.join(racine, "serveur")):
            raise ValueError("Un dossier serveur est apparu pendant la "
                             "préparation : installation annulée.")
        os.rename(provisoire, os.path.join(racine, "serveur"))
    finally:
        if os.path.isdir(provisoire):
            shutil.rmtree(provisoire, ignore_errors=True)
    if not dans_racine:
        lanceur = os.path.join(racine, C.NOM_LANCEUR)
        C.sauvegarder(lanceur, "installation")
        C.poser_lanceur(racine, C.NOM_LANCEUR,
                        C.modele_images("LANCER-LA-BIBLIOTHEQUE.bat"))
        C.noter_recent(racine, "images", os.path.basename(racine))
    le_maj.marquer_installe("banque", racine)

    etape("Empreinte des images (après)")
    apres = C.empreinte(racine, exclure=ajoutes)
    preuve = C.comparer(avant, apres)
    preuve["projet"] = os.path.basename(racine)
    tache.ligne("%d entrées, %s" % (preuve["entrees"], "identiques"
                                    if preuve["identiques"] else "DIFFERENCES"),
                "ok" if preuve["identiques"] else "erreur")

    raccourci = None
    if r.get("raccourci") and not dans_racine:
        etape("Raccourci sur le Bureau")
        try:
            icone = os.path.join(racine, "serveur", "_python", "python.exe")
            raccourci = C.raccourci_bureau(racine, os.path.basename(racine),
                                           icone if os.path.isfile(icone) else None)
            tache.ligne("Raccourci : %s" % raccourci, "ok")
        except Exception as e:
            tache.ligne("Raccourci non créé : %s" % e, "alerte")
    tache.terminer_etapes()
    return {"genre": "images", "racine": racine, "titre": os.path.basename(racine),
            "nom": os.path.basename(racine), "dans_racine": dans_racine,
            "fiches": len(donnees["items"]), "vignettes": n_vign,
            "mode": config["mode"], "vignette": config.get("vignette"),
            "preuve": [preuve], "raccourci": raccourci,
            "sans_vignette": len(donnees["stats"].get("sans_vignette", [])),
            "moteur": os.path.isfile(os.path.join(racine, "serveur", "_python",
                                                  "python.exe")),
            "duree": round(time.time() - t0)}


# ---------------------------------------------------------------------------
#  Installation d une racine a onglets
# ---------------------------------------------------------------------------
RACINE_SERVEUR = ("_serveur.py", "NAVIGATEUR.html", "biblio-generale.bat",
                  "LISEZ-MOI.txt")
RACINE_PREPARATEUR = ("_preparateur.py", "PREPARER.html", "preparer.bat",
                      "LISEZ-MOI.txt")


def _exe(nom_bat):
    return os.path.splitext(nom_bat)[0] + ".exe"


def poser_systeme_racine(provisoire, avec_moteur=False, progres=None):
    """Le programme d une racine a onglets dans un dossier provisoire :
    l accueil a onglets, le preparateur, et les modeles que celui-ci copie
    dans chaque nouvelle banque."""
    os.makedirs(provisoire, exist_ok=True)
    for f in RACINE_SERVEUR:
        shutil.copy2(C.modele_racine("serveur/" + f), os.path.join(provisoire, f))
    prep = os.path.join(provisoire, "preparateur")
    os.makedirs(prep, exist_ok=True)
    for f in RACINE_PREPARATEUR:
        shutil.copy2(C.modele_racine("serveur/preparateur/" + f),
                     os.path.join(prep, f))
    modeles = os.path.join(prep, "modeles")
    os.makedirs(modeles, exist_ok=True)
    for f in MODELE:
        shutil.copy2(C.modele_images(f), os.path.join(modeles, f))
    shutil.copy2(C.maj_py(), os.path.join(provisoire, "_maj.py"))
    return C.poser_moteur(os.path.join(provisoire, "_python"), progres) \
        if avec_moteur else 0


def reporter_marques(ancien, racine, tache=None):
    """Favoris et pastilles de l ancienne banque unique, reportes dans la
    banque ou chaque image se trouve maintenant. Au pire ils restent dans la
    sauvegarde : rien n est perdu."""
    marques = C.lire_json(os.path.join(ancien, "_marques.json"), {}) or {}
    marques = {k: v for k, v in marques.items()
               if isinstance(v, dict) and (v.get("fav") or v.get("coul"))}
    if not marques:
        return 0
    donnees = C.lire_json(os.path.join(ancien, "_donnees.json"), {}) or {}
    vignette_de = {x.get("id"): x.get("vignette")
                   for x in (donnees.get("items") or []) if isinstance(x, dict)}
    par_banque = {}
    for ident, valeur in marques.items():
        chemin = vignette_de.get(ident) or ""
        if "/" not in chemin:
            continue                       # image a la racine : plus de banque
        banque, reste = chemin.split("/", 1)
        par_banque.setdefault(banque, {})[reste] = valeur
    total = 0
    for banque, par_chemin in par_banque.items():
        serv = os.path.join(racine, banque, "serveur")
        d = C.lire_json(os.path.join(serv, "_donnees.json"), None)
        if not d:
            continue
        nouvelles = C.lire_json(os.path.join(serv, "_marques.json"), {}) or {}
        n = 0
        for x in d.get("items") or []:
            v = par_chemin.get(x.get("vignette"))
            if v and x.get("id"):
                nouvelles[x["id"]] = {
                    "fav": bool(v.get("fav")),
                    "coul": max(0, min(5, int(v.get("coul", 0)))),
                    "t": int(v.get("t", time.time() * 1000))}
                n += 1
        if n:
            C.ecrire_json(os.path.join(serv, "_marques.json"), nouvelles)
            total += n
    if tache:
        if total:
            tache.ligne("%d favori(s) / pastille(s) reportés dans les nouvelles "
                        "banques." % total, "ok")
        else:
            tache.ligne("%d favori(s) / pastille(s) n'ont pas pu être reportés : "
                        "ils restent dans la sauvegarde." % len(marques), "alerte")
    return total


def installer_racine(tache, racine, r):
    """Le dossier choisi devient une bibliotheque generale a onglets, et
    chaque sous-dossier coche une banque. Les images ne sont ni deplacees ni
    renommees : tout ce qui est ecrit va dans des dossiers serveur/."""
    racine = os.path.abspath(racine)
    t0 = time.time()
    tache.etape_suivante("Contrôles")
    if not os.path.isdir(racine):
        raise ValueError("Dossier introuvable : %s" % racine)
    if not C.ecriture_possible(racine):
        raise ValueError("Impossible d'écrire dans ce dossier.")
    det = C.detecter(racine)
    if det and det["genre"] == "films":
        raise ValueError("Ce dossier est une bibliothèque de films.")
    if det and det["genre"] == "racine":
        raise ValueError("Ce dossier est déjà une bibliothèque à onglets : aucun "
                         "fichier ne sera remplacé. Utilisez « Mettre à jour », ou "
                         "« Préparer une bibliothèque » pour ajouter une banque.")
    a_convertir = bool(det and det["genre"] == "images")
    choisies = []
    for l in (r.get("lignes") or []):
        nom = l.get("nom")
        if not l.get("coche") or not nom:
            continue
        p = os.path.join(racine, nom)
        if os.path.basename(nom) != nom or not os.path.isdir(p):
            raise ValueError("Sous-dossier introuvable : %s" % nom)
        if os.path.exists(os.path.join(p, "serveur")):
            tache.ligne("« %s » a déjà un serveur : laissée telle quelle." % nom,
                        "alerte")
            continue
        choisies.append({"nom": nom, "chemin": p, "mode": l.get("mode") or "dossier",
                         "vignette": l.get("vignette") or ""})
    deja = [b["nom"] for b in C.banques_de(racine)]
    tache.ligne("%d banque(s) à préparer%s" % (
        len(choisies), (", %d déjà en place" % len(deja)) if deja else ""))
    if a_convertir:
        tache.ligne("Ce dossier est déjà une banque unique : son serveur sera mis "
                    "de côté dans serveur\\sauvegardes. Aucune image n'est touchée.",
                    "alerte")
    marque = uuid.uuid4().hex[:8]
    provisoire = os.path.join(racine, ".preparation-" + marque)
    ecarte = os.path.join(racine, ".ancienne-banque-" + marque)

    tache.etape_suivante("Empreinte du dossier (avant)")
    # Ce que l installation ajoute a la racine. Les banques preparees ont leur
    # propre empreinte, prise par leur installation : on ne les compte pas deux fois.
    ajoutes = ["serveur", C.LANCEUR_GENERAL, C.LANCEUR_PREPARER,
               _exe(C.LANCEUR_GENERAL), _exe(C.LANCEUR_PREPARER),
               C.NOM_LANCEUR, _exe(C.NOM_LANCEUR),
               os.path.basename(provisoire), os.path.basename(ecarte)]
    ajoutes += [b["nom"] for b in choisies]
    avant = C.empreinte(racine, exclure=ajoutes, annule=tache.annulee,
                        progres=lambda n: tache.progres(n))
    tache.ligne("%d entrées relevées (hors banques)" % len(avant))
    tache.verifier()

    faits, echecs, preuve = [], [], []
    for i, b in enumerate(choisies):
        tache.verifier()
        try:
            res = installer(tache, b["chemin"],
                            {"mode": b["mode"], "vignette": b["vignette"],
                             "moteur": False, "raccourci": False},
                            dans_racine=True,
                            etiquette="Banque « %s » (%d/%d) — " % (
                                b["nom"], i + 1, len(choisies)))
            faits.append(res)
            preuve += res.get("preuve") or []
            tache.ligne("« %s » : %d fiches, %d vignettes." % (
                b["nom"], res["fiches"], res["vignettes"]), "ok")
        except C.Annulation:
            raise
        except Exception as e:
            echecs.append({"nom": b["nom"], "erreur": str(e)})
            tache.ligne("« %s » : %s" % (b["nom"], e), "erreur")

    sauvegarde, reportees, mis_de_cote = None, 0, None
    tache.etape_suivante("Programme de la bibliothèque générale")
    try:
        n = poser_systeme_racine(provisoire, bool(r.get("moteur", True)),
                                 lambda f, t: tache.progres(f, t))
        tache.ligne("Accueil à onglets, préparateur et modèles copiés", "ok")
        if n:
            tache.ligne("Moteur Python : %d fichiers" % n)
        elif r.get("moteur", True):
            tache.ligne("Moteur Python indisponible : le Python installé sera "
                        "utilisé.", "alerte")
        tache.verifier()

        tache.etape_suivante("Mise en place")
        serveur = os.path.join(racine, "serveur")
        if os.path.exists(serveur):
            if not a_convertir:
                raise ValueError("Un dossier serveur est apparu pendant la "
                                 "préparation : installation annulée.")
            os.rename(serveur, ecarte)
            mis_de_cote = ecarte
        try:
            os.rename(provisoire, serveur)
        except OSError as e:
            if mis_de_cote:
                os.rename(mis_de_cote, serveur)      # remis exactement comme avant
            raise ValueError("Mise en place impossible (%s). Rien n'a changé." % e)
        tache.ligne("serveur\\ : accueil à onglets et préparateur en place", "ok")
    finally:
        if os.path.isdir(provisoire):
            shutil.rmtree(provisoire, ignore_errors=True)

    tache.etape_suivante("Lanceurs")
    C.poser_lanceur(racine, C.LANCEUR_GENERAL,
                    C.modele_racine("Bibliotheque generale.bat"))
    C.poser_lanceur(racine, C.LANCEUR_PREPARER,
                    C.modele_racine("Preparer une bibliotheque.bat"))
    tache.ligne("« %s » et « %s »" % (_exe(C.LANCEUR_GENERAL),
                                      _exe(C.LANCEUR_PREPARER)), "ok")

    if mis_de_cote:
        tache.etape_suivante("Ancienne banque mise de côté")
        cible = os.path.join(racine, "serveur", "sauvegardes",
                             "ancienne-banque-" + time.strftime("%Y%m%d-%H%M"))
        os.makedirs(os.path.dirname(cible), exist_ok=True)
        try:
            os.rename(mis_de_cote, cible)            # meme volume : instantane
            sauvegarde = cible
        except OSError:
            sauvegarde = mis_de_cote                 # laissee a la racine
        for nom in (C.NOM_LANCEUR, _exe(C.NOM_LANCEUR)):
            src = os.path.join(racine, nom)
            if os.path.isfile(src):
                try:
                    C.cacher(src, False)
                    os.replace(src, os.path.join(sauvegarde, nom))
                except OSError:
                    pass
        tache.ligne("Ancien serveur et son lanceur : %s (à supprimer quand tout "
                    "va bien)" % os.path.relpath(sauvegarde, racine), "ok")
        reportees = reporter_marques(sauvegarde, racine, tache)

    le_maj.marquer_installe("racine", racine)
    C.noter_recent(racine, "racine", os.path.basename(racine))

    tache.etape_suivante("Empreinte du dossier (après)")
    apres = C.empreinte(racine, exclure=ajoutes)
    p = C.comparer(avant, apres)
    p["projet"] = os.path.basename(racine)
    preuve.insert(0, p)
    tache.ligne("%d entrées, %s" % (p["entrees"], "identiques" if p["identiques"]
                                    else "DIFFERENCES"),
                "ok" if p["identiques"] else "erreur")

    raccourci = None
    if r.get("raccourci"):
        tache.etape_suivante("Raccourci sur le Bureau")
        try:
            raccourci = C.raccourci_bureau(racine, os.path.basename(racine))
            tache.ligne("Raccourci : %s" % raccourci, "ok")
        except Exception as e:
            tache.ligne("Raccourci non créé : %s" % e, "alerte")
    tache.terminer_etapes()
    return {"genre": "racine", "racine": racine, "titre": os.path.basename(racine),
            "banques": [{"nom": f["nom"], "fiches": f["fiches"],
                         "vignettes": f["vignettes"], "mode": f["mode"],
                         "sans_vignette": f["sans_vignette"]} for f in faits],
            "deja": deja, "echecs": echecs,
            "fiches": sum(f["fiches"] for f in faits),
            "preuve": preuve, "raccourci": raccourci,
            "sauvegarde": sauvegarde, "marques_reportees": reportees,
            "moteur": os.path.isfile(os.path.join(racine, "serveur", "_python",
                                                  "python.exe")),
            "duree": round(time.time() - t0)}


# ---------------------------------------------------------------------------
#  Mise a jour
# ---------------------------------------------------------------------------
def etat_mise_a_jour(racine):
    """Ce que la mise a jour ferait, sans rien faire. Meme moteur que le
    bouton « Mettre a jour » des bibliotheques (le_maj, modeles/commun/_maj.py) :
    une racine a onglets est examinee avec toutes ses banques."""
    d = C.detecter(racine)
    if not d or d["genre"] not in ("images", "racine"):
        raise ValueError("Ce dossier n'est pas une bibliothèque d'images.")
    return le_maj.etat(racine)


def mettre_a_jour(tache, racine, options):
    """Remplace le code du systeme ; favoris, pastilles, configuration, index
    et vignettes restent tels quels. Un fichier modifie a la main n est jamais
    remplace sans le demander, et une sauvegarde precede chaque remplacement."""
    return le_maj.appliquer(tache, racine, options)

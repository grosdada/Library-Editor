# -*- coding: utf-8 -*-
"""Mettre une bibliotheque en ligne — module a part.

Il ne touche a rien de ce qui existe : il LIT la bibliotheque et ecrit tout
dans un seul dossier neuf, _enligne/ (serveur/_enligne/ pour les images,
parce que le scan des images ne saute que « serveur »). Il y fabrique :

    _enligne/
      proxys/     les proxys des films (720p, une image-cle toutes les 15),
                  gardes pour ne jamais les refaire
      paquet/     ce qu on envoie : 1-site.zip, 2-medias-01.zip…,
                  _deballer.php, LISEZ-MOI.txt, GUIDE.html
      _etat.json  les proxys deja faits
      _paquet.json ce qui est deja parti, pour n envoyer ensuite que les
                  changements

Aucun mot de passe : l envoi se fait dans hPanel ou dans FileZilla, par la
personne elle-meme. On ne lui demande rien, on ne recoit rien.
"""
import concurrent.futures as cf
import html
import json
import os
import secrets
import shutil
import subprocess
import threading
import time
import zipfile

import le_commun as C

TAILLE_ZIP = 450 * 1024 * 1024     # sous les plafonds d envoi du navigateur
DEFLATE = (".json", ".html", ".php", ".js", ".css", ".txt", ".htaccess")

# La recette de publier.py, mesuree sur les rushes de David le 11/09 :
# -g 15 pour que le deplacement dans la timeline ne saccade pas,
# +faststart pour que la lecture commence sans tout telecharger.
VIDEO = ["-map", "0:v:0", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
         "-vf", "scale=-2:720:flags=lanczos", "-g", "15", "-keyint_min", "15",
         "-sc_threshold", "0", "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
VIDEO_SON = ["-map", "0:a:0?", "-c:a", "aac", "-b:a", "128k", "-ac", "2"]
AUDIO = ["-vn", "-map", "0:a:0", "-c:a", "aac", "-b:a", "192k",
         "-movflags", "+faststart"]


def dossier_enligne(racine, genre):
    if genre == "images":
        return os.path.join(racine, "serveur", "_enligne")
    return os.path.join(racine, "_enligne")


# ---------------------------------------------------------------------------
#  Etat : ce qui existe deja
# ---------------------------------------------------------------------------
def etat(racine):
    racine = os.path.abspath(racine)
    d = C.detecter(racine)
    if not d:
        raise ValueError("Ce dossier n'est pas une bibliothèque installée.")
    genre = d["genre"]
    if genre == "racine":
        # Une racine a onglets n est pas mise en ligne telle quelle : chacune
        # de ses banques est un site a elle seule. On rend la liste, la page
        # redemande l etat pour celle que David choisit.
        banques = []
        for b in d.get("banques") or []:
            chemin = os.path.join(racine, b["nom"])
            donnees = C.lire_json(os.path.join(chemin, "serveur", "_donnees.json"),
                                  {}) or {}
            banques.append({"nom": b["nom"], "chemin": chemin,
                            "fiches": len(donnees.get("items") or []),
                            "compatible": b.get("compatible")})
        return {"racine": racine, "genre": "racine", "titre": d.get("titre"),
                "banques": banques}
    base = dossier_enligne(racine, genre)
    paquet = C.lire_json(os.path.join(base, "_paquet.json"), {}) or {}
    out = {"racine": racine, "genre": genre, "titre": d.get("titre"),
           "dossier": base, "paquet_precedent": {
               "date": paquet.get("date"), "fichiers": len(paquet.get("fichiers", {})),
               "site": paquet.get("site", "")},
           "ffmpeg": bool(shutil.which("ffmpeg")),
           "ffprobe": bool(shutil.which("ffprobe"))}
    if genre == "films":
        import le_films
        mod = le_films.charger_serveur(racine)
        projets = []
        for p in mod.projets_disque() + mod.biblis_disque():
            cat = mod.lire_catalogue(p)
            films = [f for f in cat.get("films", []) if not f.get("absent")]
            if not mod.catalogue_existe(p):
                continue
            projets.append({"nom": p, "fiches": len(films),
                            "secondes": round(sum(f.get("s") or 0 for f in films)),
                            "octets": sum(f.get("octets") or 0 for f in films)})
        faits = C.lire_json(os.path.join(base, "_etat.json"), {}) or {}
        out["projets"] = projets
        out["proxys_faits"] = len(faits)
        secondes = sum(p["secondes"] for p in projets)
        # ~0,4 Mo par seconde de proxy 720p, mesure a la louche sur la recette.
        out["estimation"] = C.taille_humaine(secondes * 0.4 * 1024 * 1024)
    else:
        donnees = C.lire_json(os.path.join(racine, "serveur", "_donnees.json"), {}) or {}
        items = donnees.get("items") or []
        fichiers = {f for x in items for f in x.get("fichiers", [])}
        octets = 0
        for f in fichiers:
            try:
                octets += os.path.getsize(os.path.join(racine, f))
            except OSError:
                pass
        out["fiches"] = len(items)
        out["images"] = len(fichiers)
        out["estimation"] = C.taille_humaine(octets)
    return out


# ---------------------------------------------------------------------------
#  Proxys des films
# ---------------------------------------------------------------------------
def duree(fichier):
    fp = shutil.which("ffprobe")
    if not fp:
        return None
    try:
        r = subprocess.run([fp, "-v", "error", "-show_entries", "format=duration",
                            "-of", "default=nw=1:nk=1", fichier],
                           capture_output=True, text=True, timeout=60,
                           creationflags=C.SANS_CONSOLE)
        return float(r.stdout.strip())
    except Exception:
        return None


def fabriquer_proxy(source, cible, son_seul):
    """Un proxy ; on ne le garde que s il dure comme l original (un proxy plus
    court decalerait tout le montage, et ca ne se verrait qu a la lecture)."""
    os.makedirs(os.path.dirname(cible), exist_ok=True)
    base, ext = os.path.splitext(cible)
    tmp = base + ".part" + ext      # ffmpeg devine le conteneur par l extension
    cmd = [shutil.which("ffmpeg"), "-nostdin", "-y", "-v", "error", "-i", source]
    cmd += AUDIO if son_seul else (VIDEO + VIDEO_SON)
    cmd += [tmp]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800,
                           creationflags=C.SANS_CONSOLE)
    except subprocess.TimeoutExpired:
        return False, "trop long (30 mn)"
    if r.returncode != 0 or not os.path.isfile(tmp):
        return False, (r.stderr or "").strip()[:160] or "ffmpeg a échoué"
    d1, d2 = duree(source), duree(tmp)
    if d1 and d2 and abs(d1 - d2) > 0.15:
        os.remove(tmp)
        return False, "durée %.3f au lieu de %.3f" % (d2, d1)
    os.replace(tmp, cible)
    return True, "%.1f Mo" % (os.path.getsize(cible) / 1e6)


def rel_proxy(f):
    return os.path.splitext(f["rel"])[0] + (".m4a" if f.get("son_seul") else ".mp4")


def proxys(tache, racine, mod, base):
    """Fabrique ce qui manque, a plusieurs a la fois. Reprenable."""
    etat_f = os.path.join(base, "_etat.json")
    faits = C.lire_json(etat_f, {}) or {}
    a_faire, prets = [], {}
    projets = [p for p in mod.projets_disque() + mod.biblis_disque()
               if mod.catalogue_existe(p)]
    for p in projets:
        for f in mod.lire_catalogue(p).get("films", []):
            if f.get("absent"):
                continue
            src = mod.sur(p, f["rel"])
            dst = os.path.join(base, "proxys", p, rel_proxy(f).replace("/", os.sep))
            deja = faits.get(p + "|" + f["id"])
            if os.path.isfile(dst) and deja and deja.get("octets") == f.get("octets"):
                prets[(p, f["id"])] = dst
            elif src and os.path.isfile(src):
                a_faire.append((p, f, src, dst))
            else:
                tache.ligne("Introuvable : %s/%s" % (p, f["rel"]), "alerte")
    tache.etape_suivante("Proxys : %d à faire, %d déjà faits"
                         % (len(a_faire), len(prets)), len(a_faire))
    if a_faire and not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg est introuvable : les proxys ne peuvent pas "
                           "être fabriqués. Installez ffmpeg puis recommencez.")
    verrou = threading.Lock()
    compte = {"n": 0, "echecs": 0}

    def un(t):
        p, f, src, dst = t
        if tache.annulee():
            return
        ok, msg = fabriquer_proxy(src, dst, f.get("son_seul"))
        with verrou:
            compte["n"] += 1
            tache.progres(compte["n"])
            if ok:
                faits[p + "|" + f["id"]] = {"octets": f.get("octets"),
                                           "proxy": rel_proxy(f),
                                           "fait": time.strftime("%Y-%m-%d %H:%M")}
                prets[(p, f["id"])] = dst
                if compte["n"] % 5 == 0 or f.get("son_seul"):
                    tache.ligne("%s : %s" % (f["nom"][:60], msg))
                if compte["n"] % 10 == 0:
                    C.ecrire_json(etat_f, faits)
            else:
                compte["echecs"] += 1
                tache.ligne("ÉCHEC %s : %s" % (f["nom"][:60], msg), "erreur")

    n = max(1, min(4, (os.cpu_count() or 2) // 2))
    if a_faire:
        tache.ligne("%d encodages à la fois" % n)
        with cf.ThreadPoolExecutor(max_workers=n) as pool:
            list(pool.map(un, a_faire))
    C.ecrire_json(etat_f, faits)
    tache.verifier()
    return projets, prets, compte["echecs"]


# ---------------------------------------------------------------------------
#  Contenu du site : (fichier local, chemin dans le site)
# ---------------------------------------------------------------------------
def site_films(tache, racine, base, mod, projets, prets):
    tache.etape_suivante("Catalogues et vignettes")
    genere = os.path.join(base, "genere")
    if os.path.isdir(genere):
        shutil.rmtree(genere)
    os.makedirs(genere)
    entrees = []
    publies, biblis = [], set(mod.biblis_disque())
    for p in projets:
        cat = mod.lire_catalogue(p)
        enligne = []
        for f in cat.get("films", []):
            dst = prets.get((p, f.get("id")))
            if f.get("absent") or not dst:
                continue
            fiche = dict(f)
            fiche["proxy"] = rel_proxy(f)
            fiche["poctets"] = os.path.getsize(dst)
            enligne.append(fiche)
            entrees.append((dst, "_media/%s/%s" % (p, fiche["proxy"]), "media"))
            poster = mod.poster_de(p, f)
            if os.path.isfile(poster):
                entrees.append((poster, "_posters/%s/%s.jpg" % (p, f["id"]), "site"))
        if not enligne:
            tache.ligne("%s : aucun proxy, pas mis en ligne" % p, "alerte")
            continue
        # Memes fiches, memes identifiants, plus « proxy ». Aucun chemin
        # absolu ne part en ligne.
        c = os.path.join(genere, "_data", p, "catalogue.json")
        C.ecrire_json(c, {"maj": cat.get("maj"), "racine": p, "films": enligne,
                          "dossiers": sorted({x.get("dossier", "") for x in enligne
                                              if x.get("dossier")})})
        entrees.append((c, "_data/%s/catalogue.json" % p, "site"))
        publies.append(p)
        tache.ligne("%s : %d fiches en ligne" % (p, len(enligne)), "ok")
    if not publies:
        raise RuntimeError("Aucun projet n'a de proxy : rien à mettre en ligne.")
    pj = os.path.join(genere, "_data", "projets.json")
    C.ecrire_json(pj, {"projets": publies, "biblis": [p for p in publies if p in biblis],
                       "publie": time.strftime("%Y-%m-%d %H:%M")})
    entrees.append((pj, "_data/projets.json", "site"))
    app = os.path.join(racine, "_app")
    entrees.append((os.path.join(app, "app.html"), "app.html", "site"))
    for f in ("api.php", "config.php", ".htaccess"):
        entrees.append((C.modele_enligne("films", f), f, "site"))
    entrees.append((C.modele_enligne("films", "_data", ".htaccess"),
                    "_data/.htaccess", "site"))
    for dos, dest, exts in ((os.path.join(app, "_polices"), "_polices",
                             (".ttf", ".otf", ".ttc", ".woff", ".woff2")),
                            (os.path.join(app, "_presets"), "_data/_presets", (".json",))):
        if os.path.isdir(dos):
            for n in sorted(os.listdir(dos)):
                if n.lower().endswith(exts):
                    entrees.append((os.path.join(dos, n), dest + "/" + n, "site"))
    return entrees


ROUTES_IMAGES = ("'/fichier?p='", "'/vignette?id='", "'/scan'", "'/donnees'",
                 "'/marques'", "'/ouvrir'", "'/zip'")


def page_images(source, cible):
    """NAVIGATEUR.html avec des routes relatives : le site marche aussi bien
    a la racine d un sous-domaine que dans un sous-dossier. Chaque route doit
    etre trouvee, sinon on s arrete plutot que de publier une page cassee."""
    t = open(source, encoding="utf-8").read()
    for r in ROUTES_IMAGES:
        if r not in t:
            raise RuntimeError("NAVIGATEUR.html a changé : route %s introuvable." % r)
        t = t.replace(r, "'" + r[2:])
    C.ecrire_texte(cible, t)


def site_images(tache, racine, base):
    tache.etape_suivante("Index, vignettes et images")
    serv = os.path.join(racine, "serveur")
    donnees_f = os.path.join(serv, "_donnees.json")
    donnees = C.lire_json(donnees_f, None)
    if not donnees or not donnees.get("items"):
        raise RuntimeError("Index vide : ouvrez la bibliothèque une fois (elle "
                           "se met à jour au lancement), puis recommencez.")
    genere = os.path.join(base, "genere")
    if os.path.isdir(genere):
        shutil.rmtree(genere)
    os.makedirs(genere)
    entrees = []
    index = os.path.join(genere, "index.html")
    page_images(os.path.join(serv, "NAVIGATEUR.html"), index)
    entrees.append((index, "index.html", "site"))
    entrees.append((C.modele_enligne("images", "api.php"), "api.php", "site"))
    entrees.append((C.modele_enligne("images", ".htaccess"), ".htaccess", "site"))
    entrees.append((C.modele_enligne("images", "_data", ".htaccess"),
                    "_data/.htaccess", "site"))
    entrees.append((donnees_f, "_data/_donnees.json", "site"))
    marques = os.path.join(serv, "_marques.json")
    if os.path.isfile(marques):
        entrees.append((marques, "_data/_marques.depot.json", "site"))
    vues = set()
    for item in donnees["items"]:
        m = item.get("miniature")
        if m:
            v = os.path.join(serv, "_vignettes", m)
            if os.path.isfile(v):
                entrees.append((v, "_data/_vignettes/" + m, "site"))
        for f in item.get("fichiers", []):
            if f in vues:
                continue
            vues.add(f)
            src = os.path.join(racine, f.replace("/", os.sep))
            if os.path.isfile(src):
                entrees.append((src, "_data/fichiers/" + f, "media"))
            else:
                tache.ligne("Introuvable : %s" % f, "alerte")
    tache.ligne("%d fiches, %d images" % (len(donnees["items"]), len(vues)), "ok")
    return entrees


# ---------------------------------------------------------------------------
#  Le paquet
# ---------------------------------------------------------------------------
def signature(chemin):
    st = os.stat(chemin)
    return [st.st_size, int(st.st_mtime)]


def emballer(tache, base, entrees, seulement_changes, site):
    """Les .zip : le site d abord (petit), puis les medias en tranches de
    450 Mo. En mode « changements », seuls les medias nouveaux ou modifies
    repartent ; le site (index, pages, vignettes) repart toujours."""
    paquet = os.path.join(base, "paquet")
    if os.path.isdir(paquet):
        try:
            shutil.rmtree(paquet)
        except OSError as e:
            raise RuntimeError("Le paquet précédent est ouvert dans un autre "
                               "programme (FileZilla, 7-Zip, un apercu ?) : "
                               "fermez-le, puis recommencez. (%s)" % e)
    os.makedirs(paquet)
    ancien = C.lire_json(os.path.join(base, "_paquet.json"), {}) or {}
    deja = ancien.get("fichiers", {}) if seulement_changes else {}
    site_e = [e for e in entrees if e[2] == "site"]
    medias = [e for e in entrees if e[2] == "media"
              and deja.get(e[1]) != signature(e[0])]
    sautes = sum(1 for e in entrees if e[2] == "media") - len(medias)
    total = sum(os.path.getsize(e[0]) for e in site_e + medias)
    tache.etape_suivante("Emballage : %d fichiers, %s" % (
        len(site_e) + len(medias), C.taille_humaine(total)), total)
    if sautes:
        tache.ligne("%d médias déjà envoyés la dernière fois : ils ne repartent pas"
                    % sautes)
    lots = [("1-site", site_e)]
    lot, poids, k = [], 0, 1
    for e in medias:
        t = os.path.getsize(e[0])
        if lot and poids + t > TAILLE_ZIP:
            lots.append(("%d-medias-%02d" % (k + 1, k), lot))
            lot, poids, k = [], 0, k + 1
        lot.append(e)
        poids += t
    if lot:
        lots.append(("%d-medias-%02d" % (k + 1, k), lot))
    fait = 0
    zips = []
    for nom, contenu in lots:
        chemin = os.path.join(paquet, nom + ".zip")
        with zipfile.ZipFile(chemin, "w", allowZip64=True) as z:
            for src, dest, _ in contenu:
                tache.verifier()
                mode = (zipfile.ZIP_DEFLATED if dest.lower().endswith(DEFLATE)
                        else zipfile.ZIP_STORED)
                z.write(src, dest, compress_type=mode)
                fait += os.path.getsize(src)
                tache.progres(fait)
        zips.append({"nom": nom + ".zip", "octets": os.path.getsize(chemin),
                     "fichiers": len(contenu)})
        tache.ligne("%s.zip : %d fichiers, %s" % (nom, len(contenu),
                    C.taille_humaine(os.path.getsize(chemin))), "ok")
    cle = secrets.token_hex(12)
    t = open(C.modele_enligne("_deballer.php"), encoding="utf-8").read()
    if "%%CLE%%" not in t:
        raise RuntimeError("_deballer.php : emplacement de la clé introuvable.")
    C.ecrire_texte(os.path.join(paquet, "_deballer.php"), t.replace("%%CLE%%", cle))
    # Ce qui est parti, pour la fois suivante. On le note des maintenant :
    # si l envoi echoue, relancer « tout » reste possible.
    nouveau = dict(deja) if seulement_changes else {}
    for e in site_e + medias:
        nouveau[e[1]] = signature(e[0])
    C.ecrire_json(os.path.join(base, "_paquet.json"), {
        "date": time.strftime("%Y-%m-%d %H:%M"), "site": site,
        "fichiers": nouveau})
    return paquet, zips, cle


def preparer(tache, racine, options):
    racine = os.path.abspath(racine)
    t0 = time.time()
    d = C.detecter(racine)
    if not d:
        raise ValueError("Ce dossier n'est pas une bibliothèque installée.")
    genre = d["genre"]
    if genre == "racine":
        raise ValueError("Une bibliothèque à onglets se met en ligne banque par "
                         "banque : choisissez la banque à publier.")
    base = dossier_enligne(racine, genre)
    os.makedirs(base, exist_ok=True)
    site = (options.get("site") or "").strip().rstrip("/")
    if genre == "films":
        import le_films
        mod = le_films.charger_serveur(racine)
        projets, prets, echecs = proxys(tache, racine, mod, base)
        entrees = site_films(tache, racine, base, mod, projets, prets)
    else:
        entrees = site_images(tache, racine, base)
        echecs = 0
    paquet, zips, cle = emballer(tache, base, entrees,
                                 bool(options.get("seulement_changes")), site)
    total = sum(z["octets"] for z in zips)
    url_deballer = (site + "/_deballer.php?cle=" + cle) if site else \
        "https://<votre-site>/_deballer.php?cle=" + cle
    lisez_moi(paquet, genre, d.get("titre"), zips, url_deballer, site)
    C.ecrire_texte(os.path.join(paquet, "GUIDE.html"),
                   guide_page(genre, d.get("titre"), site, url_deballer,
                              C.taille_humaine(total)))
    tache.terminer_etapes()
    return {"genre": genre, "racine": racine, "paquet": paquet, "zips": zips,
            "total": C.taille_humaine(total), "cle": cle,
            "url_deballer": url_deballer, "site": site, "echecs": echecs,
            "duree": round(time.time() - t0)}


def lisez_moi(paquet, genre, titre, zips, url_deballer, site):
    lignes = [
        "PAQUET DE MISE EN LIGNE - %s" % titre,
        "Fabrique par Library Editor le %s." % time.strftime("%d/%m/%Y %H:%M"),
        "",
        "1. Envoyez TOUS les fichiers de ce dossier dans le dossier du site",
        "   (hPanel > Files > File Manager, ou FileZilla) :",
    ]
    lignes += ["     %s  (%s)" % (z["nom"], C.taille_humaine(z["octets"])) for z in zips]
    lignes += ["     _deballer.php", "",
               "2. Ouvrez cette adresse dans votre navigateur, puis cliquez sur Deballer :",
               "     " + url_deballer, "",
               "   Le script decompresse les .zip sur place, puis les efface avec lui.",
               "",
               "3. " + ("Protegez le dossier du site : hPanel > Advanced > Password "
                        "Protect Directories." if genre == "images" else
                        "Ouvrez le site : la premiere visite propose de creer le "
                        "compte administrateur."),
               "",
               "Le guide complet est dans GUIDE.html, a cote.",
               "Aucun mot de passe n est ecrit dans ce paquet."]
    C.ecrire_texte(os.path.join(paquet, "LISEZ-MOI.txt"), "\n".join(lignes) + "\n",
                   crlf=True)


# ---------------------------------------------------------------------------
#  Le guide pas a pas — une seule source pour l application et GUIDE.html
# ---------------------------------------------------------------------------
def etapes_guide(genre, site="", url_deballer="", taille=""):
    e = html.escape
    site_aff = e(site) if site else "https://images.votre-domaine.fr"
    films = genre == "films"
    etapes = [
        ("Avant de commencer",
         "<p>Il vous faut un <b>hébergement web Hostinger</b> (offre Premium ou "
         "Business : PHP y est inclus) et un domaine. Le paquet fera environ "
         "<b>%s</b> : vérifiez l'espace libre dans hPanel, <i>Websites → "
         "Dashboard</i>.</p><p>Library Editor ne demande, ne reçoit et ne garde "
         "<b>aucun mot de passe</b> : tout ce qui en réclame se fait dans hPanel "
         "ou FileZilla, par vous.</p>" % (e(taille) or "quelques Go")),
        ("Créer un sous-domaine",
         "<p>hPanel → <i>Domains → Subdomains</i> (Domaines → Sous-domaines). "
         "Tapez par exemple <code>%s</code>, puis <b>Create</b>.</p>"
         "<p>Hostinger crée le dossier du site, en général <code>public_html/%s</code>. "
         "Le cadenas HTTPS arrive tout seul, parfois après quelques minutes.</p>"
         "<p class=\"petit\">Un sous-domaine plutôt qu'un sous-dossier : %s</p>"
         % ("montage" if films else "images", "montage" if films else "images",
            "l'application de montage appelle <code>/api/…</code> depuis la racine "
            "du site, elle doit donc en occuper une." if films else
            "c'est plus simple à protéger, et la bibliothèque marche aussi dans un "
            "sous-dossier si vous préférez.")),
        ("Préparer le paquet",
         "<p>Cliquez sur <b>Préparer le paquet</b>. %s Tout est écrit dans "
         "<code>%s</code> : des fichiers <code>.zip</code>, <code>_deballer.php</code>, "
         "<code>LISEZ-MOI.txt</code> et ce guide.</p><p>La première fois, choisissez "
         "<i>Tout</i> ; ensuite, <i>Seulement ce qui a changé</i> évite de renvoyer "
         "des Go déjà en ligne.</p>"
         % ("Les vidéos sont d'abord converties en <b>proxys 720p</b> (la recette "
            "de <code>publier.py</code>) : c'est long la première fois, jamais "
            "refait ensuite. Les identifiants ne changent pas : un montage fait en "
            "ligne se rouvre à la maison sur les originaux." if films else
            "Les images partent telles quelles, avec leurs vignettes, favoris et "
            "pastilles.",
            "_enligne\\paquet" if films else "serveur\\_enligne\\paquet")),
        ("Envoyer les fichiers",
         "<p><b>A · Par hPanel</b> (jusqu'à 1 ou 2 Go) : <i>Files → File Manager</i> "
         "(Fichiers → Gestionnaire de fichiers), ouvrez le dossier du sous-domaine, "
         "bouton <b>Upload</b>, et choisissez <b>tous</b> les fichiers du dossier "
         "<code>paquet</code>.</p>"
         "<p><b>B · Par FileZilla</b> (gros volumes : il reprend après une coupure) : "
         "hPanel → <i>Files → FTP Accounts</i> (Comptes FTP), créez un compte "
         "limité au dossier du sous-domaine — <b>vous</b> choisissez son mot de passe "
         "dans hPanel. Dans FileZilla : Hôte, Nom d'utilisateur, Mot de passe, "
         "Port 21, <b>Connexion rapide</b>, puis glissez les fichiers du paquet à "
         "droite.</p>"),
        ("Déballer sur le serveur",
         "<p>Ouvrez cette adresse dans votre navigateur et cliquez sur "
         "<b>Déballer</b> :</p><p><code class=\"url\">%s</code></p><p>Le script "
         "décompresse les .zip sur place, par tranches, puis efface les .zip et "
         "s'efface lui-même. Une coupure ? Rechargez la page : il reprend.</p>"
         % e(url_deballer or "https://<votre-site>/_deballer.php?cle=…")),
        ("Protéger l'accès",
         ("<p>Ouvrez <code>%s</code> : la première visite propose de créer le "
          "<b>compte administrateur</b>. Vous tapez son mot de passe dans la page "
          "du site ; le serveur n'en garde qu'une empreinte (bcrypt).</p><p>Pour "
          "chaque collègue : panneau <b>Accounts</b> de l'application, un compte "
          "chacun — on retire un accès sans toucher aux autres.</p>" % site_aff)
         if films else
         ("<p>hPanel → <i>Advanced → Password Protect Directories</i> (Protection "
          "par mot de passe), choisissez le dossier du sous-domaine, puis un "
          "identifiant et un mot de passe à donner aux collègues. Tout le site est "
          "alors fermé, images et téléchargements compris.</p><p class=\"petit\">Si le "
          "menu a bougé, tapez « password » dans la recherche de hPanel.</p>")),
        ("Vérifier",
         "<p>Ouvrez <code>%s</code> depuis un autre ordinateur, ou votre téléphone "
         "en 4G.</p><ul>%s</ul>"
         % (site_aff,
            "<li>la grille des rushes s'affiche, avec les vignettes ;</li>"
            "<li>une vidéo se lit, et se déplace sans accroc dans la timeline ;</li>"
            "<li>une séquence s'enregistre, puis se rouvre.</li>" if films else
            "<li>la grille s'affiche, avec les vignettes ;</li>"
            "<li>une fiche s'ouvre, ses images défilent ;</li>"
            "<li>un favori posé en ligne tient après rechargement ;</li>"
            "<li>un téléchargement ZIP de deux fiches aboutit.</li>")),
        ("Mettre à jour plus tard",
         "<p>%s Puis <b>Préparer le paquet</b> avec <i>Seulement ce qui a "
         "changé</i>, envoyez, déballez. Les fichiers déjà en ligne et identiques "
         "sont sautés.</p>"
         % ("Scannez les nouveaux rushes dans la bibliothèque, sur l'ordinateur."
            if films else "Ajoutez les images sur l'ordinateur et ouvrez la "
            "bibliothèque une fois : elle se réindexe au lancement.")),
    ]
    return [{"titre": t, "html": h} for t, h in etapes]


def guide_page(genre, titre, site, url_deballer, taille):
    corps = "".join(
        '<section><h2><span>%d</span>%s</h2>%s</section>' % (i + 1, html.escape(x["titre"]),
                                                            x["html"])
        for i, x in enumerate(etapes_guide(genre, site, url_deballer, taille)))
    return ("""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Mise en ligne - %s</title><style>
:root{--fond:#f6f5f2;--papier:#fff;--encre:#1c1c1e;--doux:#62605b;--filet:#e4e1db;--accent:#a8671c}
@media (prefers-color-scheme:dark){:root{--fond:#111214;--papier:#18191c;--encre:#ecebe8;--doux:#9a9ca3;--filet:#2a2c30;--accent:#d6a45c}}
*{box-sizing:border-box}body{margin:0;background:var(--fond);color:var(--encre);font:16px/1.6 "Segoe UI",system-ui,sans-serif;padding:32px 16px}
main{max-width:760px;margin:0 auto}h1{font-size:28px;margin:0 0 4px}.sous{color:var(--doux);margin:0 0 28px}
section{background:var(--papier);border:1px solid var(--filet);border-radius:12px;padding:18px 22px;margin:0 0 14px}
h2{font-size:18px;margin:0 0 8px;display:flex;gap:10px;align-items:center}h2 span{width:26px;height:26px;border-radius:50%%;background:var(--accent);color:#fff;font-size:13px;display:grid;place-items:center;flex:none}
code{font-family:Consolas,monospace;font-size:.9em;background:color-mix(in srgb,var(--accent) 12%%,transparent);padding:.1em .35em;border-radius:4px;word-break:break-all}
.petit{font-size:14px;color:var(--doux)}p{margin:6px 0}</style></head><body><main>
<h1>Mettre « %s » en ligne</h1><p class="sous">Guide pas à pas pour Hostinger — fabriqué par Library Editor le %s.</p>
%s</main></body></html>""" % (html.escape(titre or ""), html.escape(titre or ""),
                              time.strftime("%d/%m/%Y"), corps))

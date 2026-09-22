#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bibliotheque video locale - Coulisses du Cosmos, par projet
Un seul fichier : scan, posters, serveur HTTP, API de rangement.

    python serveur.py                demarre le serveur (scanne si besoin)
    python serveur.py --scan         rescanne tous les projets
    python serveur.py --scan GARY-ALL   rescanne un seul projet
    python serveur.py --posters      fabrique les posters manquants et sort
    python serveur.py --budget 120   limite de temps pour --posters (secondes)

Aucune dependance : uniquement la bibliotheque standard de Python 3.8+.
ffmpeg/ffprobe sont utilises s'ils sont dans le PATH ; sinon le navigateur
prend le relais pour les posters.
"""

import array
import base64
import io
import json
import math
import mimetypes
import os
import posixpath
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

ICI = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(ICI)          # racine : Coulisses-Du-Cosmos-2026
# Deux dossiers a la racine, et l appartenance remplace la convention de nom :
# un projet est un dossier de projets/, une bibliotheque un dossier de
# bibliotheques/. Ce qui traine ailleurs a la racine n existe pas pour l appli.
# ---- reglages de CETTE bibliotheque ----------------------------------------
# Un fichier facultatif, _app/bibliotheque.json, dit ou sont les rushes, ou
# ranger les donnees, et si l on a le droit de toucher aux dossiers de rushes.
# Sans lui, tout reste exactement comme aux Coulisses du Cosmos : projets/,
# bibliotheques/, donnees dans <projet>/_projet/, port 8779.
FICHIER_REGLAGES = os.path.join(ICI, "bibliotheque.json")
try:
    with io.open(FICHIER_REGLAGES, encoding="utf-8") as _f:
        REGLAGES = json.load(_f) or {}
except Exception:
    REGLAGES = {}
TITRE = REGLAGES.get("titre") or os.path.basename(BASE)
RACINE_PROJETS = os.path.normpath(
    os.path.join(BASE, REGLAGES.get("projets_dans") or "projets"))
RACINE_BIBLIS = os.path.normpath(
    os.path.join(BASE, REGLAGES.get("bibliotheques_dans") or "bibliotheques"))
# Liste blanche : quand les rushes vivent a la racine, a cote de dossiers
# d images et de prompts, on nomme ceux qui sont des projets.
SEULS = [str(x) for x in (REGLAGES.get("projets") or [])]
# Donnees (catalogue, vignettes, sequences, rangement) HORS du dossier de
# rushes : un dossier de rendus peut etre vide ou regenere par un autre outil.
DONNEES = REGLAGES.get("donnees") or ""
# Lecture seule : l application ne renomme, ne deplace, ne cree et n efface
# RIEN dans les dossiers de rushes. Le rangement se fait en dossiers virtuels.
LECTURE_SEULE = bool(REGLAGES.get("lecture_seule"))
APP = os.path.join(ICI, "app.html")
PORT = int(REGLAGES.get("port") or 8779)

# Les donnees d un projet vivent dans <projet>/_projet/ : le dossier est donc
# autonome et deplacable, y compris d une racine a l autre. PAS_PROJET ne sert
# plus qu a mettre un dossier de cote sans le sortir de projets/.
PAS_PROJET = {"contexte"}
DATA = "_projet"

# Anciens emplacements, du temps ou la bibliotheque ne connaissait qu un seul
# dossier de rushes. Ils ne servent plus qu a la migration au demarrage.
VIEUX_PROJET = "GARY-ALL"
VIEUX_CATALOGUE = os.path.join(ICI, "catalogue.json")
VIEUX_POSTERS = os.path.join(ICI, "_posters")
VIEUX_MONTAGES = os.path.join(ICI, "_montages")
VIEUX_JOURNAL = os.path.join(ICI, "journal.jsonl")

API = 5          # version de l API, controlee par l application

# Tout ce qui ecrit DANS un dossier de rushes. En lecture seule, refuse.
ECRIT_DANS_LES_RUSHES = {
    "/api/renommer", "/api/deplacer", "/api/importer", "/api/annuler",
    "/api/dossier/creer", "/api/dossier/renommer", "/api/dossier/effacer",
}

# Le serveur s arrete tout seul quand plus aucune page ne bat la mesure.
# JETON : tire au demarrage, sert uniquement a signer l adieu. Une page tierce
# peut envoyer la requete mais ne peut pas lire la reponse qui le contient, et
# donc ne peut pas eteindre le serveur de David.
JETON = uuid.uuid4().hex
VEILLE = {"signe": None, "adieu": 0.0}
GRACE_ADIEU = 5.0     # on laisse ce delai a un rechargement pour reprendre
GRACE_SILENCE = 600.0 # filet : navigateur ferme brutalement, machine endormie.
                      # Large exprès : l adieu couvre le cas normal, ce filet
                      # ne sert qu aux departs sans preavis.

EXT_VIDEO = (".mp4", ".mov", ".m4v", ".webm")
# Les fichiers de son seul entrent au catalogue comme les rushes : meme fiche,
# meme identifiant stable, mais ni image ni poster. C est ce qui permet a une
# musique d atterrir sur une piste.
EXT_AUDIO = (".wav", ".m4a", ".mp3", ".aac", ".flac", ".ogg", ".aif", ".aiff")
# Les images fixes font des fiches, comme les videos et les sons. Une image
# n a pas de duree : on lui donne celle-ci, et le bloc s etire ensuite
# librement sur la timeline, comme un calque de couleur.
EXT_IMAGE = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif",
             ".tiff", ".avif")
DUREE_IMAGE = 5.0
EXT_MEDIA = EXT_VIDEO + EXT_AUDIO + EXT_IMAGE
# L onde d un son : un pic (0 a 255) toutes les 20 ms, lu a 4 kHz en mono.
# Assez fin pour caler une coupe a l oeil, assez leger pour voyager : une
# minute de son fait 3 000 nombres.
ONDE_HZ = 4000
ONDE_PAR_SEC = 50
# Les bibliotheques ne sont plus nommees ici : tout dossier depose dans
# bibliotheques/ en devient une. Voir biblis_disque().
FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")

_verrou = threading.Lock()


# ---- mise a jour du programme depuis GitHub --------------------------------
# _maj.py (depose a cote par Library Editor) sait comparer ce programme au
# dernier publie et le remplacer, sans jamais toucher aux donnees. Absent —
# bibliotheque plus ancienne — : la fonction n est pas annoncee, rien ne change.
def _charger_maj():
    chemin = os.path.join(ICI, "_maj.py")
    if not os.path.isfile(chemin):
        return None
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("_maj_bibliotheque", chemin)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


MAJ = _charger_maj()


def version_installee():
    if not MAJ:
        return None
    return (MAJ.lire_installe(ICI) or {}).get("version")


def maintenant():
    return time.strftime("%Y-%m-%d %H:%M:%S")


# --- ou vivent les choses, projet par projet -------------------------------
_OU = {}        # nom -> racine, memorise : un dossier ne change pas de camp


def racine_de(pr):
    """Sous quelle racine vit ce dossier. Les noms sont uniques entre les deux
    racines, donc le nom seul suffit a retrouver le chemin. Par defaut
    projets/ : c est la qu on cree."""
    r = _OU.get(pr)
    if r and os.path.isdir(os.path.join(r, pr)):
        return r
    for r in (RACINE_PROJETS, RACINE_BIBLIS):
        if os.path.isdir(os.path.join(r, pr)):
            _OU[pr] = r
            return r
    return RACINE_PROJETS


def media_de(pr):
    return os.path.join(racine_de(pr), pr)


def data_de(pr):
    if DONNEES:
        return os.path.join(BASE, DONNEES, pr)
    return os.path.join(media_de(pr), DATA)


def posters_de(pr):
    return os.path.join(data_de(pr), "_posters")


# ---- rangement virtuel ------------------------------------------------------
# Le meme contrat que la version en ligne (api.php) : des dossiers qui
# n existent sur aucun disque, et une table « ce rush s affiche dans cette
# etagere ». Le catalogue n est jamais touche : « id » et « rel » restent
# ceux du fichier, donc l export XML designe toujours le rush a son
# emplacement reel. Ici, un seul utilisateur : « local ».
def rangement_de(pr):
    return os.path.join(data_de(pr), "_rangement", "local.json")


def _chemin_virtuel(p):
    p = str(p or "").replace("\\", "/").strip("/")
    if not p:
        return ""
    bouts = p.split("/")
    if len(bouts) > 5:
        return None
    propres = []
    for b in bouts:
        b = b.strip()
        if (not b or b in (".", "..") or len(b) > 60
                or re.search(r'[\\/:*?"<>|\x00]', b)):
            return None
        propres.append(b)
    return "/".join(propres)


def rangement_propre(d):
    """Normalise un rangement recu. Les parents d un sous-dossier existent
    toujours, et un rush range dans un dossier absent redevient non range."""
    dossiers = set()
    for x in (d.get("dossiers") or []):
        p = _chemin_virtuel(x)
        if not p:
            continue
        bouts = p.split("/")
        for k in range(1, len(bouts) + 1):
            dossiers.add("/".join(bouts[:k]))
        if len(dossiers) > 300:
            break
    ou = {}
    brut = d.get("ou") or {}
    if isinstance(brut, dict):
        for i, x in brut.items():
            if not re.fullmatch(r"[0-9a-f]{6,32}", str(i)):
                continue
            p = _chemin_virtuel(x)
            if not p or p not in dossiers:
                continue
            ou[str(i)] = p
            if len(ou) > 20000:
                break
    return {"maj": maintenant(), "dossiers": sorted(dossiers), "ou": ou}


def lire_rangement(pr):
    try:
        with open(rangement_de(pr), encoding="utf-8") as f:
            r = json.load(f) or {}
    except Exception:
        r = {}
    return {"dossiers": r.get("dossiers") or [], "ou": r.get("ou") or {}}


def ecrire_rangement(pr, r):
    c = rangement_de(pr)
    os.makedirs(os.path.dirname(c), exist_ok=True)
    tmp = c + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False, indent=1)
    os.replace(tmp, c)          # jamais un rangement a moitie ecrit


def catalogue_de(pr):
    return os.path.join(data_de(pr), "catalogue.json")


def journal_de(pr):
    return os.path.join(data_de(pr), "journal.jsonl")


def montages_de(pr):
    return os.path.join(data_de(pr), "_montages")


# ---- retirer les fiches manquantes ------------------------------------------
# Un rescan GARDE une fiche dont le fichier a disparu (« absent ») : si le
# disque reseau est debranche le temps d un scan, tout le projet passerait
# pour absent, et l effacer ferait perdre notes, couleurs, rangement et
# identifiants. Retirer ces fiches est donc un geste explicite, demande par
# l utilisateur (apres avoir efface des doublons, par exemple), et borde :
#   - rien n est retire si AUCUN fichier du projet n est visible : c est un
#     dossier injoignable, pas un dossier vide ;
#   - une fiche dont le fichier est revenu depuis le scan est gardee ;
#   - une fiche utilisee par une sequence est gardee : si le fichier revient
#     au meme endroit, le montage le retrouve.
# La trace va dans purges.jsonl, PAS dans journal.jsonl : « Undo on disk »
# rejoue ce journal-la et ne doit jamais tomber sur un retrait de fiches.
def ids_en_montage():
    """Les identifiants utilises par au moins une sequence, tous projets
    confondus : un montage peut puiser dans plusieurs projets."""
    ids = {}
    for nom in projets_disque() + biblis_disque():
        d = montages_de(nom)
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if not f.lower().endswith(".json"):
                continue
            try:
                with open(os.path.join(d, f), encoding="utf-8") as fh:
                    m = json.load(fh)
            except Exception:
                continue
            for x in (m.get("clips") or []):
                if x.get("film"):
                    ids.setdefault(x["film"], set()).add(nom + "/" + f[:-5])
    return ids


def purger_absents(pr):
    cat = lire_catalogue(pr)
    films = cat.get("films", [])
    absents = [f for f in films if f.get("absent")]
    if not absents:
        return {"ok": True, "retires": 0, "gardes": [], "revenus": 0,
                "films": films, "dossiers": lister_dossiers(pr)}
    vus = 0
    for f in films:
        c = sur(pr, f.get("rel"))
        if c and os.path.isfile(c):
            vus += 1
    if not os.path.isdir(media_de(pr)) or not vus:
        raise ValueError("no file of this project can be seen on disk right "
                         "now — the drive may be disconnected. Nothing was "
                         "removed.")
    utilises = ids_en_montage()
    retires, gardes, revenus = [], [], 0
    for f in absents:
        c = sur(pr, f.get("rel"))
        if c and os.path.isfile(c):
            revenus += 1          # revenu depuis le scan : le prochain le voit
        elif f["id"] in utilises:
            gardes.append({"id": f["id"], "nom": f.get("nom", ""),
                           "sequences": sorted(utilises[f["id"]])})
        else:
            retires.append(f)
    if retires:
        partis = set(f["id"] for f in retires)
        c = catalogue_de(pr)
        try:
            shutil.copy2(c, c + ".avant-purge")
        except Exception:
            pass
        cat["films"] = [f for f in films if f["id"] not in partis]
        ecrire_catalogue(pr, cat)
        for i in partis:
            for mort in (os.path.join(posters_de(pr), i + ".jpg"),
                         os.path.join(ondes_de(pr), i + ".json")):
                try:
                    os.remove(mort)
                except OSError:
                    pass
        r = lire_rangement(pr)
        if any(i in r["ou"] for i in partis):
            r["ou"] = {k: v for k, v in r["ou"].items() if k not in partis}
            ecrire_rangement(pr, rangement_propre(r))
        try:
            with open(os.path.join(data_de(pr), "purges.jsonl"), "a",
                      encoding="utf-8") as fh:
                fh.write(json.dumps({"t": maintenant(), "fiches": [
                    {"id": f["id"], "rel": f.get("rel"), "nom": f.get("nom"),
                     "octets": f.get("octets"), "s": f.get("s")}
                    for f in retires]}, ensure_ascii=False) + "\n")
        except Exception:
            pass
    return {"ok": True, "retires": len(retires), "gardes": gardes,
            "revenus": revenus, "films": cat["films"],
            "dossiers": lister_dossiers(pr)}


def _dossiers(racine, liste_blanche=True):
    """Les dossiers d une racine. `liste_blanche` False : tous, meme ceux
    que « projets » ne cite pas — c est ce que montre « Open project »."""
    out = []
    try:
        noms = os.listdir(racine)
    except Exception:
        return out
    for n in sorted(noms, key=lambda x: x.lower()):
        if n.startswith((".", "_")) or n in PAS_PROJET:
            continue
        if (liste_blanche and racine == RACINE_PROJETS and SEULS
                and n not in SEULS):
            continue
        if os.path.isdir(os.path.join(racine, n)):
            out.append(n)
    return out


def compter_medias(chemin, plafond=6000):
    """Ce qu un dossier contient, sans rien sonder : videos, sons, images.
    On s arrete au plafond — inutile de parcourir 20 000 images pour dire
    qu il y en a beaucoup."""
    videos = sons = images = 0
    vus = 0
    for dossier, sous, noms in os.walk(chemin):
        sous[:] = [x for x in sous if not x.startswith((".", "_"))]
        for n in noms:
            if n.startswith("._"):
                continue
            bas = n.lower()
            if bas.endswith(EXT_VIDEO):
                videos += 1
            elif bas.endswith(EXT_AUDIO):
                sons += 1
            elif bas.endswith(EXT_IMAGE):
                images += 1
            else:
                continue
            vus += 1
        if vus >= plafond:
            return videos, sons, images, True
    return videos, sons, images, False


def inscrire_projet(nom):
    """Fait entrer un dossier dans la liste blanche de bibliotheque.json,
    apres sauvegarde du fichier. Sans liste blanche, il n y a rien a faire :
    tous les dossiers sont deja des projets."""
    if not SEULS or nom in SEULS:
        return False
    try:
        if os.path.isfile(FICHIER_REGLAGES):
            shutil.copy2(FICHIER_REGLAGES, FICHIER_REGLAGES + ".avant-ajout")
    except OSError:
        pass
    SEULS.append(nom)
    REGLAGES["projets"] = SEULS
    with io.open(FICHIER_REGLAGES, "w", encoding="utf-8") as fr:
        json.dump(REGLAGES, fr, ensure_ascii=False, indent=1)
    return True


def projets_disque():
    """Les projets : les dossiers de projets/."""
    return _dossiers(RACINE_PROJETS)


def biblis_disque():
    """Les bibliotheques partagees : les dossiers de bibliotheques/. Toujours
    ouvertes, jamais dans la liste « ouvrir / creer »."""
    return _dossiers(RACINE_BIBLIS)


def sur(pr, rel):
    """Chemin absolu confine sous le dossier du projet.

    None si la cible s echappe, ou si un segment commence par « _ » ou
    « . » : les donnees du projet et les dossiers caches ne sont jamais
    atteignables par l API de rangement."""
    racine = os.path.normpath(media_de(pr))
    rel = (rel or "").replace("\\", "/").strip("/")
    if not rel:
        return racine
    parts = [p for p in rel.split("/") if p]
    for p in parts:
        if p in (".", "..") or p.startswith(("_", ".")):
            return None
    plein = os.path.normpath(os.path.join(racine, *parts))
    if not (plein == racine or plein.startswith(racine + os.sep)):
        return None
    return plein


def sous_projet(pr, rel):
    """Comme sur(), mais autorise les dossiers techniques (_corbeille).

    Reserve aux operations internes du serveur : jamais alimente directement
    par un nom venu de l application."""
    racine = os.path.normpath(media_de(pr))
    rel = (rel or "").replace("\\", "/").strip("/")
    parts = [p for p in rel.split("/") if p]
    if any(p in (".", "..") for p in parts):
        return None
    plein = os.path.normpath(os.path.join(racine, *parts))
    if not (plein == racine or plein.startswith(racine + os.sep)):
        return None
    return plein


def compter_fichiers(chemin):
    n = 0
    for _, _, noms in os.walk(chemin):
        n += len(noms)
    return n


CORBEILLE = "_corbeille"

NOM_INTERDIT = re.compile('[<>:"/\\\\|?*\\x00-\\x1f]')


def nom_propre(nom):
    nom = (nom or "").strip().strip(".")
    nom = NOM_INTERDIT.sub("", nom)
    nom = re.sub(r"\s+", " ", nom)
    return nom[:180]


def nom_projet(nom, doit_exister=True):
    """Valide un nom de projet : un seul segment, pas cache, pas reserve."""
    nom = (nom or "").replace("\\", "/").strip("/").strip()
    if not nom or "/" in nom:
        return None
    if nom.startswith((".", "_")) or nom in PAS_PROJET:
        return None
    if NOM_INTERDIT.search(nom) or nom != nom_propre(nom):
        return None
    if doit_exister and not os.path.isdir(media_de(nom)):
        return None
    if (doit_exister and SEULS and nom not in SEULS
            and racine_de(nom) == RACINE_PROJETS):
        return None
    return nom


def catalogue_existe(pr):
    return os.path.isfile(catalogue_de(pr))


def lire_catalogue(pr):
    c = catalogue_de(pr)
    if not os.path.isfile(c):
        return {"maj": None, "films": []}
    try:
        with open(c, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"maj": None, "films": []}


def ecrire_catalogue(pr, cat):
    cat["maj"] = maintenant()
    os.makedirs(data_de(pr), exist_ok=True)
    c = catalogue_de(pr)
    tmp = c + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cat, f, ensure_ascii=False, indent=1)
    os.replace(tmp, c)


def noter(pr, op, **infos):
    infos["op"] = op
    infos["t"] = maintenant()
    try:
        os.makedirs(data_de(pr), exist_ok=True)
        with open(journal_de(pr), "a", encoding="utf-8") as f:
            f.write(json.dumps(infos, ensure_ascii=False) + "\n")
    except Exception:
        pass


def journal_dernier(pr):
    j = journal_de(pr)
    if not os.path.isfile(j):
        return None, []
    with open(j, encoding="utf-8") as f:
        lignes = [l for l in f.read().splitlines() if l.strip()]
    if not lignes:
        return None, []
    try:
        return json.loads(lignes[-1]), lignes[:-1]
    except Exception:
        return None, lignes[:-1]


def journal_retirer(pr, restantes):
    with open(journal_de(pr), "w", encoding="utf-8") as f:
        for l in restantes:
            f.write(l + "\n")


def sonder(chemin):
    taille = os.path.getsize(chemin)
    image = chemin.lower().endswith(EXT_IMAGE)
    base = {"m": round(taille / 1048576, 2), "octets": taille,
            "w": None, "h": None, "fps": 0,
            "s": DUREE_IMAGE if image else 0.0, "a": False, "image": image}
    if not FFPROBE:
        return base
    try:
        sortie = subprocess.run(
            [FFPROBE, "-v", "error", "-show_entries",
             "stream=codec_type,width,height,r_frame_rate",
             "-show_entries", "format=duration", "-of", "json", chemin],
            capture_output=True, timeout=40).stdout
        d = json.loads(sortie)
    except Exception:
        return base
    flux = d.get("streams", [])
    v = next((s for s in flux if s.get("codec_type") == "video"), {})
    base["a"] = any(s.get("codec_type") == "audio" for s in flux)
    base["w"], base["h"] = v.get("width"), v.get("height")
    if image:
        # ffprobe donne bien une « duree » a une image (une image a 25 i/s) :
        # elle n a aucun sens ici. La duree d une image, c est celle qu on lui
        # donnera sur la timeline.
        return base
    try:
        num, den = v.get("r_frame_rate", "0/1").split("/")
        base["fps"] = round(int(num) / int(den), 3) if int(den) else 0
    except Exception:
        pass
    try:
        base["s"] = round(float(d.get("format", {}).get("duration", 0)), 3)
    except Exception:
        pass
    return base


def cle_contenu(f):
    """Empreinte stable a travers les renommages : taille + duree.

    Toutes les images ont la meme duree par defaut : on marque les leurs,
    sinon deux images de meme poids se prendraient l une pour l autre."""
    cle = "%d:%.1f" % (f.get("octets") or 0, f.get("s") or 0)
    return cle + ":i" if f.get("image") else cle


SCAN = {"etat": "repos", "projet": "", "fait": 0, "total": 0}
IMPORT = {"etat": "repos", "fait": 0, "total": 0, "nom": ""}


def fichiers_video(pr):
    """Liste (rel, plein) des medias d un projet, sans sonder : c est rapide."""
    racine = media_de(pr)
    trouves = []
    for dossier, sous, noms in os.walk(racine):
        sous[:] = [x for x in sous if not x.startswith((".", "_"))]
        for n in sorted(noms):
            if n.startswith("._") or not n.lower().endswith(EXT_MEDIA):
                continue
            plein = os.path.join(dossier, n)
            trouves.append((os.path.relpath(plein, racine).replace("\\", "/"),
                            plein))
    trouves.sort()
    return trouves


def scanner(pr, bavard=True):
    os.makedirs(posters_de(pr), exist_ok=True)
    cat = lire_catalogue(pr)
    anciens = cat.get("films", [])
    par_chemin = {f["rel"]: f for f in anciens}
    par_cle = {}
    for f in anciens:
        par_cle.setdefault(cle_contenu(f), []).append(f)

    trouves = fichiers_video(pr)
    SCAN.update({"etat": "encours", "projet": pr, "fait": 0,
                 "total": len(trouves)})

    films, pris = [], set()
    for i, (rel, plein) in enumerate(trouves):
        infos = sonder(plein)
        nom, ext = os.path.splitext(os.path.basename(rel))
        dossier = os.path.dirname(rel)
        vieux = par_chemin.get(rel)
        if vieux is None:
            for cand in par_cle.get(cle_contenu(infos), []):
                if id(cand) not in pris:
                    vieux = cand
                    break
        if vieux is not None:
            pris.add(id(vieux))
        fiche = {
            "id": (vieux or {}).get("id") or uuid.uuid4().hex[:12],
            "nom": nom, "ext": ext, "dossier": dossier, "rel": rel,
            "note": (vieux or {}).get("note", ""),
            "fav": (vieux or {}).get("fav", False),
            "coul": (vieux or {}).get("coul", 0),
            "absent": False,
            # Un fichier de son seul n a pas de poster a fabriquer et sa
            # carte s affiche autrement : on le dit une bonne fois.
            "son_seul": ext.lower() in EXT_AUDIO,
            # Une image fixe : ni son, ni duree propre. Le champ voyage
            # jusqu a l application, qui la traite comme un calque avec une
            # image dedans.
            "image": ext.lower() in EXT_IMAGE,
        }
        fiche.update(infos)
        films.append(fiche)
        SCAN["fait"] = i + 1
        if bavard and i % 50 == 0:
            print("%d/%d" % (i, len(trouves)), flush=True)

    vivants = set(f["id"] for f in films)
    for f in anciens:
        if f["id"] not in vivants:
            f["absent"] = True
            films.append(f)

    cat["films"] = films
    cat["racine"] = pr
    ecrire_catalogue(pr, cat)
    SCAN["etat"] = "fini"
    if bavard:
        print("SCAN %s : %d fiches (%d absentes)" %
              (pr, len(films), sum(1 for f in films if f.get("absent"))),
              flush=True)
    return cat


def lister_dossiers(pr):
    racine = media_de(pr)
    out = []
    for dossier, sous, _ in os.walk(racine):
        sous[:] = [x for x in sous if not x.startswith((".", "_"))]
        rel = os.path.relpath(dossier, racine).replace("\\", "/")
        if rel != ".":
            out.append(rel)
    return sorted(out)


def poster_de(pr, fiche):
    return os.path.join(posters_de(pr), fiche["id"] + ".jpg")


def ondes_de(pr):
    return os.path.join(data_de(pr), "_ondes")


_verrou_onde = threading.Lock()


def onde_de(pr, fiche):
    """Les pics du son d un media, pour les dessiner sur la timeline.

    Fabriques une fois par ffmpeg, puis gardes dans _donnees/<projet>/_ondes :
    la source n est jamais touchee, et une piste rouverte s affiche aussitot.
    """
    cible = os.path.join(ondes_de(pr), fiche["id"] + ".json")
    if os.path.isfile(cible):
        try:
            with io.open(cible, encoding="utf-8") as fh:
                d = json.load(fh)
            if d.get("pics"):
                return d
        except (OSError, ValueError):
            pass
    if not FFMPEG:
        raise RuntimeError("ffmpeg is missing: no waveform")
    src = sur(pr, fiche.get("rel") or "")
    if not src or not os.path.isfile(src):
        raise RuntimeError("file not found: %s" % fiche.get("rel"))
    r = subprocess.run([FFMPEG, "-nostdin", "-v", "error", "-i", src, "-vn",
                        "-ac", "1", "-ar", str(ONDE_HZ), "-f", "s16le", "-"],
                       capture_output=True, timeout=600)
    brut = r.stdout or b""
    if len(brut) < 2:
        raise RuntimeError((r.stderr or b"").decode("utf-8", "replace")[-160:]
                           or "no sound in this file")
    ech = array.array("h")
    ech.frombytes(brut[:len(brut) - (len(brut) % 2)])
    largeur = ONDE_HZ // ONDE_PAR_SEC
    pics = []
    for i in range(0, len(ech), largeur):
        bout = ech[i:i + largeur]
        if not bout:
            break
        pics.append(min(255, max(max(bout), -min(bout)) * 255 // 32768))
    d = {"id": fiche["id"], "pas": 1.0 / ONDE_PAR_SEC, "pics": pics,
         "s": round(len(ech) / float(ONDE_HZ), 3)}
    os.makedirs(ondes_de(pr), exist_ok=True)
    tmp = cible + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as fh:
        json.dump(d, fh)
    os.replace(tmp, cible)
    return d


def fabriquer_posters(pr, budget=None, bavard=True):
    if not FFMPEG:
        if bavard:
            print("ffmpeg missing: posters taken by the browser.")
        return 0
    os.makedirs(posters_de(pr), exist_ok=True)
    cat = lire_catalogue(pr)
    fin = (time.time() + budget) if budget else None
    faits = 0
    for f in cat.get("films", []):
        if f.get("absent") or f.get("son_seul"):
            continue
        cible = poster_de(pr, f)
        if os.path.isfile(cible) and os.path.getsize(cible) > 900:
            continue
        if fin and time.time() > fin:
            print("BUDGET %d faits" % faits, flush=True)
            return faits
        src = sur(pr, f["rel"])
        if not src or not os.path.isfile(src):
            continue
        if f.get("image"):
            # Pas de « -ss » sur une image fixe : il n y a rien a chercher.
            cmd = [FFMPEG, "-nostdin", "-v", "error", "-i", src]
        else:
            t = max(0.1, (f.get("s") or 1) * 0.35)
            cmd = [FFMPEG, "-nostdin", "-v", "error", "-ss", "%.2f" % t,
                   "-i", src]
        subprocess.run(cmd + ["-frames:v", "1", "-vf", "scale=480:-2",
                              "-q:v", "4", "-y", cible],
                       capture_output=True, timeout=60)
        faits += 1
    if bavard:
        print("POSTERS %d fabriques" % faits, flush=True)
    return faits


# ---------------------------------------------------------------------------
# Rendu de la sequence finale avec ffmpeg
# ---------------------------------------------------------------------------
RENDU = {"etat": "repos", "fait": 0, "total": 0, "fichier": "", "message": ""}
FPS_SORTIE = 24
# "mp4" image + son · "video" image seule · "audio" son seul
MODE = "mp4"
EXT_MODE = {"mp4": (".mp4",), "video": (".mp4",), "audio": (".wav", ".m4a")}
LARGE, HAUT = 1280, 720


def _couches_shk(cad):
    """La pile de couches. Un montage enregistre avant les couches n a qu un
    jeu de valeurs a plat : on le lit comme une couche unique."""
    cad = cad or {}
    l = cad.get("shks")
    if isinstance(l, list):
        return [x for x in l if isinstance(x, dict)]
    if cad.get("shk"):
        return [{"f": cad.get("shkF", 6), "a": cad.get("shkA", 1.5),
                 "r": cad.get("shkR", 0), "i": cad.get("shkIn", 0),
                 "o": cad.get("shkOut", 0)}]
    return []


def _couche_active(q):
    """Une couche decochee garde ses valeurs mais ne secoue plus. Son rang,
    lui, ne bouge pas : les harmoniques des autres ne doivent pas glisser."""
    return bool((q or {}).get("on", True))


def _rampe_couche(p, u, duree):
    """Montee et descente d UNE couche, en prefixe multiplicatif ou "".

    Contient des virgules (min, max) : toute valeur qui l utilise doit donc
    etre ecrite entre apostrophes dans le graphe de filtres, faute de quoi
    ffmpeg y verrait une separation entre deux filtres."""
    fi = max(0.0, float(p.get("i", 0) or 0))
    fo = max(0.0, float(p.get("o", 0) or 0))
    bouts = []
    if fi >= 0.01:
        bouts.append("%s/%.3f" % (u, fi))
    if fo >= 0.01 and duree > 0.02:
        bouts.append("(%.3f-%s)/%.3f" % (duree, u, fo))
    if not bouts:
        return ""
    inter = bouts[0] if len(bouts) == 1 else "min(%s,%s)" % (bouts[0], bouts[1])
    return "max(0,min(1,%s))*" % inter


def _rampe_secousse(cad, u, duree):
    """Le facteur de montee et de descente, en prefixe multiplicatif ou "".

    Il contient des virgules (min, max) : toute valeur qui l utilise doit donc
    etre ecrite entre apostrophes dans le graphe de filtres."""
    fi = max(0.0, float((cad or {}).get("shkIn", 0) or 0))
    fo = max(0.0, float((cad or {}).get("shkOut", 0) or 0))
    bouts = []
    if fi >= 0.01:
        bouts.append("%s/%.3f" % (u, fi))
    if fo >= 0.01 and duree > 0.02:
        bouts.append("(%.3f-%s)/%.3f" % (duree, u, fo))
    if not bouts:
        return ""
    inter = bouts[0] if len(bouts) == 1 else "min(%s,%s)" % (bouts[0], bouts[1])
    return "max(0,min(1,%s))*" % inter


def _secousse(cad, decalage=0.0, duree=0.0):
    """Les deux expressions ffmpeg de la secousse, en pixels, ou (None, None).

    Reprend a l identique la formule de l application (fonction « secousse » de
    app.html) : deux sinusoides de frequences incommensurables par axe, pour
    qu aucun balancement regulier ne se reconnaisse. Si les deux formules
    divergent un jour, l apercu et le rendu ne secoueront plus pareil.

    « decalage » retranche le temps ecoule avant le debut du bloc : la phase
    doit partir du bloc, pas du montage."""
    cad = cad or {}
    if not cad.get("shk"):
        return None, None
    u = "t" if abs(decalage) < 0.0005 else "(t-%.3f)" % decalage
    p = 2 * math.pi
    # Phases nulles partout, harmoniques decalees d une couche a l autre :
    # exactement la fonction « secousse » de app.html. Toute divergence ici se
    # verrait a l image.
    mx, my = [], []
    for k, q in enumerate(_couches_shk(cad)):
        if not _couche_active(q):
            continue
        a = max(0.0, min(20.0, float(q.get("a", 1.5) or 0)))
        if a < 0.02:
            continue
        f = max(0.1, min(30.0, float(q.get("f", 6) or 6)))
        r = _rampe_couche(q, u, duree)
        ax, ay = LARGE * a / 100.0 / 1.6, HAUT * a / 100.0 / 1.6
        mx.append(r + "%.3f*(sin(%.5f*%s)+0.6*sin(%.5f*%s))"
                  % (ax, p * f, u, p * f * (1.7 + 0.23 * k), u))
        my.append(r + "%.3f*(sin(%.5f*%s)+0.6*sin(%.5f*%s))"
                  % (ay, p * f * (0.83 + 0.07 * k), u, p * f * (2.1 + 0.31 * k), u))
    if not mx:
        return None, None
    return "+".join(mx), "+".join(my)


def _rotation_secousse(cad, decalage=0.0, duree=0.0):
    """L expression ffmpeg de l angle, en RADIANS, ou None.

    Troisieme paire de frequences : l angle ne doit pas suivre le deplacement
    horizontal, sinon la secousse a l air mecanique."""
    cad = cad or {}
    if not cad.get("shk"):
        return None
    u = "t" if abs(decalage) < 0.0005 else "(t-%.3f)" % decalage
    p = 2 * math.pi
    m = []
    for k, q in enumerate(_couches_shk(cad)):
        if not _couche_active(q):
            continue
        r = max(0.0, min(45.0, float(q.get("r", 0) or 0)))
        if r < 0.02:
            continue
        f = max(0.1, min(30.0, float(q.get("f", 6) or 6)))
        amp = math.radians(r) / 1.6
        m.append(_rampe_couche(q, u, duree) +
                 "%.6f*(sin(%.5f*%s)+0.6*sin(%.5f*%s))"
                 % (amp, p * f * (1.3 + 0.17 * k), u, p * f * (0.55 + 0.09 * k), u))
    return "+".join(m) if m else None


def _marge_secousse(cad):
    """De combien agrandir pour qu une secousse ne decouvre aucun bord noir :
    l ecart maximal vaut exactement shkA % de la largeur, de chaque cote."""
    cad = cad or {}
    if not cad.get("shk"):
        return 1.0
    # Le pire des cas, c est toutes les couches alignees : on somme.
    a = deg = 0.0
    for q in _couches_shk(cad):
        if not _couche_active(q):
            continue
        a += max(0.0, min(20.0, float(q.get("a", 1.5) or 0)))
        deg += max(0.0, min(45.0, float(q.get("r", 0) or 0)))
    if a <= 0 and deg <= 0:
        return 1.0
    r = math.radians(deg)
    # Couvrir un cadre tourne coute cos(o) + (cote long / cote court) x sin(o).
    k = max(LARGE / float(HAUT), HAUT / float(LARGE))
    mr = (math.cos(r) + k * math.sin(r)) if r > 0 else 1.0
    return (1.0 + 2.0 * a / 100.0) * mr + 0.01


# Au-dela de cette duree de source, « reverse » garderait trop d images en
# memoire : il les empile TOUTES avant d en ressortir une seule. A la taille du
# projet, une minute de 720p pese deja plus de deux gigaoctets.
LIMITE_INVERSE = 60.0


def _seg_filtre(cadrage, vitesse, opacite=1.0, duree=0.0, rev=False):
    mode = (cadrage or {}).get("mode", "contain")
    if mode == "cover":
        v = ("scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d"
             % (LARGE, HAUT, LARGE, HAUT))
    else:
        v = ("scale=%d:%d:force_original_aspect_ratio=decrease,"
             "pad=%d:%d:(ow-iw)/2:(oh-ih)/2" % (LARGE, HAUT, LARGE, HAUT))
    ech = float((cadrage or {}).get("echelle", 1) or 1)
    if abs(ech - 1) > 0.01:
        v += ",scale=iw*%.4f:ih*%.4f,crop=%d:%d" % (ech, ech, LARGE, HAUT)
    # « reverse » APRES la mise a l echelle — il empile les images decodees,
    # autant qu elles soient deja a la taille de sortie — et AVANT setpts,
    # pour que « t » redevienne ensuite le temps du montage.
    if rev:
        v += ",reverse"
    if abs(vitesse - 1) > 0.001:
        v += ",setpts=%.6f*PTS" % (1.0 / vitesse)
    if opacite < 0.995:
        # composer sur du noir revient a multiplier les canaux RVB
        o = max(0.0, min(1.0, opacite))
        v += ",colorchannelmixer=rr=%.3f:gg=%.3f:bb=%.3f" % (o, o, o)
    # Apres le changement de vitesse : « t » est alors le temps du montage,
    # comme dans le moniteur.
    ex, ey = _secousse(cadrage, 0.0, duree)
    er = _rotation_secousse(cadrage, 0.0, duree)
    if ex or er:
        m = _marge_secousse(cadrage)
        etapes = ["scale=iw*%.4f:ih*%.4f" % (m, m)]
        if er:
            # On tourne AVANT de decouper : la fenetre se promene ensuite dans
            # une image deja inclinee, et la marge garantit qu elle ne sort
            # jamais du cadre.
            etapes.append("rotate=a='%s':ow=iw:oh=ih:fillcolor=black" % er)
        etapes.append("crop=w=%d:h=%d:x='(iw-ow)/2+%s':y='(ih-oh)/2+%s'"
                      % (LARGE, HAUT, ex or "0", ey or "0"))
        v += "," + ",".join(etapes)
    v += ",fps=%d,format=yuv420p,setsar=1" % FPS_SORTIE
    return v


def _expr_vol(cles, echelle, decalage):
    """Expression ffmpeg pour un volume anime.

    Les images-cles arrivent en secondes depuis le debut du bloc ; « decalage »
    retranche ce que les bornes I/O ont rogne en tete. Maintien avant la
    premiere cle, rampes lineaires entre les cles, maintien apres la derniere —
    exactement ce que fait l application dans le moniteur."""
    pts = []
    for k in (cles or []):
        try:
            t = float(k.get("t", 0)) - decalage
            v = max(0.0, float(k.get("v", 1))) * echelle
        except Exception:
            continue
        pts.append((t, v))
    pts.sort()
    if not pts:
        return None
    if len(pts) == 1:
        return "%.4f" % pts[0][1]
    expr = "%.4f" % pts[-1][1]
    for i in range(len(pts) - 1, 0, -1):
        t0, v0 = pts[i - 1]
        t1, v1 = pts[i]
        if t1 - t0 <= 0.0001:
            morceau = "%.4f" % v1
        else:
            morceau = "(%.4f+(%.6f)*(t-%.4f))" % (v0, (v1 - v0) / (t1 - t0), t0)
        expr = "if(lt(t\,%.4f)\,%s\,%s)" % (t1, morceau, expr)
    return "if(lt(t\,%.4f)\,%.4f\,%s)" % (pts[0][0], pts[0][1], expr)


def _atempo(v):
    """atempo n accepte que 0.5..2 : on enchaine si besoin."""
    out, r = [], float(v)
    while r > 2.0:
        out.append("atempo=2.0")
        r /= 2.0
    while r < 0.5:
        out.append("atempo=0.5")
        r /= 0.5
    if abs(r - 1) > 0.001:
        out.append("atempo=%.6f" % r)
    return ",".join(out)


def _segment(plan, dossier, i, avec_son, fi=0.0, fo=0.0, pr_defaut=""):
    """Fabrique un segment normalise. Renvoie (chemin, duree) ou (None, 0).

    Un plan peut venir d un autre projet que celui du montage : il porte alors
    sa propre cle « projet ». Sans cette cle, on prend celui du montage."""
    src = sur(plan.get("projet") or pr_defaut, plan.get("fichier") or "")
    if not src or not os.path.isfile(src):
        return None, 0
    e = float(plan.get("entree", 0))
    o = float(plan.get("sortie", 0))
    vit = abs(float(plan.get("vitesse", 1) or 1)) or 1.0
    rev = bool(plan.get("rev"))
    duree = max(0.05, (o - e) / vit)
    # Une image fixe : ffmpeg la boucle le temps du bloc. Ni vitesse ni
    # lecture inversee — il n y a qu une image, et sa duree est deja celle
    # qu on veut.
    image = src.lower().endswith(EXT_IMAGE)
    if image:
        rev = False
    if rev and MODE != "audio" and (o - e) > LIMITE_INVERSE:
        RENDU["message"] = (
            "un plan inverse de %.0f s depasse la limite de %.0f s : "
            "coupe-le en morceaux plus courts."
            % (o - e, LIMITE_INVERSE))
        return None, 0
    if MODE == "audio":
        cible = os.path.join(dossier, "seg%03d.m4a" % i)
        if not avec_son:
            return _silence(dossier, i, duree)
        af = "[0:a]aresample=48000,aformat=channel_layouts=stereo"
        # Le son s inverse AVANT le changement de tempo : atempo etire ce
        # qu il recoit, l ordre inverse donnerait la meme duree mais pas les
        # memes attaques.
        if rev:
            af += ",areverse"
        tempo = _atempo(vit)
        if tempo:
            af += "," + tempo
        gain = float(plan.get("gain", 1) or 1)
        gexpr = plan.get("gain_expr")
        if gexpr:
            af += ",volume=volume='%s':eval=frame" % gexpr
        elif abs(gain - 1) > 0.01:
            af += ",volume=%.3f" % gain
        if fi > 0.02:
            af += ",afade=t=in:st=0:d=%.3f" % min(fi, duree)
        if fo > 0.02:
            af += ",afade=t=out:st=%.3f:d=%.3f" % (max(0, duree - fo),
                                                  min(fo, duree))
        af += "[a]"
        cmd = [FFMPEG, "-nostdin", "-v", "error", "-ss", "%.3f" % e,
               "-to", "%.3f" % o, "-i", src, "-filter_complex", af,
               "-map", "[a]", "-vn", "-c:a", "aac", "-b:a", "192k",
               "-ar", "48000", "-ac", "2", "-t", "%.3f" % duree, "-y", cible]
        r = subprocess.run(cmd, capture_output=True, timeout=900)
        if r.returncode != 0 or not os.path.isfile(cible):
            RENDU["message"] = (r.stderr or b"").decode("utf-8", "replace")[-400:]
            return None, 0
        return cible, duree

    cible = os.path.join(dossier, "seg%03d.mp4" % i)
    if image:
        cmd = [FFMPEG, "-nostdin", "-v", "error", "-loop", "1",
               "-framerate", str(FPS_SORTIE), "-t", "%.3f" % duree, "-i", src]
    else:
        cmd = [FFMPEG, "-nostdin", "-v", "error", "-ss", "%.3f" % e,
               "-to", "%.3f" % o, "-i", src]
    if MODE == "video":
        avec_son = False
    if not avec_son and MODE != "video":
        cmd += ["-f", "lavfi", "-t", "%.3f" % duree,
                "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
    cmd += ["-filter_complex"]
    vf = _seg_filtre(plan.get("cadrage"), 1.0 if image else vit,
                     float(plan.get("opacite", 1) or 1), duree, rev)
    if fi > 0.02:
        vf += ",fade=t=in:st=0:d=%.3f" % min(fi, duree)
    if fo > 0.02:
        vf += ",fade=t=out:st=%.3f:d=%.3f" % (max(0, duree - fo), min(fo, duree))
    fv = "[0:v]" + vf + "[v]"
    if avec_son:
        af = "[0:a]aresample=48000,aformat=channel_layouts=stereo"
        if rev:
            af += ",areverse"
        tempo = _atempo(vit)
        if tempo:
            af += "," + tempo
        gain = float(plan.get("gain", 1) or 1)
        gexpr = plan.get("gain_expr")
        if gexpr:
            af += ",volume=volume='%s':eval=frame" % gexpr
        elif abs(gain - 1) > 0.01:
            af += ",volume=%.3f" % gain
        if fi > 0.02:
            af += ",afade=t=in:st=0:d=%.3f" % min(fi, duree)
        if fo > 0.02:
            af += ",afade=t=out:st=%.3f:d=%.3f" % (max(0, duree - fo), min(fo, duree))
        af += "[a]"
        cmd += [fv + ";" + af]
    else:
        cmd += [fv]
        if MODE != "video":
            cmd += ["-map", "1:a"]
    cmd += ["-map", "[v]"]
    if avec_son:
        cmd += ["-map", "[a]"]
    cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "18"]
    if MODE == "video":
        cmd += ["-an"]
    else:
        cmd += ["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]
    cmd += ["-t", "%.3f" % duree, "-y", cible]
    r = subprocess.run(cmd, capture_output=True, timeout=900)
    if r.returncode != 0 or not os.path.isfile(cible):
        RENDU["message"] = (r.stderr or b"").decode("utf-8", "replace")[-400:]
        return None, 0
    return cible, duree


# --------------------------------------------------------------------------
#  Blocs sans rush : calque de couleur et texte
# --------------------------------------------------------------------------
# Ils n ont pas de fichier derriere eux. Deux cas :
#   - poses sur la piste video retenue, ils deviennent un segment plein cadre ;
#   - poses sur une piste au-dessus (le cas normal), ils sont incrustes sur le
#     montage assemble, en une seule passe ffmpeg.
# Chaque calque est une entree RGBA de sa propre duree, fondue en alpha puis
# decalee dans le temps par « tpad », et superposee par « overlay ».

# Les polices chargees par l utilisateur vivent dans la bibliotheque, a cote
# de serveur.py — pas dans un projet : une typo sert a tous les montages.
POLICES_LIB = os.path.join(ICI, "_polices")
EXT_POLICE = (".ttf", ".otf", ".ttc", ".woff", ".woff2")
# woff/woff2 conviennent au navigateur mais pas a libfreetype : le rendu
# ffmpeg ne sait graver qu un ttf, otf ou ttc.
EXT_POLICE_RENDU = (".ttf", ".otf", ".ttc")
MAX_POLICE = 12 * 1024 * 1024


def polices_lib():
    """Les polices de la bibliotheque, triees par nom."""
    try:
        noms = sorted(os.listdir(POLICES_LIB))
    except OSError:
        return []
    out = []
    for n in noms:
        if not n.lower().endswith(EXT_POLICE):
            continue
        plein = os.path.join(POLICES_LIB, n)
        if not os.path.isfile(plein):
            continue
        out.append({"nom": n, "octets": os.path.getsize(plein),
                    "rendu": n.lower().endswith(EXT_POLICE_RENDU)})
    return out


def police_lib(nom):
    """Chemin d une police de la bibliotheque, ou None. Confine au dossier."""
    n = os.path.basename(str(nom or "").replace("\\", "/"))
    if not n or not n.lower().endswith(EXT_POLICE):
        return None
    plein = os.path.join(POLICES_LIB, n)
    if os.path.dirname(os.path.abspath(plein)) != os.path.abspath(POLICES_LIB):
        return None
    return plein if os.path.isfile(plein) else None


# ---------------------------------------------------------------------------
#  Prereglages : ils vivent dans la bibliotheque, pas dans le navigateur
# ---------------------------------------------------------------------------
# Un reglage de secousse se trouve a tatons ; il ne doit pas disparaitre avec
# un vidage de cache ou un changement de navigateur. Un fichier par genre, a
# cote des polices : les prereglages appartiennent a la bibliotheque.
PRESETS_LIB = os.path.join(ICI, "_presets")
MAX_PRESETS = 400


def fichier_presets(genre):
    """Le fichier d un genre de prereglages, ou None si le nom ne va pas."""
    g = str(genre or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9_-]{1,24}", g):
        return None
    return os.path.join(PRESETS_LIB, g + ".json")


def lire_presets(genre):
    f = fichier_presets(genre)
    if not f or not os.path.isfile(f):
        return {}
    try:
        with open(f, encoding="utf-8") as fh:
            o = json.load(fh)
        return o if isinstance(o, dict) else {}
    except Exception:
        return {}


def ecrire_presets(genre, o):
    f = fichier_presets(genre)
    if f is None:
        return False
    os.makedirs(PRESETS_LIB, exist_ok=True)
    tmp = f + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(o, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, f)
    return True


def nom_preset(nom):
    """Un nom lisible : pas de retour a la ligne, 40 caracteres au plus."""
    n = re.sub(r"[\r\n\t]+", " ", str(nom or "")).strip()
    return n[:40]


POLICES_WIN = "C:/Windows/Fonts/"
POLICES_REPLI = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/Library/Fonts/Arial.ttf",
]


def _coul_ff(v, defaut="#000000"):
    """Une couleur sure pour ffmpeg : rien d autre que #rrggbb ne passe."""
    v = str(v or "").strip()
    if len(v) == 7 and v[0] == "#":
        try:
            int(v[1:], 16)
            return v.lower()
        except ValueError:
            pass
    return defaut


def _chemin_filtre(chemin):
    """Un chemin utilisable dans une chaine de filtres ffmpeg."""
    c = str(chemin).replace("\\", "/")
    return c.replace(":", "\\:").replace("'", "\\'")


def _police(plan):
    """Le fichier de police a passer a drawtext, ou None.

    La bibliotheque d abord : une typo chargee par l utilisateur prime sur une
    homonyme de Windows, sinon un montage ne rendrait pas ce qu il montre."""
    ttf = os.path.basename(str(plan.get("ttf") or "").strip())
    if ttf:
        propre = police_lib(ttf)
        if propre and ttf.lower().endswith(EXT_POLICE_RENDU):
            return propre
        essai = POLICES_WIN + ttf
        if os.path.isfile(essai):
            return essai
        # meme dossier, casse differente : Windows n est pas sensible a la
        # casse mais un montage peut venir d ailleurs.
        try:
            for n in os.listdir(POLICES_WIN):
                if n.lower() == ttf.lower():
                    return POLICES_WIN + n
        except OSError:
            pass
    for r in POLICES_REPLI:
        if os.path.isfile(r):
            return r
    return None


def _drawtext(plan, travail, n, ech=1.0):
    """Le filtre drawtext d un bloc texte, ou "" si rien n est ecrivable.

    Le texte passe par un fichier : cela evite toute question d echappement
    (deux-points, apostrophes, accents, retours a la ligne)."""
    txt = str(plan.get("texte") or "")
    if not txt.strip():
        return ""
    police = _police(plan)
    if not police:
        return ""
    fich = os.path.join(travail, "texte%03d.txt" % n)
    with io.open(fich, "w", encoding="utf-8") as f:
        f.write(txt)
    taille = float(plan.get("taille") or 9)
    px = max(6, int(round(HAUT * taille / 100.0 * ech)))
    cad = plan.get("cadrage") or {}
    dx = float(cad.get("dx", 0) or 0) * LARGE / 200.0
    dy = float(cad.get("dy", 0) or 0) * HAUT / 200.0
    teinte = _coul_ff(plan.get("teinte"), "#ffffff")
    opac = max(0.0, min(1.0, float(plan.get("opacite", 1) or 1)))
    f = ["drawtext=fontfile=" + _chemin_filtre(police),
         "textfile=" + _chemin_filtre(fich),
         "fontsize=%d" % px,
         "fontcolor=%s@%.3f" % (teinte, opac),
         "line_spacing=%d" % max(0, int(px * 0.2)),
         "x=(w-text_w)/2%+.1f" % dx,
         "y=(h-text_h)/2%+.1f" % dy]
    if plan.get("ombre", True):
        d = max(1, int(round(px * 0.045)))
        f += ["shadowcolor=black@%.3f" % (0.6 * opac),
              "shadowx=%d" % d, "shadowy=%d" % d]
    return ":".join(f)


def _fondus_alpha(fi, fo, duree):
    """Fondus d ouverture et de fermeture sur le canal alpha d un calque."""
    f = ""
    if fi > 0.02:
        f += ",fade=t=in:st=0:d=%.3f:alpha=1" % min(fi, duree)
    if fo > 0.02:
        f += ",fade=t=out:st=%.3f:d=%.3f:alpha=1" % (max(0, duree - fo),
                                                     min(fo, duree))
    return f


def _segment_synth(plan, dossier, i, duree, fi=0.0, fo=0.0):
    """Un calque ou un texte pose sur la piste video retenue : plein cadre."""
    if MODE == "audio":
        return _silence(dossier, i, duree)
    cible = os.path.join(dossier, "seg%03d.mp4" % i)
    genre = plan.get("genre")
    cad = plan.get("cadrage") or {}
    ech = max(0.01, float(cad.get("echelle", 1) or 1))
    opac = max(0.0, min(1.0, float(plan.get("opacite", 1) or 1)))
    if genre == "couleur":
        # Le calque est seul a l image : on melange sa couleur avec le noir
        # selon sa transparence, plutot que de composer pour rien.
        base = _coul_ff(plan.get("fond"))
        r = int(base[1:3], 16) * opac
        v = int(base[3:5], 16) * opac
        b = int(base[5:7], 16) * opac
        fond = "#%02x%02x%02x" % (int(r), int(v), int(b))
        vf = "null"
        if ech < 0.999:
            # un aplat reduit, centre sur du noir
            vf = ("scale=%d:%d,pad=%d:%d:(ow-iw)/2:(oh-ih)/2:black"
                  % (max(2, int(LARGE * ech)) & ~1, max(2, int(HAUT * ech)) & ~1,
                     LARGE, HAUT))
    else:
        fond = "black"
        vf = _drawtext(plan, dossier, i, ech) or "null"
    cmd = [FFMPEG, "-nostdin", "-v", "error", "-f", "lavfi", "-i",
           "color=c=%s:s=%dx%d:r=%d" % (fond, LARGE, HAUT, FPS_SORTIE)]
    if MODE != "video":
        cmd += ["-f", "lavfi", "-i",
                "anullsrc=channel_layout=stereo:sample_rate=48000"]
    if fi > 0.02:
        vf += ",fade=t=in:st=0:d=%.3f" % min(fi, duree)
    if fo > 0.02:
        vf += ",fade=t=out:st=%.3f:d=%.3f" % (max(0, duree - fo), min(fo, duree))
    cmd += ["-filter_complex", "[0:v]" + vf + ",format=yuv420p[v]", "-map", "[v]"]
    if MODE != "video":
        cmd += ["-map", "1:a", "-c:a", "aac", "-b:a", "192k",
                "-ar", "48000", "-ac", "2"]
    else:
        cmd += ["-an"]
    cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-t", "%.3f" % duree, "-y", cible]
    r = subprocess.run(cmd, capture_output=True, timeout=900)
    if r.returncode != 0 or not os.path.isfile(cible):
        RENDU["message"] = (r.stderr or b"").decode("utf-8", "replace")[-400:]
        return None, 0
    return cible, duree


def _incruster(base, sortie, calques, a0, b0, travail):
    """Superpose les calques sur le montage assemble, en une passe.

    Chaque calque devient une entree RGBA de sa propre duree : couleur pleine,
    ou canevas transparent grave par drawtext. Fondus sur l alpha, decalage
    dans le temps par tpad, puis overlay en chaine."""
    cmd = [FFMPEG, "-nostdin", "-v", "error", "-i", base]
    chaine, etiq, n = [], "0:v", 0
    for plan in calques:
        pos = float(plan.get("position", 0) or 0)
        d = float(plan.get("duree", 0) or 0)
        if pos < a0:
            d -= (a0 - pos)
            pos = a0
        if b0 and pos + d > b0:
            d = b0 - pos
        if d <= 0.06:
            continue
        pos -= a0
        genre = plan.get("genre")
        cad = plan.get("cadrage") or {}
        ech = max(0.01, float(cad.get("echelle", 1) or 1))
        opac = max(0.0, min(1.0, float(plan.get("opacite", 1) or 1)))
        dx = float(cad.get("dx", 0) or 0) * LARGE / 200.0
        dy = float(cad.get("dy", 0) or 0) * HAUT / 200.0
        fi = float(plan.get("fondu_entree", 0) or 0)
        fo = float(plan.get("fondu_sortie", 0) or 0)
        n += 1
        # La phase part du debut du calque : « t » est ici le temps du
        # montage assemble, et le calque entre a « pos ».
        sx, sy = _secousse(cad, pos, d)
        sr = _rotation_secousse(cad, pos, d)
        if genre == "couleur":
            # Le calque de couleur est agrandi comme un rush, sinon la
            # secousse decouvrirait le bord du montage.
            mg = _marge_secousse(cad)
            w = max(2, int(round(LARGE * ech * mg))) & ~1
            h = max(2, int(round(HAUT * ech * mg))) & ~1
            cmd += ["-f", "lavfi", "-t", "%.3f" % d, "-i",
                    "color=c=%s:s=%dx%d:r=%d,format=rgba"
                    % (_coul_ff(plan.get("fond")), w, h, FPS_SORTIE)]
            f = "[%d:v]colorchannelmixer=aa=%.3f" % (n, opac)
            x = "%.1f" % ((LARGE - w) / 2.0 + dx)
            y = "%.1f" % ((HAUT - h) / 2.0 + dy)
            if sx:
                x, y = x + "+" + sx, y + "+" + sy
        else:
            dessin = _drawtext(plan, travail, n, ech)
            if not dessin:
                # texte vide, ou police introuvable : rien a graver. On rend
                # l indice, aucune entree n ayant ete ajoutee.
                n -= 1
                continue
            cmd += ["-f", "lavfi", "-t", "%.3f" % d, "-i",
                    "color=c=black@0.0:s=%dx%d:r=%d,format=rgba"
                    % (LARGE, HAUT, FPS_SORTIE)]
            f = "[%d:v]" % n + dessin
            if sr:
                # Le canevas du texte est transparent et plein cadre : le faire
                # tourner fait tourner le texte autour du centre de l image.
                f += ",rotate=a='%s':ow=iw:oh=ih:fillcolor=black@0.0" % sr
            # Le canevas du texte est transparent et plein cadre : le secouer
            # ne decouvre rien, il n y a donc pas de marge a prendre.
            x, y = (sx, sy) if sx else ("0", "0")
        f += _fondus_alpha(fi, fo, d)
        if pos > 0.001:
            f += ",tpad=start_duration=%.3f:start_mode=add:color=black@0.0" % pos
        f += "[c%d]" % n
        chaine.append(f)
        suivante = "b%d" % n
        chaine.append("[%s][c%d]overlay=x='%s':y='%s':eof_action=pass[%s]"
                      % (etiq, n, x, y, suivante))
        etiq = suivante
    if not n:
        # Tous les calques sont tombes hors des bornes, ou n avaient rien a
        # graver. Ce n est pas un echec : le montage assemble est le resultat.
        shutil.copyfile(base, sortie)
        return True
    chaine.append("[%s]format=yuv420p[v]" % etiq)
    cmd += ["-filter_complex", ";".join(chaine), "-map", "[v]"]
    if MODE != "video":
        cmd += ["-map", "0:a?", "-c:a", "copy"]
    else:
        cmd += ["-an"]
    cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p", "-y", sortie]
    r = subprocess.run(cmd, capture_output=True, timeout=3600)
    if r.returncode != 0 or not os.path.isfile(sortie):
        RENDU["message"] = (r.stderr or b"").decode("utf-8", "replace")[-500:]
        return False
    return True


def _mixer(base, sortie, libres, a0, b0, pr_defaut):
    """Melange au montage assemble les sons qui ne sont lies a aucun plan.

    C est le cas de toute la musique, et des bruitages poses seuls : jusqu ici
    ils s affichaient mais ne sortaient pas. Chaque son devient une entree,
    rognee a ses points d entree et de sortie, mise a son volume, fondue, puis
    decalee dans le temps par « adelay » ; « amix » les superpose au son deja
    la, sans normaliser — sinon ajouter une piste baisserait tout le reste."""
    cmd = [FFMPEG, "-nostdin", "-v", "error", "-i", base]
    chaine, etiqs, n = [], [], 0
    for plan in libres:
        src = sur(plan.get("projet") or pr_defaut, plan.get("fichier") or "")
        if not src or not os.path.isfile(src):
            continue
        pos = float(plan.get("position", 0) or 0)
        d = float(plan.get("duree", 0) or 0)
        e = float(plan.get("entree", 0) or 0)
        vit = max(0.1, abs(float(plan.get("vitesse", 1) or 1)))
        if pos < a0:                      # rogne par le point d entree
            e += (a0 - pos) * vit
            d -= (a0 - pos)
            pos = a0
        if b0 and pos + d > b0:
            d = b0 - pos
        if d <= 0.06:
            continue
        pos -= a0
        n += 1
        cmd += ["-i", src]
        f = ["[%d:a]atrim=start=%.3f:end=%.3f" % (n, max(0, e), max(0, e) + d * vit),
             "asetpts=PTS-STARTPTS",
             "aresample=48000", "aformat=channel_layouts=stereo"]
        if plan.get("rev"):
            f.append("areverse")
        tempo = _atempo(vit)
        if tempo:
            f.append(tempo)
        gain = float(plan.get("gain", 1) or 1)
        gexpr = plan.get("gain_expr")
        if gexpr:
            f.append("volume=volume='%s':eval=frame" % gexpr)
        elif abs(gain - 1) > 0.01:
            f.append("volume=%.3f" % gain)
        fi = float(plan.get("fondu_entree", 0) or 0)
        fo = float(plan.get("fondu_sortie", 0) or 0)
        if fi > 0.02:
            f.append("afade=t=in:st=0:d=%.3f" % min(fi, d))
        if fo > 0.02:
            f.append("afade=t=out:st=%.3f:d=%.3f" % (max(0, d - fo), min(fo, d)))
        if pos > 0.001:
            ms = int(round(pos * 1000))
            f.append("adelay=%d|%d" % (ms, ms))
        etiq = "s%d" % n
        chaine.append(",".join(f) + "[%s]" % etiq)
        etiqs.append(etiq)
    if not n:
        # Rien a melanger : le fichier assemble est deja le resultat.
        shutil.copyfile(base, sortie)
        return True
    # « duration=first » garde la duree du montage : une musique plus longue
    # que l image ne rallonge pas le film.
    entrees = "[0:a]" + "".join("[%s]" % x for x in etiqs)
    chaine.append(entrees + "amix=inputs=%d:normalize=0:duration=first:"
                  "dropout_transition=0[a]" % (len(etiqs) + 1))
    cmd += ["-filter_complex", ";".join(chaine), "-map", "[a]"]
    if MODE != "audio":
        cmd += ["-map", "0:v", "-c:v", "copy"]
    ext = os.path.splitext(sortie)[1].lower()
    if ext == ".wav":
        cmd += ["-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2"]
    else:
        cmd += ["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]
    if ext == ".mp4":
        cmd += ["-movflags", "+faststart"]
    cmd += ["-y", sortie]
    r = subprocess.run(cmd, capture_output=True, timeout=3600)
    if r.returncode != 0 or not os.path.isfile(sortie):
        RENDU["message"] = (r.stderr or b"").decode("utf-8", "replace")[-500:]
        return False
    return True


def _silence(dossier, i, duree):
    cible = os.path.join(dossier, "seg%03d.m4a" % i)
    cmd = [FFMPEG, "-nostdin", "-v", "error", "-f", "lavfi", "-i",
           "anullsrc=channel_layout=stereo:sample_rate=48000",
           "-t", "%.3f" % duree, "-c:a", "aac", "-b:a", "192k", "-y", cible]
    r = subprocess.run(cmd, capture_output=True, timeout=300)
    return (cible, duree) if r.returncode == 0 else (None, 0)


def _noir(dossier, i, duree):
    if MODE == "audio":
        return _silence(dossier, i, duree)
    cible = os.path.join(dossier, "seg%03d.mp4" % i)
    cmd = [FFMPEG, "-nostdin", "-v", "error",
           "-f", "lavfi", "-i", "color=c=black:s=%dx%d:r=%d" % (LARGE, HAUT, FPS_SORTIE)]
    if MODE != "video":
        cmd += ["-f", "lavfi", "-i",
                "anullsrc=channel_layout=stereo:sample_rate=48000"]
    cmd += ["-t", "%.3f" % duree, "-c:v", "libx264", "-preset", "veryfast",
            "-crf", "20", "-pix_fmt", "yuv420p"]
    cmd += (["-an"] if MODE == "video" else ["-c:a", "aac", "-b:a", "192k"])
    cmd += ["-y", cible]
    r = subprocess.run(cmd, capture_output=True, timeout=300)
    return (cible, duree) if r.returncode == 0 else (None, 0)


def _codecs(sortie):
    """Encodeurs de sortie, selon le mode et l extension demandee."""
    ext = os.path.splitext(sortie)[1].lower()
    out = []
    if MODE == "audio":
        out += ["-vn"]
    else:
        out += ["-c:v", "libx264", "-preset", "medium", "-crf", "18",
                "-pix_fmt", "yuv420p", "-r", str(FPS_SORTIE)]
    if MODE == "video":
        out += ["-an"]
    elif ext == ".wav":
        out += ["-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2"]
    else:
        out += ["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]
    if ext == ".mp4":
        out += ["-movflags", "+faststart"]
    return out


def _assembler(segments, sortie):
    """Assemble les segments : concatenation sur les coupes franches, fondu
    enchaine sur les recouvrements. Chaque entree est d abord normalisee —
    sans cela, concat produit une base de temps que xfade refuse ensuite."""
    avec_v = MODE != "audio"
    avec_a = MODE != "video"

    if len(segments) == 1:
        meme = (os.path.splitext(segments[0][0])[1].lower() ==
                os.path.splitext(sortie)[1].lower())
        if meme:
            shutil.copyfile(segments[0][0], sortie)
            return True
        cmd = ([FFMPEG, "-nostdin", "-v", "error", "-i", segments[0][0]]
               + _codecs(sortie) + ["-y", sortie])
        r = subprocess.run(cmd, capture_output=True, timeout=1800)
        if r.returncode != 0:
            RENDU["message"] = (r.stderr or b"").decode("utf-8", "replace")[-500:]
            return False
        return True

    cmd = [FFMPEG, "-nostdin", "-v", "error"]
    for seg in segments:
        cmd += ["-i", seg[0]]

    pre = []
    for i in range(len(segments)):
        # settb en dernier : fps= remet la base de temps, donc il doit passer avant
        if avec_v:
            pre.append("[%d:v]setpts=PTS-STARTPTS,fps=%d,format=yuv420p,setsar=1,"
                       "settb=1/%d[nv%d]" % (i, FPS_SORTIE, FPS_SORTIE, i))
        if avec_a:
            pre.append("[%d:a]asetpts=PTS-STARTPTS,"
                       "aformat=sample_fmts=fltp:sample_rates=48000:"
                       "channel_layouts=stereo,asettb=1/48000[na%d]" % (i, i))

    fv, fa = [], []
    vlab, alab = "nv0", "na0"
    cumul = segments[0][1]
    for i in range(1, len(segments)):
        duree, recouv = segments[i][1], segments[i][2]
        nv, na = "v%d" % i, "a%d" % i
        if recouv > 0.02:
            d = max(1.0 / FPS_SORTIE, min(recouv, duree - 0.05, cumul - 0.05))
            offset = max(0.0, cumul - d)
            if avec_v:
                fv.append("[%s][nv%d]xfade=transition=fade:duration=%.3f:"
                          "offset=%.3f,settb=1/%d[%s]"
                          % (vlab, i, d, offset, FPS_SORTIE, nv))
            if avec_a:
                fa.append("[%s][na%d]acrossfade=d=%.3f:c1=tri:c2=tri,"
                          "asettb=1/48000[%s]" % (alab, i, d, na))
            cumul = offset + duree
        else:
            if avec_v:
                fv.append("[%s][nv%d]concat=n=2:v=1:a=0,settb=1/%d[%s]"
                          % (vlab, i, FPS_SORTIE, nv))
            if avec_a:
                fa.append("[%s][na%d]concat=n=2:v=0:a=1,asettb=1/48000[%s]"
                          % (alab, i, na))
            cumul = cumul + duree
        vlab, alab = nv, na

    cmd += ["-filter_complex", ";".join(pre + fv + fa)]
    if avec_v:
        cmd += ["-map", "[%s]" % vlab]
    if avec_a:
        cmd += ["-map", "[%s]" % alab]
    cmd += _codecs(sortie) + ["-y", sortie]
    r = subprocess.run(cmd, capture_output=True, timeout=3600)
    if r.returncode != 0:
        RENDU["message"] = (r.stderr or b"").decode("utf-8", "replace")[-500:]
        return False
    return True


# Une page web ne peut pas lire un chemin disque : c est le serveur, qui
# tourne sur la machine de David, qui ouvre le selecteur. Le dialogue part dans
# un processus separe — Tk n aime pas vivre dans un fil de serveur HTTP.
_CHOISIR_TK = (
    "import sys\n"
    "import tkinter as tk\n"
    "from tkinter import filedialog\n"
    "r = tk.Tk(); r.withdraw(); r.attributes('-topmost', True)\n"
    "d = filedialog.askdirectory(title='Render output folder',\n"
    "                            initialdir=(sys.argv[1] or None))\n"
    "sys.stdout.write(d or '')\n"
)

_CHOISIR_PS = (
    "Add-Type -AssemblyName System.Windows.Forms | Out-Null; "
    "$d = New-Object System.Windows.Forms.FolderBrowserDialog; "
    "$d.Description = 'Render output folder'; "
    "$d.SelectedPath = '%s'; "
    "if ($d.ShowDialog() -eq 'OK') { [Console]::Out.Write($d.SelectedPath) }"
)


def _sans_console():
    """Sous Windows, empeche le clignotement d une console noire."""
    return {"creationflags": 0x08000000} if sys.platform == "win32" else {}


def _python_muet():
    """pythonw.exe s il existe : il ouvre la fenetre Tk sans console."""
    exe = sys.executable or "python"
    if sys.platform == "win32":
        muet = os.path.join(os.path.dirname(exe), "pythonw.exe")
        if os.path.isfile(muet):
            return muet
    return exe


def choisir_dossier(depart):
    """Ouvre un selecteur de dossier natif et renvoie le chemin, ou "" si
    l utilisateur annule. None si aucun selecteur n est disponible."""
    depart = depart if depart and os.path.isdir(depart) else ""
    try:
        r = subprocess.run([_python_muet(), "-c", _CHOISIR_TK, depart],
                           capture_output=True, timeout=300, **_sans_console())
        if r.returncode == 0:
            return r.stdout.decode("utf-8", "replace").strip()
    except Exception:
        pass
    if sys.platform == "win32":
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-STA", "-Command",
                 _CHOISIR_PS % depart.replace("'", "''")],
                capture_output=True, timeout=300, **_sans_console())
            if r.returncode == 0:
                return r.stdout.decode("utf-8", "replace").strip()
        except Exception:
            pass
    return None


def _destination(pr, nom, demande, mode):
    """Ou ecrire le rendu.

    Par defaut dans les montages du projet. Un chemin donne peut etre absolu
    ou relatif au dossier du projet, et designer soit un dossier soit un
    fichier. L extension est alignee sur le mode. On n ecrase jamais : le nom
    est suffixe -2, -3 si la place est prise."""
    exts = EXT_MODE[mode]
    demande = (demande or "").strip().replace("/", os.sep).replace("\\", os.sep)
    if not demande:
        dossier, feuille = montages_de(pr), nom + exts[0]
    else:
        plein = demande
        if not os.path.isabs(plein):
            # En lecture seule, un chemin relatif part des sequences, pas du
            # dossier de rushes.
            plein = os.path.join(montages_de(pr) if LECTURE_SEULE
                                 else media_de(pr), plein)
        plein = os.path.normpath(plein)
        # Dossier ou fichier ? Un dossier qui n existe pas encore ne doit pas
        # passer pour un nom de fichier : ce qui tranche, c est la presence
        # d une extension sur le dernier element du chemin.
        feuille_fin = os.path.basename(plein)
        _, ext_fin = os.path.splitext(feuille_fin)
        if os.path.isdir(plein) or not ext_fin:
            dossier, feuille = plein, nom + exts[0]
        else:
            dossier, feuille = os.path.dirname(plein), feuille_fin
            if not dossier:
                dossier, feuille = plein, nom + exts[0]
    base, ext = os.path.splitext(feuille)
    if ext.lower() not in exts:
        ext = exts[0]
    base = nom_propre(base) or nom
    if LECTURE_SEULE:
        rush = os.path.normcase(os.path.normpath(media_de(pr)))
        vise = os.path.normcase(os.path.normpath(dossier))
        if vise == rush or vise.startswith(rush + os.sep):
            raise ValueError("this library never writes into “%s” — choose "
                             "another output folder" % pr)
    try:
        os.makedirs(dossier, exist_ok=True)
    except Exception as e:
        raise ValueError("output folder failed: %s: %s"
                         % (type(e).__name__, e))
    k, cible = 1, os.path.join(dossier, base + ext)
    while os.path.exists(cible):
        k += 1
        cible = os.path.join(dossier, "%s-%d%s" % (base, k, ext))
    return cible


def rendre(montage, nom, pr, cible=None, mode="mp4"):
    """Tourne dans un thread. Met a jour RENDU au fur et a mesure."""
    global LARGE, HAUT, FPS_SORTIE, MODE
    try:
        MODE = mode if mode in EXT_MODE else "mp4"
        RENDU.update({"etat": "encours", "fait": 0, "total": 0,
                      "fichier": "", "message": "", "type": MODE,
                      "vers": cible or ""})
        if not FFMPEG:
            raise RuntimeError("ffmpeg not found in PATH")
        # specifications du projet, avec garde-fous
        f = montage.get("format") or {}
        LARGE = max(64, min(7680, int(f.get("w") or 1280)))
        HAUT = max(64, min(4320, int(f.get("h") or 720)))
        LARGE -= LARGE % 2
        HAUT -= HAUT % 2
        FPS_SORTIE = max(1, min(120, int(round(float(montage.get("fps") or 24)))))
        plans = montage.get("plans") or []
        pistes = {p["id"]: p for p in (montage.get("pistes") or [])}

        # piste video retenue : celle qui porte le plus de plans, la plus haute
        compte = {}
        for p in plans:
            pid = p.get("piste", "")
            if p.get("genre"):
                # Un calque ou un texte ne doit pas peser dans le choix de la
                # piste : sinon deux textes suffiraient a detourner le rendu
                # sur leur propre piste et l image disparaitrait.
                continue
            if pistes.get(pid, {}).get("type") == "v" and not pistes[pid].get("mute"):
                compte[pid] = compte.get(pid, 0) + 1
        if not compte:
            # Rien que des calques ? On rend quand meme : la piste video la
            # plus basse qui en porte fait l affaire.
            for p in plans:
                pid = p.get("piste", "")
                if (p.get("genre") and pistes.get(pid, {}).get("type") == "v"
                        and not pistes[pid].get("mute")):
                    compte[pid] = compte.get(pid, 0) + 1
        if not compte:
            raise RuntimeError("no shot on an active video track")
        pv = sorted(compte.items(), key=lambda kv: (kv[1], kv[0]))[-1][0]

        # Les calques poses ailleurs que sur la piste retenue sont incrustes
        # sur le montage assemble, dans une seconde passe.
        calques = sorted(
            [p for p in plans
             if p.get("genre") and p.get("piste") != pv
             and pistes.get(p.get("piste", ""), {}).get("type") == "v"
             and not pistes[p["piste"]].get("mute")],
            key=lambda p: (p.get("piste", ""), float(p.get("position", 0) or 0)))

        # sons disponibles, par lien
        sons = {}
        for p in plans:
            pid = p.get("piste", "")
            if pistes.get(pid, {}).get("type") == "a" and not pistes[pid].get("mute"):
                if p.get("lien"):
                    sons[p["lien"]] = p

        # Tout ce qui sonne sans etre lie a un plan : la musique par
        # definition, et les bruitages poses seuls. Melanges en fin de course.
        def _sonore(pid):
            t = pistes.get(pid, {})
            return t.get("type") in ("a", "m") and not t.get("mute")
        libres = []
        for p in plans:
            pid = p.get("piste", "")
            if not _sonore(pid) or p.get("genre"):
                continue
            if p.get("lien") and sons.get(p["lien"]) is p:
                continue
            q = dict(p)
            pa = pistes.get(pid, {})
            tr = float(pa.get("vol", 1) if pa.get("vol") is not None else 1)
            animg = (p.get("anim") or {}).get("gain")
            if animg:
                q["gain_expr"] = _expr_vol(animg, tr,
                                           float(p.get("position", 0) or 0) - a0)
                q["gain"] = 1.0
            else:
                q["gain"] = float(p.get("gain", 1) or 1) * tr
            libres.append(q)

        v = sorted([p for p in plans if p.get("piste") == pv],
                   key=lambda p: float(p.get("position", 0)))
        a0 = float(montage.get("entree", 0) or 0)
        b0 = float(montage.get("sortie", 0) or 0)

        travail = os.path.join(montages_de(pr), "_travail")
        shutil.rmtree(travail, ignore_errors=True)
        os.makedirs(travail, exist_ok=True)

        RENDU["total"] = len(v)
        segments = []
        precedent_fin = a0
        i = 0
        for idx, p in enumerate(v):
            pos = pos0 = float(p.get("position", 0))
            duree = float(p.get("duree", 0))
            vit = abs(float(p.get("vitesse", 1) or 1)) or 1.0
            e = float(p.get("entree", 0))
            o = float(p.get("sortie", 0))
            # bornes I/O
            if pos < a0:
                e += (a0 - pos) * vit
                duree -= (a0 - pos)
                pos = a0
            if b0 and pos + duree > b0:
                o -= (pos + duree - b0) * vit
                duree = b0 - pos
            if duree <= 0.06 or o - e <= 0.06:
                RENDU["fait"] += 1
                continue
            trou = pos - precedent_fin
            if trou > 0.08:
                c, d = _noir(travail, i, trou)
                if c:
                    segments.append((c, d, 0.0))
                    i += 1
            recouv = max(0.0, precedent_fin - pos)
            lien = p.get("lien")
            son = sons.get(lien) if lien else None
            avec_son = son is not None
            q = dict(p)
            q["entree"], q["sortie"], q["duree"] = e, o, duree
            # Le volume vient du bloc audio, pas du bloc image, multiplie par
            # le volume general de sa piste. Sans ca le reglage de volume ne
            # sortait jamais de l application.
            if son is not None:
                pa = pistes.get(son.get("piste"), {})
                tr = float(pa.get("vol", 1) if pa.get("vol") is not None else 1)
                animg = (son.get("anim") or {}).get("gain")
                if animg:
                    # Le volume est anime : ffmpeg l evalue image par image,
                    # avec le volume de piste deja multiplie dedans.
                    q["gain_expr"] = _expr_vol(animg, tr, pos - pos0)
                    q["gain"] = 1.0
                else:
                    q["gain"] = float(son.get("gain", 1) or 1) * tr
            # un fondu explicite n est cuit dans le segment que si ce cote
            # n est pas deja traite par un fondu enchaine de l assemblage
            suivant = v[idx + 1] if idx + 1 < len(v) else None
            recouv_apres = 0.0
            if suivant is not None:
                recouv_apres = max(0.0, (pos + duree) -
                                   float(suivant.get("position", 0)))
            fi_c = 0.0 if recouv > 0.02 else float(p.get("fondu_entree", 0) or 0)
            fo_c = 0.0 if recouv_apres > 0.02 else float(p.get("fondu_sortie", 0) or 0)
            if p.get("genre"):
                c, d = _segment_synth(q, travail, i, duree, fi_c, fo_c)
            else:
                c, d = _segment(q, travail, i, avec_son, fi_c, fo_c, pr)
            if not c:
                raise RuntimeError("segment %d failed: %s" % (i, RENDU["message"]))
            segments.append((c, d, recouv if segments else 0.0))
            precedent_fin = pos + duree
            i += 1
            RENDU["fait"] += 1

        # noir final si le point de sortie depasse le dernier plan
        if b0 and b0 - precedent_fin > 0.08:
            c, d = _noir(travail, i, b0 - precedent_fin)
            if c:
                segments.append((c, d, 0.0))

        if not segments:
            raise RuntimeError("no segment to assemble")
        sortie = cible or os.path.join(montages_de(pr),
                                       nom_propre(nom) + EXT_MODE[MODE][0])
        os.makedirs(os.path.dirname(sortie), exist_ok=True)
        # En mode audio les calques ne donnent rien, en mode image seule le
        # melange non plus : chaque passe ne tourne que si elle a un objet.
        a_incruster = calques if MODE != "audio" else []
        a_melanger = libres if MODE != "video" else []
        ext0 = EXT_MODE[MODE][0]
        brut = (os.path.join(travail, "assemble" + ext0)
                if (a_incruster or a_melanger) else sortie)
        if not _assembler(segments, brut):
            raise RuntimeError("assembly failed: " + RENDU["message"])
        cour = brut
        if a_incruster:
            RENDU["message"] = "compositing %d layer(s)" % len(a_incruster)
            suiv = (os.path.join(travail, "incruste.mp4") if a_melanger
                    else sortie)
            if not _incruster(cour, suiv, a_incruster, a0, b0, travail):
                raise RuntimeError("overlay pass failed: " + RENDU["message"])
            cour = suiv
        if a_melanger:
            RENDU["message"] = "mixing %d unlinked sound(s)" % len(a_melanger)
            if not _mixer(cour, sortie, a_melanger, a0, b0, pr):
                raise RuntimeError("audio mix failed: " + RENDU["message"])
        RENDU["message"] = ""
        shutil.rmtree(travail, ignore_errors=True)
        RENDU.update({"etat": "fini", "fichier": sortie})
    except Exception as e:
        RENDU.update({"etat": "erreur",
                      "message": "%s: %s" % (type(e).__name__, e)})


def _port_occupe(port):
    import socket
    s = socket.socket()
    s.settimeout(0.4)
    try:
        s.connect(("127.0.0.1", port))
        return True
    except Exception:
        return False
    finally:
        try:
            s.close()
        except Exception:
            pass


def _pid_sur_port(port):
    """Sous Windows : le PID qui ecoute sur ce port, ou None."""
    if sys.platform != "win32":
        return None
    try:
        out = subprocess.run(["netstat", "-ano", "-p", "TCP"],
                             capture_output=True, timeout=15).stdout
        out = out.decode("utf-8", "replace")
    except Exception:
        return None
    for ligne in out.splitlines():
        m = ligne.split()
        if (len(m) >= 5 and m[0].upper() == "TCP"
                and m[1].endswith(":" + str(port))
                and m[3].upper() == "LISTENING"):
            try:
                return int(m[4])
            except Exception:
                return None
    return None


def _est_python(pid):
    try:
        out = subprocess.run(["tasklist", "/FI", "PID eq %d" % pid,
                              "/FO", "CSV", "/NH"],
                             capture_output=True, timeout=15).stdout
        return b"python" in out.lower()
    except Exception:
        return False


def arreter_precedent():
    """Libere le port : demande polie d abord, fermeture du processus ensuite.

    L ancienne version du serveur ne connait pas /api/arret : sans le second
    recours, relancer l application echouait a se lier et l ancienne instance
    continuait de repondre — d ou une application qui ne se mettait jamais a
    jour."""
    try:
        req = urllib.request.Request("http://127.0.0.1:%d/api/arret" % PORT,
                                     data=b"{}",
                                     headers={"X-Biblio-Arret": "1",
                                              "Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=2).read()
        print("Instance precedente arretee proprement.")
        time.sleep(1.2)
    except Exception:
        pass

    for _ in range(8):
        if not _port_occupe(PORT):
            return True
        pid = _pid_sur_port(PORT)
        if pid and pid != os.getpid() and _est_python(pid):
            print("Port %d is held by process %d: closing it."
                  % (PORT, pid))
            subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                           capture_output=True, timeout=15)
            time.sleep(1.0)
        else:
            time.sleep(0.7)
    return not _port_occupe(PORT)


class Serveur(ThreadingHTTPServer):
    # On garde SO_REUSEADDR : sans lui, la connexion d arret laisse un
    # TIME_WAIT qui empeche de se relier pendant une minute. Le risque de
    # double liaison est ecarte autrement — on ne se lie qu apres avoir
    # verifie que le port est reellement libre (voir demarrer()).
    allow_reuse_address = True
    daemon_threads = True


class Poste(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "Biblio/1.0"

    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        corps = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corps)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corps)

    def _erreur(self, message, code=400):
        self._json({"ok": False, "erreur": message}, code)

    def _fichier(self, chemin, cache=True):
        """Sert un fichier, en honorant les requetes Range (seek video)."""
        if not chemin or not os.path.isfile(chemin):
            return self._erreur("not found", 404)
        taille = os.path.getsize(chemin)
        type_, _ = mimetypes.guess_type(chemin)
        type_ = type_ or "application/octet-stream"
        debut, fin = 0, taille - 1
        partiel = False
        rang = self.headers.get("Range")
        if rang:
            m = re.match(r"bytes=(\d*)-(\d*)", rang.strip())
            if m:
                a, b = m.group(1), m.group(2)
                if a:
                    debut = int(a)
                    fin = int(b) if b else taille - 1
                elif b:
                    debut = max(0, taille - int(b))
                if debut >= taille:
                    self.send_response(416)
                    self.send_header("Content-Range", "bytes */%d" % taille)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                fin = min(fin, taille - 1)
                partiel = True
        longueur = fin - debut + 1
        self.send_response(206 if partiel else 200)
        self.send_header("Content-Type", type_)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(longueur))
        if partiel:
            self.send_header("Content-Range",
                             "bytes %d-%d/%d" % (debut, fin, taille))
        self.send_header("Cache-Control",
                         "public, max-age=3600" if cache else "no-store")
        self.end_headers()
        if self.command == "HEAD":
            return
        with open(chemin, "rb") as f:
            f.seek(debut)
            reste = longueur
            while reste > 0:
                bloc = f.read(min(262144, reste))
                if not bloc:
                    break
                try:
                    self.wfile.write(bloc)
                except Exception:
                    return
                reste -= len(bloc)

    def _corps(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:
            return {}

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        morceaux = urllib.parse.urlparse(self.path)
        req = urllib.parse.parse_qs(morceaux.query)
        chemin = urllib.parse.unquote(posixpath.normpath(morceaux.path))

        if chemin == "/api/rendu":
            return self._json(RENDU)

        if chemin == "/api/vivant":
            VEILLE["signe"] = time.time()
            VEILLE["adieu"] = 0.0
            return self._json({"ok": True})

        # --- l onde d un son, pour la dessiner sur sa piste ---------------
        if chemin == "/api/onde":
            pr = nom_projet((req.get("projet") or [""])[0])
            if not pr:
                return self._erreur("unknown project", 404)
            ident = (req.get("id") or [""])[0]
            f = None
            for x in lire_catalogue(pr).get("films", []):
                if x.get("id") == ident:
                    f = x
                    break
            if not f:
                return self._erreur("unknown entry", 404)
            try:
                # Un ffmpeg a la fois : dix pistes affichees d un coup ne
                # doivent pas lancer dix decodages en parallele.
                with _verrou_onde:
                    return self._json(onde_de(pr, f))
            except Exception as e:
                return self._erreur(str(e) or "waveform unavailable", 502)

        # --- tous les dossiers de la bibliotheque, projets ou non ---------
        if chemin == "/api/dossiers":
            connus = set(projets_disque())
            out = []
            for n in _dossiers(RACINE_PROJETS, liste_blanche=False):
                v, s, im, beaucoup = compter_medias(
                    os.path.join(RACINE_PROJETS, n))
                out.append({"nom": n, "projet": n in connus, "videos": v,
                            "sons": s, "images": im, "beaucoup": beaucoup})
            return self._json({"dossiers": out, "racine": RACINE_PROJETS,
                               "liste_blanche": bool(SEULS)})

        if chemin == "/api/scan_etat":
            return self._json(SCAN)

        if chemin == "/api/import_etat":
            return self._json(IMPORT)

        # Les polices sont a la bibliotheque, pas a un projet : ces routes
        # sont donc traitees avant toute resolution de projet.
        if chemin == "/api/polices":
            return self._json({"polices": polices_lib(),
                               "dossier": POLICES_LIB})

        if chemin in ("/", "/index.html", "/app.html"):
            return self._fichier(APP, cache=False)

        # --- les projets presents sur le disque ---------------------------
        if chemin == "/api/projets":
            out = []
            # les bibliotheques en dernier : l appli garde ainsi le premier
            # projet comme onglet d accueil, et elles tombent en bas de liste
            for n in projets_disque() + biblis_disque():
                vu = catalogue_existe(n)
                cat = lire_catalogue(n) if vu else None
                out.append({
                    "nom": n,
                    "scanne": vu,
                    "clips": (sum(1 for f in cat.get("films", [])
                                  if not f.get("absent")) if cat else 0),
                    # un projet neuf est « scanne » mais vide : on compte
                    # quand meme les fichiers pour pouvoir proposer le scan
                    "fichiers": (None if (vu and cat.get("films"))
                                 else len(fichiers_video(n))),
                })
            VEILLE["signe"] = time.time()
            return self._json({"projets": out, "racine": BASE, "jeton": JETON,
                               "biblis": biblis_disque(),
                               "api": API, "ffmpeg": bool(FFMPEG),
                               "titre": TITRE, "rangement": True,
                               "lecture_seule": LECTURE_SEULE,
                               # sait retirer les fiches manquantes
                               # (/api/purger) : sans ce champ, l application
                               # ne montre pas le bouton.
                               "purge": True,
                               # sait se mettre a jour depuis GitHub
                               # (/api/maj) : sans ce champ, pas de bouton.
                               "maj": bool(MAJ),
                               # sait dessiner l onde d un son (/api/onde) :
                               # sans ce champ, le menu ne la propose pas.
                               "onde": bool(FFMPEG),
                               # sait lister TOUS les dossiers (/api/dossiers)
                               # et en ouvrir un (/api/projet/ajouter).
                               "dossiers": True,
                               "version": version_installee(),
                               "format": REGLAGES.get("format") or None})

        # --- catalogue d un projet ----------------------------------------
        if chemin in ("/api/catalogue", "/api/scan"):
            pr = nom_projet((req.get("projet") or [""])[0])
            if not pr:
                return self._erreur("unknown project", 404)
            with _verrou:
                if chemin == "/api/scan":
                    cat = scanner(pr, bavard=False)
                    fabriquer_posters(pr, budget=25, bavard=False)
                elif catalogue_existe(pr):
                    cat = lire_catalogue(pr)
                else:
                    # Jamais scanne : on ne sonde rien, on annonce le travail.
                    cat = {"maj": None, "films": [], "besoin_scan": True,
                           "a_scanner": len(fichiers_video(pr))}
            cat["projet"] = pr
            cat["dossiers"] = lister_dossiers(pr)
            cat["ffmpeg"] = bool(FFMPEG)
            cat["racine_abs"] = media_de(pr)
            cat["api"] = API
            return self._json(cat)

        # --- montages enregistres dans un projet --------------------------
        # Ou un rush a-t-il servi ? On ouvre tous les montages de tous les
        # projets et on compte les blocs qui portent cet identifiant. Les
        # identifiants sont stables et independants du chemin : un meme rush
        # se retrouve donc meme s il a ete range ailleurs entre-temps.
        # Y a-t-il une version plus recente du programme sur GitHub ?
        if chemin == "/api/maj":
            if not MAJ:
                return self._erreur("this library cannot update itself", 404)
            try:
                r = MAJ.verifier_en_ligne("films", BASE)
            except Exception as e:
                return self._erreur(str(e), 502)
            VEILLE["signe"] = time.time()
            return self._json(dict(r, ok=True))

        if chemin == "/api/usages":
            fid = ((req.get("id") or [""])[0] or "").strip()
            if not re.fullmatch(r"[0-9a-f]{6,32}", fid or ""):
                return self._erreur("invalid id")
            out = []
            for nom in projets_disque() + biblis_disque():
                d = montages_de(nom)
                if not os.path.isdir(d):
                    continue
                for f in sorted(os.listdir(d)):
                    if not f.lower().endswith(".json"):
                        continue
                    c = os.path.join(d, f)
                    try:
                        with open(c, encoding="utf-8") as fh:
                            m = json.load(fh)
                    except Exception:
                        continue
                    k = sum(1 for x in (m.get("clips") or [])
                            if x.get("film") == fid)
                    if k:
                        out.append({"projet": nom, "nom": f[:-5], "blocs": k,
                                    "maj": time.strftime(
                                        "%Y-%m-%d %H:%M",
                                        time.localtime(os.path.getmtime(c)))})
            out.sort(key=lambda x: x["maj"], reverse=True)
            VEILLE["signe"] = time.time()
            return self._json({"ok": True, "id": fid, "usages": out})

        if chemin == "/api/presets":
            g = (req.get("genre") or ["secousse"])[0]
            if fichier_presets(g) is None:
                return self._erreur("invalid preset kind")
            return self._json({"ok": True, "genre": g, "presets": lire_presets(g)})

        if chemin == "/api/rangement":
            pr = nom_projet((req.get("projet") or [""])[0])
            if not pr:
                return self._erreur("unknown project", 404)
            r = lire_rangement(pr)
            return self._json({"ok": True, "projet": pr, "qui": "local",
                               "dossiers": r["dossiers"], "ou": r["ou"]})

        if chemin == "/api/montages":
            pr = nom_projet((req.get("projet") or [""])[0])
            if not pr:
                return self._erreur("unknown project", 404)
            d = montages_de(pr)
            os.makedirs(d, exist_ok=True)
            out = []
            for n in sorted(os.listdir(d)):
                if n.lower().endswith(".json"):
                    c = os.path.join(d, n)
                    out.append({"nom": n[:-5], "projet": pr,
                                "maj": time.strftime("%Y-%m-%d %H:%M",
                                       time.localtime(os.path.getmtime(c))),
                                "octets": os.path.getsize(c)})
            out.sort(key=lambda x: x["maj"], reverse=True)
            return self._json({"montages": out, "projet": pr})

        if chemin == "/api/montage":
            pr = nom_projet((req.get("projet") or [""])[0])
            nom = nom_propre((req.get("nom") or [""])[0])
            if not pr:
                return self._erreur("unknown project", 404)
            f = os.path.join(montages_de(pr), nom + ".json")
            if not nom or not os.path.isfile(f):
                return self._erreur("sequence not found", 404)
            with open(f, encoding="utf-8") as fh:
                return self._json({"ok": True, "nom": nom, "projet": pr,
                                   "montage": json.load(fh)})

        # --- medias : /media/<projet>/<chemin relatif> --------------------
        if chemin.startswith("/media/"):
            pr, _, rel = chemin[len("/media/"):].partition("/")
            pr = nom_projet(urllib.parse.unquote(pr))
            if not pr or not rel:
                return self._erreur("media not found", 404)
            return self._fichier(sur(pr, rel))

        if chemin.startswith("/polices/"):
            plein = police_lib(chemin[len("/polices/"):])
            if not plein:
                return self._erreur("font not found", 404)
            return self._fichier(plein)

        if chemin.startswith("/posters/"):
            pr, _, nom = chemin[len("/posters/"):].partition("/")
            pr = nom_projet(urllib.parse.unquote(pr))
            if not pr or not re.fullmatch(r"[0-9a-f]{6,32}\.jpg", nom):
                return self._erreur("poster not found", 404)
            return self._fichier(os.path.join(posters_de(pr), nom))

        return self._erreur("unknown route", 404)

    def do_POST(self):
        chemin = urllib.parse.urlparse(self.path).path
        d = self._corps()
        # Le selecteur de dossier reste ouvert tant que l on n a pas choisi :
        # on le traite hors du verrou, sinon il bloquerait tout le serveur
        # pendant qu on navigue — enregistrements et scans compris.
        if chemin == "/api/parcourir":
            try:
                return self._agir(chemin, d)
            except Exception as e:
                return self._erreur("%s: %s" % (type(e).__name__, e), 500)
        with _verrou:
            try:
                return self._agir(chemin, d)
            except Exception as e:
                return self._erreur("%s: %s" % (type(e).__name__, e), 500)

    def _agir(self, chemin, d):
        # Verifie ici plutot que dans l interface : un bouton cache se
        # contourne, une route refusee non.
        if LECTURE_SEULE and chemin in ECRIT_DANS_LES_RUSHES:
            return self._erreur(
                "this library never modifies the rushes folders — "
                "organise them with My folders instead", 403)
        # Installer la version publiee sur GitHub : le programme seulement,
        # chaque fichier sauvegarde avant d etre remplace. Il prend effet au
        # prochain lancement de la bibliotheque.
        if chemin == "/api/maj":
            if not MAJ:
                return self._erreur("this library cannot update itself", 404)
            try:
                r = MAJ.appliquer_en_ligne("films", BASE)
            except Exception as e:
                return self._erreur(str(e), 502)
            return self._json(dict(r, ok=True))

        if chemin == "/api/arret":
            if self.headers.get("X-Biblio-Arret") != "1":
                return self._erreur("en-tete d arret manquante", 403)
            self._json({"ok": True})
            threading.Thread(target=lambda: (time.sleep(0.3), os._exit(0)),
                             daemon=True).start()
            return

        # Creer un projet : un dossier vide a la racine. Les rushes, c est
        # l Explorateur qui les y met ; un scan les decouvre ensuite.
        if chemin == "/api/parcourir":
            if d.get("jeton") != JETON:
                return self._erreur("invalid token", 403)
            c = choisir_dossier((d.get("depart") or "").strip())
            if c is None:
                return self._erreur("no folder picker on this "
                                    "machine — type the path by hand", 501)
            return self._json({"ok": True, "chemin": c})

        if chemin == "/api/adieu":
            # Envoye par sendBeacon a la fermeture de l onglet. On ne sort pas
            # tout de suite : un rechargement produit le meme evenement, et sa
            # nouvelle page va rebattre la mesure dans la seconde.
            if d.get("jeton") != JETON:
                return self._erreur("invalid token", 403)
            VEILLE["adieu"] = time.time()
            return self._json({"ok": True, "dans": GRACE_ADIEU})

        if chemin == "/api/police":
            nom = os.path.basename(str(d.get("nom") or "").replace("\\", "/"))
            base, ext = os.path.splitext(nom)
            ext = ext.lower()
            base = nom_propre(base)
            if not base or ext not in EXT_POLICE:
                return self._erreur("font must be .ttf, .otf, .ttc, .woff "
                                    "or .woff2", 400)
            brut = d.get("donnees") or ""
            try:
                octets = base64.b64decode(brut, validate=True)
            except Exception:
                return self._erreur("unreadable font file", 400)
            if not octets:
                return self._erreur("empty font file", 400)
            if len(octets) > MAX_POLICE:
                return self._erreur("font too large (max %d MB)"
                                    % (MAX_POLICE // (1024 * 1024)), 400)
            os.makedirs(POLICES_LIB, exist_ok=True)
            # On n ecrase jamais : un homonyme devient « nom-2 », « nom-3 ».
            feuille, i = base + ext, 2
            while os.path.exists(os.path.join(POLICES_LIB, feuille)):
                feuille = "%s-%d%s" % (base, i, ext)
                i += 1
            with open(os.path.join(POLICES_LIB, feuille), "wb") as fh:
                fh.write(octets)
            return self._json({"ok": True, "nom": feuille,
                               "octets": len(octets),
                               "rendu": ext in EXT_POLICE_RENDU,
                               "polices": polices_lib()})

        if chemin == "/api/projet/creer":
            nom = nom_projet(d.get("nom"), doit_exister=False)
            if not nom:
                return self._erreur("invalid project name")
            plein = os.path.join(RACINE_PROJETS, nom)
            if os.path.exists(plein):
                return self._erreur("this project already exists", 409)
            os.makedirs(plein)
            os.makedirs(os.path.join(data_de(nom), "_posters"), exist_ok=True)
            os.makedirs(os.path.join(data_de(nom), "_montages"), exist_ok=True)
            # Une liste blanche qui ignorerait le projet qu on vient de creer
            # le ferait disparaitre aussitot : on l y inscrit.
            if SEULS and nom not in SEULS:
                SEULS.append(nom)
                REGLAGES["projets"] = SEULS
                try:
                    with io.open(FICHIER_REGLAGES, "w", encoding="utf-8") as fr:
                        json.dump(REGLAGES, fr, ensure_ascii=False, indent=1)
                except Exception:
                    pass
            ecrire_catalogue(nom, {"maj": None, "films": [], "racine": nom})
            return self._json({"ok": True, "nom": nom, "chemin": plein,
                               "projets": projets_disque()})

        if chemin == "/api/projet/ajouter":
            # Un dossier qui existe deja dans la bibliotheque devient un
            # projet : rien n est cree, rien n est deplace, on l inscrit.
            nom = nom_projet(d.get("nom"), doit_exister=False)
            if not nom or not os.path.isdir(os.path.join(RACINE_PROJETS, nom)):
                return self._erreur("unknown folder", 404)
            neuf = inscrire_projet(nom)
            # Pas de catalogue vide : le dossier reste « jamais scanne », et
            # l application propose son scan comme pour tout projet neuf.
            return self._json({"ok": True, "nom": nom, "ajoute": neuf,
                               "chemin": media_de(nom),
                               "projets": projets_disque()})

        if chemin == "/api/presets":
            g = d.get("genre") or "secousse"
            if fichier_presets(g) is None:
                return self._erreur("invalid preset kind")
            l = lire_presets(g)
            # Remplacement en bloc : sert a la reprise unique des prereglages
            # qui dormaient dans le navigateur. Il n ecrase jamais un fichier
            # deja rempli.
            if isinstance(d.get("presets"), dict):
                if l:
                    return self._json({"ok": True, "genre": g, "presets": l,
                                       "reprise": False})
                l = {nom_preset(k): v for k, v in d["presets"].items()
                     if nom_preset(k)}
                ecrire_presets(g, l)
                return self._json({"ok": True, "genre": g, "presets": l,
                                   "reprise": True})
            nom = nom_preset(d.get("nom"))
            if not nom:
                return self._erreur("name the preset")
            if d.get("effacer"):
                if nom not in l:
                    return self._erreur("no such preset", 404)
                del l[nom]
            else:
                if nom not in l and len(l) >= MAX_PRESETS:
                    return self._erreur("too many presets (%d)" % MAX_PRESETS)
                l[nom] = d.get("valeur")
            ecrire_presets(g, l)
            return self._json({"ok": True, "genre": g, "presets": l})

        pr = nom_projet(d.get("projet"))
        if not pr:
            return self._erreur("unknown project: %s" % (d.get("projet") or ""),
                                404)
        cat = lire_catalogue(pr)
        index = {f["id"]: f for f in cat.get("films", [])}

        # Retirer les fiches dont le fichier a disparu. N ecrit que dans les
        # donnees de la bibliotheque, jamais dans un dossier de rushes : la
        # route reste donc permise en lecture seule.
        if chemin == "/api/purger":
            try:
                return self._json(purger_absents(pr))
            except ValueError as e:
                return self._erreur(str(e), 409)

        if chemin == "/api/rangement":
            r = rangement_propre(d)
            try:
                ecrire_rangement(pr, r)
            except Exception as e:
                return self._erreur("could not save the arrangement: %s" % e,
                                    500)
            return self._json({"ok": True, "projet": pr, "qui": "local",
                               "dossiers": r["dossiers"], "ou": r["ou"]})

        if chemin == "/api/renommer":
            f = index.get(d.get("id"))
            if not f:
                return self._erreur("unknown entry", 404)
            neuf = nom_propre(d.get("nom"))
            if not neuf:
                return self._erreur("empty name")
            if neuf == f["nom"]:
                return self._json({"ok": True, "film": f})
            src = sur(pr, f["rel"])
            rel_neuf = (posixpath.join(f["dossier"], neuf + f["ext"])
                        if f["dossier"] else neuf + f["ext"])
            dst = sur(pr, rel_neuf)
            if not src or not dst or not os.path.isfile(src):
                return self._erreur("source file not found", 404)
            if os.path.exists(dst):
                return self._erreur("a file already has this name", 409)
            os.rename(src, dst)
            noter(pr, "renommer", id=f["id"], avant=f["rel"], apres=rel_neuf)
            f["nom"], f["rel"] = neuf, rel_neuf
            ecrire_catalogue(pr, cat)
            return self._json({"ok": True, "film": f})

        if chemin == "/api/deplacer":
            cible = (d.get("dossier") or "").replace("\\", "/").strip("/")
            dossier_abs = sur(pr, cible)
            if dossier_abs is None:
                return self._erreur("invalid folder")
            if not os.path.isdir(dossier_abs):
                return self._erreur("folder does not exist", 404)
            faits, refus = [], []
            for fid in d.get("ids", []):
                f = index.get(fid)
                if not f or f.get("absent") or f["dossier"] == cible:
                    continue
                src = sur(pr, f["rel"])
                rel_neuf = (posixpath.join(cible, f["nom"] + f["ext"])
                            if cible else f["nom"] + f["ext"])
                dst = sur(pr, rel_neuf)
                if not src or not os.path.isfile(src):
                    refus.append({"nom": f["nom"], "cause": "source not found"})
                    continue
                if os.path.exists(dst):
                    refus.append({"nom": f["nom"],
                                  "cause": "name already taken at the destination"})
                    continue
                shutil.move(src, dst)
                noter(pr, "deplacer", id=f["id"], avant=f["rel"], apres=rel_neuf)
                f["dossier"], f["rel"] = cible, rel_neuf
                faits.append(f["id"])
            ecrire_catalogue(pr, cat)
            return self._json({"ok": True, "deplaces": faits, "refus": refus,
                               "films": cat["films"]})

        if chemin == "/api/importer":
            # Recopier des rushes d un autre projet dans celui-ci. Sert quand
            # on ferme un projet dont le montage en cours se sert : le montage
            # devient autonome, le projet d accueil contient tout son materiel.
            src_pr = nom_projet(d.get("source"))
            if not src_pr:
                return self._erreur("unknown source project", 404)
            if src_pr == pr:
                return self._erreur("source and destination are the same", 400)
            sous = nom_propre(d.get("dossier") or ("importés-de-" + src_pr))
            if not sous:
                return self._erreur("invalid destination folder")
            arrivee = sur(pr, sous)
            if arrivee is None:
                return self._erreur("invalid destination folder")
            os.makedirs(arrivee, exist_ok=True)
            idx_src = {f["id"]: f
                       for f in lire_catalogue(src_pr).get("films", [])}
            pris = set(f["rel"] for f in cat.get("films", []))
            ids = [x for x in (d.get("ids") or [])][:500]
            IMPORT.update({"etat": "encours", "fait": 0, "total": len(ids),
                           "nom": ""})
            corresp, importes, refus = {}, [], []
            for fid in ids:
                f = idx_src.get(fid)
                if not f or f.get("absent"):
                    refus.append({"nom": str(fid), "cause": "unknown entry"})
                    IMPORT["fait"] += 1
                    continue
                source = sur(src_pr, f["rel"])
                if not source or not os.path.isfile(source):
                    refus.append({"nom": f.get("nom", fid),
                                  "cause": "source not found"})
                    IMPORT["fait"] += 1
                    continue
                IMPORT["nom"] = f.get("nom", "")
                base, ext = f["nom"], f.get("ext", "")
                nom, k = base, 1
                while True:
                    rel = posixpath.join(sous, nom + ext)
                    cible = sur(pr, rel)
                    if cible and not os.path.exists(cible) and rel not in pris:
                        break
                    k += 1
                    nom = "%s-%d" % (base, k)
                    if k > 99:
                        cible = None
                        break
                if not cible:
                    refus.append({"nom": base, "cause": "name cannot be placed"})
                    IMPORT["fait"] += 1
                    continue
                try:
                    shutil.copy2(source, cible)
                except Exception as e:
                    refus.append({"nom": base, "cause": "copie refusee (%s)"
                                  % type(e).__name__})
                    IMPORT["fait"] += 1
                    continue
                fiche = dict(f)
                fiche["id"] = uuid.uuid4().hex[:12]
                fiche["nom"], fiche["dossier"], fiche["rel"] = nom, sous, rel
                fiche["absent"] = False
                fiche["venu_de"] = src_pr + "/" + f["rel"]
                cat.setdefault("films", []).append(fiche)
                pris.add(rel)
                # meme image, nouvel identifiant : on recopie le poster plutot
                # que de refaire tourner ffmpeg pour rien
                vieux_poster = poster_de(src_pr, f)
                if os.path.isfile(vieux_poster):
                    os.makedirs(posters_de(pr), exist_ok=True)
                    try:
                        shutil.copy2(vieux_poster, poster_de(pr, fiche))
                    except Exception:
                        pass
                noter(pr, "importer", id=fiche["id"], source=src_pr,
                      avant=f["rel"], apres=rel)
                corresp[fid] = fiche["id"]
                importes.append(fiche)
                IMPORT["fait"] += 1
            ecrire_catalogue(pr, cat)
            IMPORT.update({"etat": "fini", "nom": ""})
            return self._json({"ok": True, "corresp": corresp,
                               "importes": importes, "refus": refus,
                               "dossier": sous, "films": cat["films"],
                               "dossiers": lister_dossiers(pr)})

        if chemin == "/api/dossier/creer":
            nom = nom_propre(d.get("nom"))
            if not nom:
                return self._erreur("empty name")
            parent = (d.get("parent") or "").replace("\\", "/").strip("/")
            rel = posixpath.join(parent, nom) if parent else nom
            plein = sur(pr, rel)
            if plein is None:
                return self._erreur("invalid path")
            if os.path.exists(plein):
                return self._erreur("this folder already exists", 409)
            os.makedirs(plein)
            noter(pr, "dossier-creer", apres=rel)
            return self._json({"ok": True, "dossiers": lister_dossiers(pr)})

        if chemin == "/api/dossier/renommer":
            ancien = (d.get("ancien") or "").replace("\\", "/").strip("/")
            neuf = nom_propre(d.get("nom"))
            if not ancien or not neuf:
                return self._erreur("empty name")
            src = sur(pr, ancien)
            parent = posixpath.dirname(ancien)
            rel_neuf = posixpath.join(parent, neuf) if parent else neuf
            dst = sur(pr, rel_neuf)
            if not src or not os.path.isdir(src):
                return self._erreur("folder not found", 404)
            if dst is None:
                return self._erreur("invalid path")
            if os.path.exists(dst):
                return self._erreur("a folder already has this name", 409)
            os.rename(src, dst)
            noter(pr, "dossier-renommer", avant=ancien, apres=rel_neuf)
            for f in cat.get("films", []):
                if f["dossier"] == ancien or f["dossier"].startswith(ancien + "/"):
                    f["dossier"] = rel_neuf + f["dossier"][len(ancien):]
                    f["rel"] = posixpath.join(f["dossier"], f["nom"] + f["ext"])
            ecrire_catalogue(pr, cat)
            return self._json({"ok": True, "films": cat["films"],
                               "dossiers": lister_dossiers(pr)})

        if chemin == "/api/montage/renommer":
            ancien = nom_propre(d.get("ancien"))
            neuf = nom_propre(d.get("nom"))
            if not ancien or not neuf:
                return self._erreur("empty name")
            src = os.path.join(montages_de(pr), ancien + ".json")
            dst = os.path.join(montages_de(pr), neuf + ".json")
            if not os.path.isfile(src):
                return self._erreur("sequence not found", 404)
            if ancien != neuf and os.path.exists(dst):
                return self._erreur("a sequence already has this name", 409)
            if ancien != neuf:
                os.rename(src, dst)
                noter(pr, "montage-renommer", avant=ancien, apres=neuf)
            return self._json({"ok": True, "nom": neuf})

        if chemin == "/api/montage/effacer":
            # Comme pour les dossiers : rien ne disparait, tout part dans une
            # corbeille que l on vide a la main.
            nom = nom_propre(d.get("nom"))
            src = os.path.join(montages_de(pr), nom + ".json")
            if not nom or not os.path.isfile(src):
                return self._erreur("sequence not found", 404)
            bac = os.path.join(montages_de(pr), CORBEILLE)
            os.makedirs(bac, exist_ok=True)
            feuille, k = nom, 1
            while os.path.exists(os.path.join(bac, feuille + ".json")):
                k += 1
                feuille = "%s-%d" % (nom, k)
            shutil.move(src, os.path.join(bac, feuille + ".json"))
            noter(pr, "montage-corbeille", avant=nom, apres=feuille)
            return self._json({"ok": True, "nom": nom,
                               "vers": "_montages/%s/%s.json" % (CORBEILLE, feuille)})

        if chemin == "/api/dossier/effacer":
            # Deux cas, et jamais de perte. Un dossier sans aucun fichier est
            # reellement retire. Un dossier qui contient quelque chose part
            # dans <projet>/_corbeille/ : il disparait de la bibliotheque, ses
            # fiches passent en « absent », et /api/annuler le ramene.
            rel = (d.get("dossier") or "").replace("\\", "/").strip("/")
            src = sur(pr, rel)
            if not rel or src is None:
                return self._erreur("invalid folder")
            if src == os.path.normpath(media_de(pr)):
                return self._erreur("the project root cannot be deleted",
                                    400)
            if not os.path.isdir(src):
                return self._erreur("folder not found", 404)

            n = compter_fichiers(src)
            if n == 0:
                # Un dossier sans aucun fichier peut vraiment partir. Si le
                # systeme refuse la suppression (disque en lecture seule, droits
                # restreints), on ne renvoie pas une erreur : on le met a la
                # corbeille comme les autres.
                try:
                    shutil.rmtree(src)
                except OSError as e:
                    n = -1
                    raison = "%s: %s" % (type(e).__name__, e)
                else:
                    noter(pr, "dossier-vide-efface", avant=rel)
                    return self._json({"ok": True, "mode": "efface",
                                       "dossier": rel, "fichiers": 0,
                                       "films": cat.get("films", []),
                                       "dossiers": lister_dossiers(pr)})

            bac = sous_projet(pr, CORBEILLE)
            os.makedirs(bac, exist_ok=True)
            feuille = posixpath.basename(rel)
            nom, k = feuille, 1
            while os.path.exists(os.path.join(bac, nom)):
                k += 1
                nom = "%s-%d" % (feuille, k)
            dst_rel = CORBEILLE + "/" + nom
            shutil.move(src, os.path.join(bac, nom))
            noter(pr, "dossier-corbeille", avant=rel, apres=dst_rel)
            touches = 0
            for f in cat.get("films", []):
                if f["dossier"] == rel or f["dossier"].startswith(rel + "/"):
                    f["absent"] = True
                    touches += 1
            ecrire_catalogue(pr, cat)
            return self._json({"ok": True, "mode": "corbeille", "dossier": rel,
                               "vers": dst_rel, "fichiers": max(0, n),
                               "clips": touches, "films": cat["films"],
                               "dossiers": lister_dossiers(pr),
                               "repli": (raison if n == -1 else "")})

        if chemin == "/api/marquer":
            f = index.get(d.get("id"))
            if not f:
                return self._erreur("unknown entry", 404)
            for cle in ("fav", "coul", "note"):
                if cle in d:
                    f[cle] = d[cle]
            ecrire_catalogue(pr, cat)
            return self._json({"ok": True, "film": f})

        if chemin == "/api/poster":
            f = index.get(d.get("id"))
            if not f:
                return self._erreur("unknown entry", 404)
            data = d.get("data") or ""
            if "," in data:
                data = data.split(",", 1)[1]
            try:
                brut = base64.b64decode(data)
            except Exception:
                return self._erreur("image illisible")
            if len(brut) < 500 or len(brut) > 4000000:
                return self._erreur("invalid image size")
            os.makedirs(posters_de(pr), exist_ok=True)
            with open(poster_de(pr, f), "wb") as fh:
                fh.write(brut)
            return self._json({"ok": True})

        if chemin == "/api/montage":
            nom = nom_propre(d.get("nom") or "montage") or "montage"
            dossier = montages_de(pr)
            os.makedirs(dossier, exist_ok=True)
            with open(os.path.join(dossier, nom + ".json"), "w",
                      encoding="utf-8") as fh:
                json.dump(d.get("montage") or {}, fh, ensure_ascii=False, indent=1)
            return self._json({"ok": True, "nom": nom})

        if chemin == "/api/rendre":
            if RENDU.get("etat") == "encours":
                return self._erreur("a render is already running", 409)
            m = d.get("montage") or {}
            nom = nom_propre(d.get("nom") or "sequence") or "sequence"
            if not m.get("plans"):
                return self._erreur("empty sequence", 400)
            mode = (d.get("type") or "mp4").lower()
            if mode not in EXT_MODE:
                return self._erreur("unknown render type: %s" % mode, 400)
            try:
                cible = _destination(pr, nom, d.get("sortie"), mode)
            except ValueError as e:
                return self._erreur(str(e), 400)
            threading.Thread(target=rendre, args=(m, nom, pr, cible, mode),
                             daemon=True).start()
            return self._json({"ok": True, "lance": True, "fichier": cible,
                               "type": mode})

        if chemin == "/api/texte":
            nom = nom_propre(d.get("nom") or "export")
            ext = (d.get("ext") or "txt").lower().lstrip(".")
            if ext not in ("json", "xml", "txt", "edl", "fcpxml"):
                return self._erreur("extension not allowed", 400)
            contenu = d.get("contenu") or ""
            if not isinstance(contenu, str) or len(contenu) > 8000000:
                return self._erreur("invalid content", 400)
            dossier = montages_de(pr)
            os.makedirs(dossier, exist_ok=True)
            cible = os.path.join(dossier, nom + "." + ext)
            with open(cible, "w", encoding="utf-8") as fh:
                fh.write(contenu)
            return self._json({"ok": True, "fichier": cible})

        if chemin == "/api/annuler":
            entree, restantes = journal_dernier(pr)
            if not entree:
                return self._erreur("nothing to undo", 404)
            op = entree.get("op")
            if op in ("renommer", "deplacer"):
                src, dst = (sur(pr, entree["apres"]),
                            sur(pr, entree["avant"]))
                if not src or not dst or not os.path.isfile(src):
                    return self._erreur("the file has moved since", 409)
                if os.path.exists(dst):
                    return self._erreur("the original place is occupied", 409)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.move(src, dst)
            elif op == "dossier-renommer":
                src, dst = (sur(pr, entree["apres"]),
                            sur(pr, entree["avant"]))
                if not src or not os.path.isdir(src) or os.path.exists(dst):
                    return self._erreur("cannot go back", 409)
                os.rename(src, dst)
            elif op == "montage-renommer":
                src = os.path.join(montages_de(pr), entree["apres"] + ".json")
                dst = os.path.join(montages_de(pr), entree["avant"] + ".json")
                if not os.path.isfile(src):
                    return self._erreur("the sequence has moved since", 409)
                if os.path.exists(dst):
                    return self._erreur("the original name is taken again", 409)
                os.rename(src, dst)
            elif op == "montage-corbeille":
                src = os.path.join(montages_de(pr), CORBEILLE,
                                   entree["apres"] + ".json")
                dst = os.path.join(montages_de(pr), entree["avant"] + ".json")
                if not os.path.isfile(src):
                    return self._erreur("the sequence has moved since", 409)
                if os.path.exists(dst):
                    return self._erreur("the original name is taken again", 409)
                shutil.move(src, dst)
            elif op == "dossier-corbeille":
                src = sous_projet(pr, entree["apres"])
                dst = sur(pr, entree["avant"])
                if not src or not os.path.isdir(src) or not dst:
                    return self._erreur("the folder has moved since", 409)
                if os.path.exists(dst):
                    return self._erreur("the original place is occupied", 409)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.move(src, dst)
            elif op == "dossier-vide-efface":
                plein = sur(pr, entree["avant"])
                if not plein:
                    return self._erreur("invalid path", 400)
                if os.path.exists(plein):
                    return self._erreur("this folder exists again", 409)
                os.makedirs(plein)
            elif op == "dossier-creer":
                plein = sur(pr, entree["apres"])
                if plein and os.path.isdir(plein) and not os.listdir(plein):
                    os.rmdir(plein)
                else:
                    return self._erreur("the folder is not empty", 409)
            else:
                return self._erreur("operation non annulable", 400)
            journal_retirer(pr, restantes)
            cat = scanner(pr, bavard=False)
            cat["dossiers"] = lister_dossiers(pr)
            cat["ok"] = True
            cat["annule"] = entree
            return self._json(cat)

        return self._erreur("unknown route", 404)


def migrer_vers_projets():
    """Reprend les donnees de l epoque ou la bibliotheque ne connaissait qu un
    seul dossier de rushes, et les installe dans GARY-ALL/_projet/.

    On copie, on ne supprime rien : l ancien emplacement reste sur le disque,
    simplement ignore. Les identifiants, favoris et couleurs sont donc repris
    tels quels, et rien n est perdu si la migration tourne mal."""
    if not os.path.isdir(media_de(VIEUX_PROJET)):
        return
    if catalogue_existe(VIEUX_PROJET) or not os.path.isfile(VIEUX_CATALOGUE):
        return
    os.makedirs(posters_de(VIEUX_PROJET), exist_ok=True)
    os.makedirs(montages_de(VIEUX_PROJET), exist_ok=True)
    comptes = {"posters": 0, "montages": 0}
    for cle, src, dst in (("posters", VIEUX_POSTERS, posters_de(VIEUX_PROJET)),
                          ("montages", VIEUX_MONTAGES,
                           montages_de(VIEUX_PROJET))):
        if not os.path.isdir(src):
            continue
        for n in sorted(os.listdir(src)):
            a, b = os.path.join(src, n), os.path.join(dst, n)
            if os.path.isdir(a) or os.path.exists(b):
                continue
            # on ne reprend que les donnees : les rendus mp4 d essai restent
            # ou ils sont, ils ne valent pas une copie sur un disque reseau
            if cle == "montages" and not n.lower().endswith(".json"):
                continue
            try:
                shutil.copy2(a, b)
                comptes[cle] += 1
            except Exception:
                pass
    if os.path.isfile(VIEUX_JOURNAL) and not os.path.isfile(
            journal_de(VIEUX_PROJET)):
        try:
            shutil.copy2(VIEUX_JOURNAL, journal_de(VIEUX_PROJET))
        except Exception:
            pass
    # le catalogue en dernier : sa presence est le drapeau « deja migre »
    shutil.copy2(VIEUX_CATALOGUE, catalogue_de(VIEUX_PROJET))
    cat = lire_catalogue(VIEUX_PROJET)
    print("MIGRATION vers %s/%s : %d fiches, %d posters, %d montages"
          % (VIEUX_PROJET, DATA, len(cat.get("films", [])),
             comptes["posters"], comptes["montages"]), flush=True)


def veiller():
    """Sort quand plus personne ne regarde. Un rendu en cours suspend tout :
    on ne coupe jamais un encodage en route."""
    while True:
        time.sleep(1.0)
        if RENDU.get("etat") == "encours" or SCAN.get("etat") == "encours":
            continue
        t, signe, adieu = time.time(), VEILLE["signe"], VEILLE["adieu"]
        if signe is None:
            continue
        raison = None
        if adieu and t - adieu > GRACE_ADIEU and t - signe > GRACE_ADIEU - 1:
            raison = "tab closed"
        elif t - signe > GRACE_SILENCE:
            raison = "no page for %d s" % GRACE_SILENCE
        if raison:
            print("")
            print("  Automatic shutdown: %s." % raison)
            print("  Run LANCER.bat again whenever you like.")
            sys.stdout.flush()
            time.sleep(0.3)
            os._exit(0)


def demarrer():
    projets = projets_disque()
    if not projets:
        print("No project found in: %s" % RACINE_PROJETS)
        print("Expected layout next to serveur.py's folder:")
        print("  <root>/_app/  <root>/projets/  <root>/bibliotheques/")
        input("Enter to close...")
        return
    migrer_vers_projets()
    arreter_precedent()
    if _port_occupe(PORT):
        print("")
        print("  Port %d is still held by another program." % PORT)
        print("  A serveur.py window is probably still open:")
        print("  close it, then run LANCER.bat again.")
        print("")
        input("Enter to close...")
        return
    srv = None
    for essai in range(10):
        try:
            srv = Serveur(("127.0.0.1", PORT), Poste)
            break
        except OSError:
            if essai == 0:
                print("Port %d is freeing up, waiting..." % PORT)
            time.sleep(0.8)
    if srv is None:
        print("")
        print("  Could not open port %d after several tries." % PORT)
        print("  Restart the computer or change PORT at the top of serveur.py.")
        print("")
        input("Enter to close...")
        return
    url = "http://127.0.0.1:%d/" % PORT
    print("=" * 58)
    print("  Library open at  %s" % url)
    print("  Root : %s" % BASE)
    print("  Projects : %s" % ", ".join(projets))
    _b = biblis_disque()
    if _b:
        print("  Libraries : %s" % ", ".join(_b))
    print("  ffmpeg : %s" % ("oui" if FFMPEG else "no (posters made by the browser)"))
    print("  Quits by itself when you close the tab.")
    print("=" * 58)
    threading.Thread(target=veiller, daemon=True).start()
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    budget = None
    if "--budget" in sys.argv:
        try:
            budget = float(sys.argv[sys.argv.index("--budget") + 1])
        except Exception:
            budget = None
    cibles = [a for a in sys.argv[1:] if not a.startswith("-")]
    if "--scan" in sys.argv:
        for p in (cibles or projets_disque()):
            if nom_projet(p):
                scanner(p)
    if "--posters" in sys.argv:
        for p in (cibles or projets_disque()):
            if nom_projet(p):
                fabriquer_posters(p, budget=budget)
    if "--purger" in sys.argv:
        for p in (cibles or projets_disque()):
            if nom_projet(p):
                try:
                    r = purger_absents(p)
                    print("PURGE %s : %d retirees, %d gardees (sequences), "
                          "%d revenues" % (p, r["retires"], len(r["gardes"]),
                                           r["revenus"]), flush=True)
                except ValueError as e:
                    print("PURGE %s refusee : %s" % (p, e), flush=True)
    if not ("--scan" in sys.argv or "--posters" in sys.argv
            or "--purger" in sys.argv):
        demarrer()

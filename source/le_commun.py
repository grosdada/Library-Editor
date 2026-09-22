# -*- coding: utf-8 -*-
"""Ce que partagent les trois modules : ressources embarquees, empreintes,
ports, raccourcis, lanceurs, taches de fond, reglages de l application.

Aucun mot de passe n est jamais demande, recu, ecrit ni stocke ici.
"""
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import traceback
import uuid

VERSION = "1.1.1"
DEPOT_GITHUB = "https://github.com/grosdada/Library-Editor"
NOM = "Library Editor"
GELE = bool(getattr(sys, "frozen", False))
ICI = os.path.dirname(os.path.abspath(__file__))
PROJET = os.path.dirname(ICI)                    # hors gel : le dossier du projet
RESSOURCES = getattr(sys, "_MEIPASS", ICI)       # gele : _internal

# Fichiers de l application, par utilisateur : jamais dans une bibliotheque.
APPDATA = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"),
                       NOM)
LOCAL = os.path.join(os.environ.get("LOCALAPPDATA") or APPDATA, NOM)
REGLAGES = os.path.join(APPDATA, "reglages.json")
JOURNAL = os.path.join(LOCAL, "journal.txt")

# Les ports deja pris chez David (brief, invariant 7), et les plages que
# les bibliotheques d images et la bibliotheque generale utilisent : un
# port de bibliotheque video n y tombe jamais.
PORTS_RESERVES = {8779, 8780}
PLAGE_FILMS = (8781, 8880)

EXT_VIDEO = (".mp4", ".mov", ".m4v", ".webm")
EXT_AUDIO = (".wav", ".m4a", ".mp3", ".aac", ".flac", ".ogg", ".aif", ".aiff")
EXT_IMAGE = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif",
             ".tiff", ".avif")
# Des videos que le scan ne liste pas du tout (piege 2 du brief).
EXT_VIDEO_IGNOREES = (".mkv", ".avi", ".mxf", ".mts", ".m2ts", ".wmv", ".flv",
                      ".mpg", ".mpeg", ".3gp", ".ts", ".vob", ".dv", ".r3d",
                      ".braw", ".ogv")

NOM_LANCEUR = "LANCER-LA-BIBLIOTHEQUE.bat"


# ---------------------------------------------------------------------------
#  Journal
# ---------------------------------------------------------------------------
def journal(*morceaux):
    ligne = time.strftime("%Y-%m-%d %H:%M:%S ") + " ".join(str(m) for m in morceaux)
    try:
        os.makedirs(LOCAL, exist_ok=True)
        with io.open(JOURNAL, "a", encoding="utf-8") as f:
            f.write(ligne + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
#  Ressources embarquees
# ---------------------------------------------------------------------------
def ressource(*parts):
    return os.path.join(RESSOURCES, *parts)


def depot(chemin):
    """Un fichier du depot GitHub, par son chemin DANS le depot
    (« template/_app/serveur.py », « modeles/images/_scan.py »...). Hors gel,
    le dossier du projet EST le depot ; gele, l application en embarque une
    copie sous _internal/depot. Les memes chemins que version.json : ce que
    Library Editor installe et ce que les bibliotheques telechargent ne
    peuvent pas diverger."""
    parts = chemin.split("/")
    if GELE:
        return ressource("depot", *parts)
    return os.path.join(PROJET, *parts)


def modele_films(nom):
    """Le modele video. serveur.py et app.html viennent TOUJOURS de
    template/_app : une seule source, celle que les essais eprouvent."""
    if nom in ("serveur.py", "app.html"):
        return depot("template/_app/" + nom)
    return depot("modeles/films/" + nom)


def modele_images(nom):
    return depot("modeles/images/" + nom)


def modele_racine(chemin):
    return depot("modeles/racine/" + chemin)


def modele_enligne(*parts):
    return depot("/".join(("modeles", "enligne") + parts))


def lanceur_exe():
    """Le petit .exe a icone qui lance le .bat du meme nom."""
    return depot("modeles/lanceur/lanceur.exe")


def maj_py():
    return depot("modeles/commun/_maj.py")


def interface(nom):
    if GELE:
        return ressource("ui", nom)
    return os.path.join(ICI, "ui", nom)


def moteur_source():
    """Le moteur Python a deposer dans une bibliotheque, ou None."""
    d = (ressource("moteur", "python") if GELE
         else os.path.join(PROJET, "build", "moteur", "python"))
    return d if os.path.isfile(os.path.join(d, "python.exe")) else None


# ---------------------------------------------------------------------------
#  Lecture, ecriture
# ---------------------------------------------------------------------------
def lire_json(chemin, defaut=None):
    try:
        with io.open(chemin, encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return defaut


def ecrire_json(chemin, valeur, indent=1):
    """Ecriture atomique : jamais un fichier a moitie ecrit."""
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    tmp = chemin + "." + uuid.uuid4().hex[:6] + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as f:
        json.dump(valeur, f, ensure_ascii=False, indent=indent)
    os.replace(tmp, chemin)


def ecrire_texte(chemin, texte, crlf=False):
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    with io.open(chemin, "w", encoding="utf-8",
                 newline="\r\n" if crlf else "\n") as f:
        f.write(texte)


def sauvegarder(chemin, motif):
    """fichier -> fichier.avant-<motif>, sans jamais ecraser une sauvegarde
    existante (methode de David : sauvegarde avant chaque modification)."""
    if not os.path.isfile(chemin):
        return None
    cible = "%s.avant-%s" % (chemin, motif)
    n = 2
    while os.path.exists(cible):
        cible = "%s.avant-%s-%d" % (chemin, motif, n)
        n += 1
    shutil.copy2(chemin, cible)
    return cible


def taille_humaine(octets):
    o = float(octets or 0)
    for unite in ("octets", "Ko", "Mo", "Go", "To"):
        if o < 1024 or unite == "To":
            if unite == "octets":
                return "%d octets" % o
            return ("%.2f %s" % (o, unite)).replace(".", ",")
        o /= 1024.0


def copier_arbre(source, destination, progression=None):
    """Copie un dossier (le moteur, ~400 fichiers) en rendant compte."""
    fichiers = []
    for rep, _, noms in os.walk(source):
        for n in noms:
            fichiers.append(os.path.join(rep, n))
    for i, a in enumerate(fichiers):
        b = os.path.join(destination, os.path.relpath(a, source))
        os.makedirs(os.path.dirname(b), exist_ok=True)
        shutil.copy2(a, b)
        if progression and (i % 20 == 0 or i == len(fichiers) - 1):
            progression(i + 1, len(fichiers))
    return len(fichiers)


# ---------------------------------------------------------------------------
#  Empreinte : la preuve qu on n a rien touche
# ---------------------------------------------------------------------------
def empreinte(dossier, exclure=(), annule=None, progres=None):
    """(nom relatif, taille, date) de chaque entree, comme dans
    tests/serveur_essais.py. `exclure` : noms de premier niveau ignores (ce
    que l installation ajoute, et seulement cela)."""
    exclure = {e.lower() for e in exclure}
    out = []
    for rep, sous, fics in os.walk(dossier):
        if rep == dossier:
            sous[:] = [s for s in sous if s.lower() not in exclure]
            fics = [f for f in fics if f.lower() not in exclure]
        for n in sous + fics:
            p = os.path.join(rep, n)
            try:
                st = os.stat(p)
            except OSError:
                continue
            out.append("%s|%d|%.6f" % (os.path.relpath(p, dossier),
                                       st.st_size if n in fics else 0,
                                       st.st_mtime))
            if progres and len(out) % 200 == 0:
                progres(len(out))
        if annule and annule():
            break
    return sorted(out)


def comparer(avant, apres):
    a, b = set(avant), set(apres)
    return {"identiques": a == b, "entrees": len(apres),
            "disparues": sorted(a - b)[:20], "nouvelles": sorted(b - a)[:20]}


# ---------------------------------------------------------------------------
#  Reglages de l application : recents et ports attribues
# ---------------------------------------------------------------------------
_VERROU_REGLAGES = threading.Lock()


def reglages():
    r = lire_json(REGLAGES, {}) or {}
    r.setdefault("recents", [])
    r.setdefault("ports", {})
    return r


def noter_recent(chemin, genre, titre, port=None):
    with _VERROU_REGLAGES:
        r = reglages()
        cle = os.path.normcase(os.path.abspath(chemin))
        r["recents"] = [x for x in r["recents"]
                        if os.path.normcase(os.path.abspath(x.get("chemin", ""))) != cle]
        r["recents"].insert(0, {"chemin": chemin, "genre": genre, "titre": titre,
                                "date": time.strftime("%Y-%m-%d %H:%M"),
                                "port": port})
        r["recents"] = r["recents"][:30]
        if port:
            r["ports"][cle] = port
        ecrire_json(REGLAGES, r)


def oublier_recent(chemin):
    with _VERROU_REGLAGES:
        r = reglages()
        cle = os.path.normcase(os.path.abspath(chemin))
        r["recents"] = [x for x in r["recents"]
                        if os.path.normcase(os.path.abspath(x.get("chemin", ""))) != cle]
        ecrire_json(REGLAGES, r)


def port_libre_ici(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def port_pour_bibliotheque(chemin):
    """Un port par bibliotheque (invariant 7). Une bibliotheque deja connue
    garde le sien ; sinon le premier port de la plage qui n est ni reserve,
    ni attribue a une autre bibliotheque, ni occupe en ce moment."""
    r = reglages()
    cle = os.path.normcase(os.path.abspath(chemin))
    if cle in r["ports"]:
        return int(r["ports"][cle])
    pris = set(PORTS_RESERVES) | {int(p) for k, p in r["ports"].items() if k != cle}
    for port in range(PLAGE_FILMS[0], PLAGE_FILMS[1]):
        if port not in pris and port_libre_ici(port):
            return port
    raise RuntimeError("Aucun port libre entre %d et %d." % PLAGE_FILMS)


# ---------------------------------------------------------------------------
#  Ce qu est un dossier
# ---------------------------------------------------------------------------
LANCEUR_GENERAL = "Bibliotheque generale.bat"
LANCEUR_PREPARER = "Preparer une bibliotheque.bat"


def est_banque(chemin):
    serv = os.path.join(chemin, "serveur")
    return all(os.path.isfile(os.path.join(serv, f))
               for f in ("_serveur.py", "NAVIGATEUR.html", "_scan.py"))


def banques_de(racine):
    """Les banques d une racine a onglets (sous-dossiers equipes)."""
    out = []
    try:
        noms = sorted(os.listdir(racine), key=str.lower)
    except OSError:
        return out
    for n in noms:
        if n.startswith((".", "_")) or n.lower() == "serveur":
            continue
        p = os.path.join(racine, n)
        if os.path.isdir(p) and est_banque(p):
            conf = lire_json(os.path.join(p, "serveur", "_configuration.json"), None)
            out.append({"nom": n, "configuration": conf,
                        "compatible": bool(conf and conf.get("type")
                                           == "bibliotheque-configurable-v1")})
    return out


def detecter(chemin):
    """'films', 'racine' (images a onglets), 'images' (une banque) ou None,
    avec ce qu on sait de la bibliotheque."""
    serv = os.path.join(chemin, "serveur")
    # Une racine a onglets : bibliotheque generale + preparateur, comme
    # K:\Bibliotheque-Assets-IA ou LDR\Design-def. Testee AVANT la banque :
    # les deux ont un dossier « serveur ».
    if (os.path.isfile(os.path.join(serv, "_serveur.py"))
            and os.path.isfile(os.path.join(serv, "NAVIGATEUR.html"))
            and os.path.isfile(os.path.join(serv, "preparateur", "_preparateur.py"))):
        return {"genre": "racine", "titre": os.path.basename(chemin),
                "banques": banques_de(chemin),
                "moteur": os.path.isfile(os.path.join(serv, "_python", "python.exe"))}
    app = os.path.join(chemin, "_app")
    if (os.path.isfile(os.path.join(app, "serveur.py"))
            and os.path.isfile(os.path.join(app, "app.html"))):
        r = lire_json(os.path.join(app, "bibliotheque.json"), None)
        return {"genre": "films", "reglages": r,
                "titre": (r or {}).get("titre") or os.path.basename(chemin),
                "port": (r or {}).get("port") or (8779 if r is None else None),
                "moteur": os.path.isfile(os.path.join(app, "_python", "python.exe")),
                "ancienne_variante": r is None}
    serv = os.path.join(chemin, "serveur")
    if all(os.path.isfile(os.path.join(serv, f))
           for f in ("_serveur.py", "NAVIGATEUR.html", "_scan.py")):
        conf = lire_json(os.path.join(serv, "_configuration.json"), None)
        return {"genre": "images", "configuration": conf,
                "titre": os.path.basename(chemin),
                "moteur": os.path.isfile(os.path.join(serv, "_python", "python.exe")),
                "compatible": bool(conf and conf.get("type") == "bibliotheque-configurable-v1")}
    return None


def ecriture_possible(dossier):
    try:
        test = os.path.join(dossier, ".le-essai-%s" % uuid.uuid4().hex[:6])
        with open(test, "w") as f:
            f.write("x")
        os.remove(test)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
#  Windows : dossiers, raccourcis, lancement
# ---------------------------------------------------------------------------
SANS_CONSOLE = 0x08000000 if os.name == "nt" else 0


def ouvrir_explorateur(chemin):
    if os.name == "nt":
        os.startfile(chemin)            # noqa
    else:
        subprocess.Popen(["xdg-open", chemin])


def lanceur_de(racine):
    """Le .bat qui ouvre cette bibliotheque (celle d une racine : la
    bibliotheque generale)."""
    d = detecter(racine)
    nom = LANCEUR_GENERAL if (d and d["genre"] == "racine") else NOM_LANCEUR
    return os.path.join(racine, nom)


def lancer_bibliotheque(racine):
    """Double-clic sur le lanceur : sa propre console, comme a la main."""
    bat = lanceur_de(racine)
    if not os.path.isfile(bat):
        raise ValueError("Lanceur introuvable : %s" % bat)
    os.startfile(bat)                   # noqa


def lancer_preparateur(racine):
    bat = os.path.join(racine, LANCEUR_PREPARER)
    if not os.path.isfile(bat):
        raise ValueError("Preparateur introuvable : %s" % bat)
    os.startfile(bat)                   # noqa


# ---- lanceurs a icone -------------------------------------------------------
# Un .bat ne peut pas porter d icone : a cote de chaque lanceur .bat, on pose
# un .exe du meme nom (le petit lanceur de source/lanceur.cs, a l icone de
# Library Editor) qui lance ce .bat. Le .bat est cache : dans l Explorateur,
# on ne voit que le lanceur a icone. Il reste la, lisible et lancable.
def attribut_cache(chemin):
    if os.name != "nt" or not os.path.exists(chemin):
        return False
    try:
        import ctypes
        a = ctypes.windll.kernel32.GetFileAttributesW(str(chemin))
        return a != -1 and bool(a & 0x2)
    except Exception:
        return False


def cacher(chemin, oui=True):
    if os.name != "nt" or not os.path.exists(chemin):
        return
    try:
        import ctypes
        k = ctypes.windll.kernel32
        a = k.GetFileAttributesW(str(chemin))
        if a == -1:
            return
        a = (a | 0x2) if oui else (a & ~0x2)
        k.SetFileAttributesW(str(chemin), (a & 0xFFFF) or 0x80)
    except Exception:
        pass


def copier_fichier(source, cible):
    """shutil.copy2 qui passe outre l attribut « cache » : Windows refuse
    d ecraser un fichier cache avec un fichier normal."""
    cache = attribut_cache(cible)
    if cache:
        cacher(cible, False)
    os.makedirs(os.path.dirname(cible), exist_ok=True)
    shutil.copy2(source, cible)
    if cache:
        cacher(cible, True)


def poser_lanceur(dossier, nom_bat, source_bat):
    """Le .bat (cache) et son .exe a icone, dans `dossier`."""
    bat = os.path.join(dossier, nom_bat)
    copier_fichier(source_bat, bat)
    exe = os.path.splitext(bat)[0] + ".exe"
    if os.path.isfile(lanceur_exe()):
        copier_fichier(lanceur_exe(), exe)
        cacher(bat, True)
    return bat


def bureau():
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                            "[Environment]::GetFolderPath('Desktop')"],
                           capture_output=True, timeout=20,
                           creationflags=SANS_CONSOLE)
        d = r.stdout.decode("utf-8", "replace").strip()
        if d and os.path.isdir(d):
            return d
    except Exception:
        pass
    return os.path.join(os.path.expanduser("~"), "Desktop")


def raccourci_bureau(racine, titre, icone=None):
    """Un .lnk sur le Bureau vers le lanceur de la bibliotheque — son .exe a
    icone s il existe, sinon le .bat."""
    cible = lanceur_de(racine)
    exe = os.path.splitext(cible)[0] + ".exe"
    if os.path.isfile(exe):
        cible, icone = exe, exe
    nom = "".join(c for c in titre if c not in '<>:"/\\|?*').strip() or "Bibliotheque"
    lnk = os.path.join(bureau(), nom + ".lnk")
    ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:LE_LNK);"
          "$s.TargetPath=$env:LE_CIBLE;$s.WorkingDirectory=$env:LE_DOSSIER;"
          "if($env:LE_ICONE){$s.IconLocation=$env:LE_ICONE};"
          "$s.Description='Bibliotheque - Library Editor';$s.Save()")
    env = dict(os.environ, LE_LNK=lnk, LE_CIBLE=cible, LE_DOSSIER=racine,
               LE_ICONE=(icone + ",0") if icone else "")
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                       capture_output=True, timeout=30, env=env,
                       creationflags=SANS_CONSOLE)
    if r.returncode or not os.path.isfile(lnk):
        raise RuntimeError("Raccourci impossible : " +
                           r.stderr.decode("utf-8", "replace")[-300:])
    return lnk


def poser_moteur(destination, progression=None):
    """Copie le moteur Python embarque. Renvoie le nombre de fichiers, ou 0
    s il n est pas disponible (application lancee hors gel sans build)."""
    src = moteur_source()
    if not src:
        return 0
    if os.path.isdir(destination):
        shutil.rmtree(destination)
    return copier_arbre(src, destination, progression)


# ---------------------------------------------------------------------------
#  Taches de fond, suivies par l interface
# ---------------------------------------------------------------------------
class Tache:
    """Un travail long dans un fil, que la page interroge toutes les 400 ms.
    Une seule a la fois : deux installations croisees dans le meme dossier
    ne doivent pas pouvoir exister."""
    courante = None
    _verrou = threading.Lock()

    def __init__(self, genre, titre, fonction, *args):
        self.id = uuid.uuid4().hex[:10]
        self.genre, self.titre = genre, titre
        self.etape, self.fait, self.total = "", 0, 0
        self.lignes, self.etapes = [], []
        self.etat = "encours"            # encours | fini | erreur | annule
        self.resultat, self.erreur = None, ""
        self.debut = time.time()
        self._stop = False
        self._fonction, self._args = fonction, args

    @classmethod
    def lancer(cls, genre, titre, fonction, *args):
        with cls._verrou:
            t = cls.courante
            if t and t.etat == "encours":
                raise RuntimeError("Un travail est déjà en cours : %s" % t.titre)
            t = cls(genre, titre, fonction, *args)
            cls.courante = t
        threading.Thread(target=t._executer, daemon=True).start()
        return t

    def _executer(self):
        journal("TACHE", self.genre, self.titre)
        try:
            self.resultat = self._fonction(self, *self._args)
            self.etat = "annule" if self._stop else "fini"
        except Annulation:
            self.etat = "annule"
            self.ligne("Arrêté à la demande. Rien n'est à moitié fait : "
                       "relancer reprend là où ça s'est arrêté.", "alerte")
        except Exception as e:
            self.etat = "erreur"
            self.erreur = str(e) or type(e).__name__
            journal("ERREUR", self.titre, traceback.format_exc())
            self.ligne("Erreur : " + self.erreur, "erreur")
        journal("FIN", self.titre, self.etat)

    # ---- appele par le travail --------------------------------------------
    def etape_suivante(self, libelle, total=0):
        if self.etapes and self.etapes[-1]["etat"] == "encours":
            self.etapes[-1]["etat"] = "fait"
        self.etapes.append({"libelle": libelle, "etat": "encours"})
        self.etape, self.fait, self.total = libelle, 0, total

    def progres(self, fait, total=None):
        self.fait = fait
        if total is not None:
            self.total = total

    def ligne(self, texte, genre="info"):
        self.lignes.append({"t": time.strftime("%H:%M:%S"), "texte": texte,
                            "genre": genre})
        if len(self.lignes) > 400:
            self.lignes = self.lignes[-400:]

    def arreter(self):
        self._stop = True

    def annulee(self):
        return self._stop

    def verifier(self):
        if self._stop:
            raise Annulation()

    def terminer_etapes(self):
        if self.etapes and self.etapes[-1]["etat"] == "encours":
            self.etapes[-1]["etat"] = "fait"

    def vue(self, depuis=0):
        return {"id": self.id, "genre": self.genre, "titre": self.titre,
                "etat": self.etat, "etape": self.etape, "fait": self.fait,
                "total": self.total, "etapes": self.etapes,
                "lignes": self.lignes[depuis:], "nlignes": len(self.lignes),
                "resultat": self.resultat if self.etat != "encours" else None,
                "partiel": (getattr(self, "resultat_partiel", None)
                            if self.etat == "encours" else None),
                "erreur": self.erreur,
                "duree": round(time.time() - self.debut, 1)}


class Annulation(Exception):
    def __str__(self):
        return "Arrêté à la demande."

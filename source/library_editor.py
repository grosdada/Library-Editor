# -*- coding: utf-8 -*-
"""Library Editor — fabrique des bibliotheques d images et de films.

On lance l exe : une fenetre s ouvre (Edge en mode application, sans barre
d adresse), on choisit ou on cree un dossier, et il y installe une
bibliotheque complete — serveur, application, lanceur, premier scan — en
prouvant qu il n a touche a aucun fichier existant. Un module a part prepare
la mise en ligne sur Hostinger, avec son guide pas a pas.

Architecture : un petit serveur HTTP sur 127.0.0.1 sert l interface
(ui/index.html) et une API JSON ; les travaux longs tournent dans des fils
que la page suit. Aucune dependance hors de la bibliotheque standard, sauf
Pillow pour les apercus (facultatif).

    Library Editor.exe                      l application
    Library Editor.exe --choisir-dossier F  (interne) le selecteur natif
"""
import io
import json
import os
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse
import urllib.request
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.dont_write_bytecode = True
ICI = os.path.dirname(os.path.abspath(__file__))
if ICI not in sys.path:
    sys.path.insert(0, ICI)

import le_commun as C        # noqa: E402

# Sans console (application fenetree), sys.stdout vaut None : ce que les
# modules impriment part dans le journal au lieu de lever une erreur.
if sys.stdout is None or sys.stderr is None:
    try:
        os.makedirs(C.LOCAL, exist_ok=True)
        _j = io.open(C.JOURNAL, "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or _j
        sys.stderr = sys.stderr or _j
    except Exception:
        pass

# Chaque ffprobe, ffmpeg ou PowerShell lance depuis une application sans
# console ouvrirait une fenetre noire le temps d un eclair : 122 eclairs pour
# un scan. On les rend muets par defaut, pour ce processus seulement.
if os.name == "nt":
    _Popen = subprocess.Popen

    class _PopenMuet(_Popen):
        def __init__(self, *a, **k):
            if not k.get("creationflags"):
                k["creationflags"] = C.SANS_CONSOLE
            super().__init__(*a, **k)
    subprocess.Popen = _PopenMuet

JETON = uuid.uuid4().hex
IDENTITE = "library-editor-" + C.VERSION
VIE = {"battement": 0.0, "adieu": 0.0, "debut": time.time(), "fenetre": None}
RACINES_VUES = set()          # dossiers analyses : seuls servis en apercu
APERCUS = {}
INSTANCE = os.path.join(C.LOCAL, "instance.json")


# ---------------------------------------------------------------------------
#  Le selecteur de dossier : dans un processus a part (Tk n aime pas les fils
#  d un serveur HTTP), qui est ce meme exe appele avec --choisir-dossier.
# ---------------------------------------------------------------------------
def selecteur_enfant(depart, titre, sortie):
    import tkinter as tk
    from tkinter import filedialog
    r = tk.Tk()
    r.withdraw()
    r.attributes("-topmost", True)
    r.update()
    d = filedialog.askdirectory(parent=r, title=titre or "Choisir un dossier",
                                initialdir=(depart if depart and os.path.isdir(depart)
                                            else None), mustexist=True)
    r.destroy()
    with io.open(sortie, "w", encoding="utf-8") as f:
        json.dump({"chemin": os.path.normpath(d) if d else ""}, f)


def choisir_dossier(depart, titre):
    sortie = os.path.join(C.LOCAL, "choix-%s.json" % uuid.uuid4().hex[:8])
    os.makedirs(C.LOCAL, exist_ok=True)
    if C.GELE:
        cmd = [sys.executable, "--choisir-dossier", depart or "", titre or "", sortie]
    else:
        cmd = [sys.executable, os.path.abspath(__file__), "--choisir-dossier",
               depart or "", titre or "", sortie]
    try:
        subprocess.run(cmd, timeout=900)
        r = C.lire_json(sortie, {}) or {}
        return r.get("chemin", "")
    finally:
        try:
            os.remove(sortie)
        except OSError:
            pass


# ---------------------------------------------------------------------------
#  La fenetre
# ---------------------------------------------------------------------------
def trouver_edge():
    candidats = [
        os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                     r"Microsoft\Edge\Application\msedge.exe"),
        os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"),
                     r"Microsoft\Edge\Application\msedge.exe"),
    ]
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe") as k:
            candidats.insert(0, winreg.QueryValue(k, None))
    except Exception:
        pass
    for c in candidats:
        if c and os.path.isfile(c):
            return c
    return None


def taille_ecran():
    try:
        import ctypes
        u = ctypes.windll.user32
        return u.GetSystemMetrics(0), u.GetSystemMetrics(1)
    except Exception:
        return 1920, 1080


def ouvrir_fenetre(url):
    """Edge en mode application, avec son propre profil : c est une vraie
    fenetre a part, sans barre d adresse. A defaut, le navigateur par defaut."""
    edge = trouver_edge()
    if edge:
        W, H = taille_ecran()
        w, h = min(1360, W - 80), min(900, H - 90)
        # Un profil a part, SANS extensions ni synchronisation. Constate le
        # 22/09 : sur le profil habituel, un Edge ferme qui demarre pour nous
        # lance aussi les extensions de David (AIPRM ouvrait sa propre
        # fenetre) ; sur un profil neuf sans ces options, Edge synchronisait
        # les extensions du compte et faisait pareil. Avec elles : une seule
        # fenetre, et plus aucun processus Edge une fois fermee
        # (--disable-background-mode). Le Edge habituel n est pas touche.
        # L arret repose sur le battement et l adieu de la page.
        profil = os.path.join(C.LOCAL, "fenetre")
        try:
            p = subprocess.Popen([edge, "--app=" + url, "--user-data-dir=" + profil,
                                  "--window-size=%d,%d" % (w, h),
                                  "--window-position=%d,%d" % ((W - w) // 2,
                                                               max(0, (H - h) // 2 - 20)),
                                  "--no-first-run", "--no-default-browser-check",
                                  "--disable-extensions", "--disable-sync",
                                  "--disable-component-update",
                                  "--disable-background-mode"])
            VIE["fenetre"] = p
            return True
        except Exception as e:
            C.journal("Edge impossible :", e)
    webbrowser.open(url)
    return False


def instance_existante():
    """Une autre instance tourne deja ? On lui ouvre une fenetre et on sort."""
    r = C.lire_json(INSTANCE, None)
    if not r:
        return None
    url = "http://127.0.0.1:%d/" % int(r.get("port", 0))
    try:
        with urllib.request.urlopen(url + "api/identite", timeout=1.5) as x:
            if json.loads(x.read()).get("identite") == IDENTITE:
                return url
    except Exception:
        pass
    return None


def veiller():
    """S arrete quand la fenetre est fermee — jamais pendant un travail."""
    while True:
        time.sleep(1.0)
        t = C.Tache.courante
        if t and t.etat == "encours":
            continue
        now, bat, adieu = time.time(), VIE["battement"], VIE["adieu"]
        raison = None
        if not bat:
            if now - VIE["debut"] > 120:
                raison = "aucune fenetre"
        elif adieu and adieu > bat - 1 and now - adieu > 4:
            raison = "fenetre fermee"
        elif now - bat > 180:
            # Large exprès : une fenetre minimisee, Edge la ralentit a un
            # battement par minute. L adieu couvre la fermeture normale.
            raison = "plus de battement"
        if raison:
            C.journal("ARRET :", raison)
            try:
                os.remove(INSTANCE)
            except OSError:
                pass
            os._exit(0)


# ---------------------------------------------------------------------------
#  L API
# ---------------------------------------------------------------------------
def lire_page():
    with io.open(C.interface("index.html"), encoding="utf-8") as f:
        t = f.read()
    return t.replace("%%JETON%%", JETON).replace("%%VERSION%%", C.VERSION)


def recents():
    out = []
    for x in C.reglages()["recents"]:
        ch = x.get("chemin", "")
        d = C.detecter(ch) if os.path.isdir(ch) else None
        out.append(dict(x, existe=bool(d), genre=(d or {}).get("genre", x.get("genre")),
                        titre=(d or {}).get("titre") or x.get("titre"),
                        port=(d or {}).get("port") or x.get("port")))
    return out


def etat_general():
    import shutil
    t = C.Tache.courante
    return {"version": C.VERSION, "identite": IDENTITE,
            "ffmpeg": bool(shutil.which("ffmpeg")),
            "ffprobe": bool(shutil.which("ffprobe")),
            "moteur": bool(C.moteur_source()), "edge": bool(trouver_edge()),
            "recents": recents(),
            "tache": t.vue(len(t.lignes)) if t else None}


def inspecter(chemin):
    chemin = os.path.abspath(os.path.expandvars(os.path.expanduser(chemin.strip().strip('"'))))
    if not os.path.isdir(chemin):
        raise ValueError("Dossier introuvable : %s" % chemin)
    try:
        noms = os.listdir(chemin)
    except OSError as e:
        raise ValueError("Dossier illisible : %s" % e)
    visibles = [n for n in noms if not n.startswith((".", "$"))]
    sous = [n for n in visibles if os.path.isdir(os.path.join(chemin, n))]
    d = C.detecter(chemin)
    reseau = False
    if os.name == "nt":
        try:
            import ctypes
            lecteur = os.path.splitdrive(chemin)[0] + "\\"
            reseau = chemin.startswith("\\\\") or \
                ctypes.windll.kernel32.GetDriveTypeW(lecteur) == 4
        except Exception:
            pass
    return {"chemin": chemin, "nom": os.path.basename(chemin) or chemin,
            "vide": not visibles, "sous_dossiers": len(sous),
            "fichiers": len(visibles) - len(sous), "detection": d,
            "ecriture": C.ecriture_possible(chemin), "reseau": reseau,
            "parent": os.path.dirname(chemin)}


def creer_dossier(parent, nom):
    nom = (nom or "").strip()
    if not nom or any(c in nom for c in '<>:"/\\|?*') or nom.strip(". ") != nom.strip():
        raise ValueError("Nom de dossier invalide.")
    parent = os.path.abspath(parent)
    if not os.path.isdir(parent):
        raise ValueError("Dossier parent introuvable.")
    cible = os.path.join(parent, nom)
    if os.path.exists(cible):
        if os.listdir(cible):
            raise ValueError("Ce dossier existe déjà et n'est pas vide : "
                             "choisissez-le plutôt avec « Choisir un dossier existant ».")
        return cible
    os.makedirs(cible)
    return cible


def apercu(racine, rel):
    """Une vignette de 240 px, pour montrer quelles images le suffixe
    choisit. Seulement dans un dossier analyse pendant cette session."""
    racine = os.path.abspath(racine)
    vus = {os.path.normcase(racine), os.path.normcase(os.path.dirname(racine))}
    if not (vus & RACINES_VUES):
        raise PermissionError("Dossier non analysé.")
    plein = os.path.abspath(os.path.join(racine, rel))
    if not os.path.normcase(plein).startswith(os.path.normcase(racine) + os.sep):
        raise PermissionError("Chemin refusé.")
    if os.path.splitext(plein)[1].lower() not in C.EXT_IMAGE:
        raise PermissionError("Pas une image.")
    cle = (plein, os.path.getmtime(plein))
    if cle in APERCUS:
        return APERCUS[cle]
    from PIL import Image, ImageOps
    with Image.open(plein) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((240, 240))
        b = io.BytesIO()
        im.save(b, "JPEG", quality=82)
    if len(APERCUS) > 400:
        APERCUS.clear()
    APERCUS[cle] = b.getvalue()
    return APERCUS[cle]


def lancer_tache(genre, titre, fonction, *args):
    t = C.Tache.lancer(genre, titre, fonction, *args)
    return {"tache": t.id}


def route_post(chemin, d):
    import le_films as F
    import le_images as I
    import le_enligne as E
    import le_maj

    if chemin == "/api/choisir":
        return {"chemin": choisir_dossier(d.get("depart", ""), d.get("titre", ""))}
    if chemin == "/api/creer-dossier":
        return {"chemin": creer_dossier(d.get("parent", ""), d.get("nom", ""))}
    if chemin == "/api/inspecter":
        return inspecter(d.get("chemin", ""))
    if chemin == "/api/analyser":
        racine = inspecter(d.get("chemin", ""))["chemin"]
        RACINES_VUES.add(os.path.normcase(racine))
        if d.get("genre") == "images":
            return lancer_tache("analyse", "Analyse des images", I.analyser, racine)
        return lancer_tache("analyse", "Analyse des films", F.analyser, racine)
    if chemin == "/api/images/verifier":
        racine = os.path.abspath(d.get("chemin", ""))
        RACINES_VUES.add(os.path.normcase(racine))
        return I.verifier(racine, d.get("reglage") or {})
    if chemin == "/api/installer":
        racine = inspecter(d.get("chemin", ""))["chemin"]
        reglages = d.get("reglages") or {}
        if d.get("genre") == "images":
            if reglages.get("racine"):
                return lancer_tache("installation", "Bibliothèque d'images à onglets",
                                    I.installer_racine, racine, reglages)
            return lancer_tache("installation", "Installation de la bibliothèque "
                                "d'images", I.installer, racine, reglages)
        return lancer_tache("installation", "Installation de la bibliothèque de "
                            "films", F.installer, racine, reglages)
    if chemin == "/api/maj/etat":
        racine = inspecter(d.get("chemin", ""))["chemin"]
        return le_maj.etat(racine)
    if chemin == "/api/maj/lancer":
        racine = inspecter(d.get("chemin", ""))["chemin"]
        det = C.detecter(racine) or {}
        return lancer_tache("maj", "Mise à jour de %s" % (det.get("titre") or
                            os.path.basename(racine)),
                            le_maj.appliquer, racine, d.get("options") or {})
    if chemin == "/api/editeur/maj/etat":
        return le_maj.etat_editeur()
    if chemin == "/api/editeur/maj/lancer":
        return lancer_tache("maj", "Mise à jour de Library Editor",
                            le_maj.maj_editeur)
    if chemin == "/api/preparer":
        C.lancer_preparateur(os.path.abspath(d.get("chemin", "")))
        return {"ok": True}
    if chemin == "/api/tache/arreter":
        t = C.Tache.courante
        if t:
            t.arreter()
        return {"ok": True}
    if chemin == "/api/ouvrir":
        C.lancer_bibliotheque(os.path.abspath(d.get("chemin", "")))
        return {"ok": True}
    if chemin == "/api/explorer":
        p = os.path.abspath(d.get("chemin", ""))
        if not os.path.exists(p):
            raise ValueError("Introuvable : %s" % p)
        C.ouvrir_explorateur(p)
        return {"ok": True}
    if chemin == "/api/raccourci":
        racine = os.path.abspath(d.get("chemin", ""))
        det = C.detecter(racine)
        if not det:
            raise ValueError("Aucune bibliothèque dans ce dossier.")
        sous = "_app" if det["genre"] == "films" else "serveur"
        icone = os.path.join(racine, sous, "_python", "python.exe")
        return {"raccourci": C.raccourci_bureau(racine, det.get("titre") or
                                                os.path.basename(racine),
                                                icone if os.path.isfile(icone) else None)}
    if chemin == "/api/oublier":
        C.oublier_recent(d.get("chemin", ""))
        return {"ok": True}
    if chemin == "/api/navigateur":
        u = str(d.get("url", ""))
        if not u.startswith(("https://", "http://")):
            raise ValueError("Adresse refusée.")
        webbrowser.open(u)
        return {"ok": True}
    if chemin == "/api/enligne/etat":
        return E.etat(inspecter(d.get("chemin", ""))["chemin"])
    if chemin == "/api/enligne/guide":
        return {"etapes": E.etapes_guide(d.get("genre", "images"), d.get("site", ""),
                                         d.get("url", ""), d.get("taille", ""))}
    if chemin == "/api/enligne/preparer":
        racine = inspecter(d.get("chemin", ""))["chemin"]
        return lancer_tache("enligne", "Paquet de mise en ligne", E.preparer, racine,
                            d.get("options") or {})
    raise LookupError("route inconnue")


class Poste(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _envoyer(self, code, corps, type_="application/json; charset=utf-8",
                 cache="no-store"):
        self.send_response(code)
        self.send_header("Content-Type", type_)
        self.send_header("Content-Length", str(len(corps)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(corps)

    def _json(self, obj, code=200):
        self._envoyer(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        try:
            if u.path in ("/", "/index.html"):
                return self._envoyer(200, lire_page().encode("utf-8"),
                                     "text/html; charset=utf-8")
            if u.path in ("/icone.png", "/favicon.ico"):
                with open(C.interface("icone.png"), "rb") as f:
                    return self._envoyer(200, f.read(), "image/png", "max-age=86400")
            if u.path == "/api/identite":
                return self._json({"identite": IDENTITE})
            # Le reste exige le jeton : une page d un autre site ne peut pas
            # le lire, donc ne peut rien demander ici.
            if (q.get("j") or [""])[0] != JETON:
                return self._json({"erreur": "jeton"}, 403)
            if u.path == "/api/vivant":
                # Seule une page de CETTE instance compte : une fenetre oubliee
                # d une session precedente, sur le meme port, recoit un refus
                # (et se recharge) au lieu de garder l application en vie.
                VIE["battement"] = time.time()
                return self._json({"ok": True})
            if u.path == "/api/etat":
                return self._json(etat_general())
            if u.path == "/api/tache":
                t = C.Tache.courante
                depuis = int((q.get("depuis") or ["0"])[0] or 0)
                return self._json(t.vue(depuis) if t else {"etat": "aucune"})
            if u.path == "/api/apercu":
                corps = apercu((q.get("racine") or [""])[0], (q.get("p") or [""])[0])
                return self._envoyer(200, corps, "image/jpeg", "max-age=3600")
            return self._json({"erreur": "introuvable"}, 404)
        except PermissionError as e:
            return self._json({"erreur": str(e)}, 403)
        except Exception as e:
            C.journal("GET", self.path, traceback.format_exc())
            return self._json({"erreur": str(e)}, 400)

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        if u.path == "/api/adieu":
            n = int(self.headers.get("Content-Length") or 0)
            corps = self.rfile.read(n) if n else b""
            if JETON.encode() in corps or (urllib.parse.parse_qs(u.query).get("j")
                                           or [""])[0] == JETON:
                VIE["adieu"] = time.time()
            return self._json({"ok": True})
        origine = self.headers.get("Origin")
        hote = "http://" + (self.headers.get("Host") or "")
        if ((origine and origine != hote)
                or self.headers.get("Sec-Fetch-Site") == "cross-site"
                or self.headers.get("X-LE-Jeton") != JETON):
            return self._json({"erreur": "Origine refusée."}, 403)
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n > 2000000:
                raise ValueError("Requête trop volumineuse.")
            d = json.loads(self.rfile.read(n).decode("utf-8") or "{}") if n else {}
            if not isinstance(d, dict):
                raise ValueError("Objet JSON attendu.")
            return self._json(route_post(u.path, d))
        except LookupError as e:
            return self._json({"erreur": str(e)}, 404)
        except Exception as e:
            C.journal("POST", u.path, traceback.format_exc())
            return self._json({"erreur": str(e)}, 400)


class Serveur(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False


def demarrer(sans_fenetre=False, port_voulu=None):
    os.makedirs(C.LOCAL, exist_ok=True)
    url = None if port_voulu else instance_existante()
    if url:
        ouvrir_fenetre(url)
        return 0
    srv = None
    for port in ([port_voulu] if port_voulu else range(8765, 8779)):
        try:
            srv = Serveur(("127.0.0.1", port), Poste)
            break
        except OSError:
            continue
    if srv is None:
        C.journal("Aucun port libre pour l application.")
        return 1
    port = srv.server_address[1]
    C.ecrire_json(INSTANCE, {"port": port, "pid": os.getpid()})
    url = "http://127.0.0.1:%d/" % port
    C.journal("DEMARRAGE", C.VERSION, url, "gele" if C.GELE else "source")
    if not sans_fenetre:
        threading.Thread(target=veiller, daemon=True).start()
        threading.Timer(0.3, lambda: ouvrir_fenetre(url)).start()
    print("Library Editor : %s" % url, flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "--choisir-dossier":
        a = sys.argv[2:] + ["", "", ""]
        selecteur_enfant(a[0], a[1], a[2])
        sys.exit(0)
    port = None
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
    sys.exit(demarrer("--sans-fenetre" in sys.argv, port))

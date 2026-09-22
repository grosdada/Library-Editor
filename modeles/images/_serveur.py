# -*- coding: utf-8 -*-
"""Serveur d'une banque configurable. Importable par la bibliotheque generale."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
import webbrowser
import zipfile

sys.dont_write_bytecode = True
ICI = Path(__file__).resolve().parent
RACINE = ICI.parent
VERROU = threading.Lock()
SCAN_VERROU = threading.Lock()
spec = importlib.util.spec_from_file_location("indexeur_" + str(id(ICI)), ICI / "_scan.py")
INDEXEUR = importlib.util.module_from_spec(spec)
spec.loader.exec_module(INDEXEUR)


def lire(nom, defaut):
    fichier = ICI / nom
    if not fichier.exists():
        return defaut
    return json.loads(fichier.read_text(encoding="utf-8-sig"))


def ecrire(nom, valeur):
    cible = ICI / nom
    temporaire = cible.with_suffix(cible.suffix + ".tmp")
    temporaire.write_text(json.dumps(valeur, ensure_ascii=False), encoding="utf-8")
    os.replace(temporaire, cible)


def chemin_asset(relatif, dossier=False):
    if not isinstance(relatif, str):
        raise ValueError("Chemin invalide.")
    chemin = (RACINE / relatif).resolve()
    try:
        rel = chemin.relative_to(RACINE.resolve())
    except ValueError:
        raise ValueError("Chemin hors de la bibliotheque.")
    if any(p.casefold() in INDEXEUR.EXCLUS or p.startswith(".") for p in rel.parts):
        raise ValueError("Dossier technique exclu.")
    if dossier:
        if not chemin.is_dir():
            raise ValueError("Dossier introuvable.")
    elif not chemin.is_file() or chemin.suffix.lower() not in INDEXEUR.EXTENSIONS:
        raise ValueError("Image introuvable.")
    return chemin


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(RACINE), **kwargs)

    def reponse(self, code, valeur):
        corps = json.dumps(valeur, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corps)))
        self.end_headers()
        self.wfile.write(corps)

    def fichier(self, chemin):
        # Le chemin est valide avant toute ouverture.
        try:
            contenu = chemin.read_bytes()
        except OSError:
            return self.reponse(404, {"erreur": "Fichier introuvable."})
        version = (parse_qs(urlparse(self.path).query).get("v") or [""])[0]
        image = chemin.suffix.lower() in INDEXEUR.EXTENSIONS
        self._cache_image = bool(image and version and version == hashlib.sha256(contenu).hexdigest())
        self.send_response(200)
        self.send_header("Content-Type", self.guess_type(str(chemin)))
        self.send_header("Content-Length", str(len(contenu)))
        self.end_headers()
        self.wfile.write(contenu)

    def do_GET(self):
        u = urlparse(self.path)
        try:
            if u.path in ("/", "/serveur/NAVIGATEUR.html"):
                return self.fichier(ICI / "NAVIGATEUR.html")
            if u.path == "/donnees":
                return self.reponse(200, lire("_donnees.json", {"nom": RACINE.name, "items": []}))
            if u.path == "/marques":
                return self.reponse(200, lire("_marques.json", {}))
            if u.path == "/fichier":
                return self.fichier(chemin_asset((parse_qs(u.query).get("p") or [""])[0]))
            if u.path == "/vignette":
                nom = (parse_qs(u.query).get("id") or [""])[0]
                if len(nom) == 28 and nom.endswith(".jpg") and all(c in "0123456789abcdef" for c in nom[:-4]):
                    return self.fichier(ICI / "_vignettes" / nom)
            return self.reponse(404, {"erreur": "Ressource inconnue."})
        except (ValueError, OSError) as erreur:
            return self.reponse(400, {"erreur": str(erreur)})

    def do_POST(self):
        origine = self.headers.get("Origin")
        if (origine and origine != "http://" + self.headers.get("Host", "")) or self.headers.get("Sec-Fetch-Site") == "cross-site":
            return self.reponse(403, {"erreur": "Origine refusee."})
        try:
            taille = int(self.headers.get("Content-Length", 0))
            if not 0 < taille <= 4000000:
                raise ValueError("Requete invalide ou trop volumineuse.")
            brut = self.rfile.read(taille).decode("utf-8")
            if "application/x-www-form-urlencoded" in self.headers.get("Content-Type", ""):
                brut = parse_qs(brut).get("d", ["{}"])[0]
            d = json.loads(brut)
            if not isinstance(d, dict):
                raise ValueError("Objet JSON attendu.")
            route = urlparse(self.path).path
            if route == "/scan":
                with SCAN_VERROU:
                    resultat = INDEXEUR.enregistrer(RACINE, lire("_configuration.json", {}), ICI, forcer=True)
                return self.reponse(200, resultat)
            if route == "/ouvrir":
                chemin = chemin_asset(d.get("dossier", "."), dossier=True)
                if sys.platform.startswith("win"):
                    subprocess.Popen(["explorer", str(chemin)])
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", str(chemin)])
                else:
                    subprocess.Popen(["xdg-open", str(chemin)])
                return self.reponse(200, {"ok": True})
            if route == "/marques":
                with VERROU:
                    marques = lire("_marques.json", {})
                    for identifiant, valeur in d.items():
                        if not isinstance(valeur, dict):
                            continue
                        ancien = marques.get(identifiant, {})
                        if int(valeur.get("t", 0)) >= int(ancien.get("t", 0)):
                            marques[identifiant] = {"fav": bool(valeur.get("fav")), "coul": max(0, min(5, int(valeur.get("coul", 0)))), "t": int(valeur.get("t", time.time() * 1000))}
                    ecrire("_marques.json", marques)
                return self.reponse(200, marques)
            if route == "/zip":
                selection = d.get("fichiers", [])
                if not isinstance(selection, list) or not selection:
                    raise ValueError("Selection vide.")
                chemins = list(dict.fromkeys(chemin_asset(p) for p in selection))
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Disposition", 'attachment; filename="selection.zip"')
                self.end_headers()
                with zipfile.ZipFile(self.wfile, "w", zipfile.ZIP_STORED) as archive:
                    for chemin in chemins:
                        archive.write(chemin, chemin.relative_to(RACINE.resolve()).as_posix())
                return
            return self.reponse(404, {"erreur": "Action inconnue."})
        except (ValueError, OSError, TypeError) as erreur:
            return self.reponse(400, {"erreur": str(erreur)})

    def do_HEAD(self):
        self.send_error(405)

    def end_headers(self):
        self.send_header("Cache-Control", "private, max-age=31536000, immutable" if getattr(self, "_cache_image", False) else "no-store")
        self._cache_image = False
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    # Sans ce message, la console restait noire pendant tout le scan : on
    # croyait l ouverture ratee.
    print("Bibliotheque " + RACINE.name + " : mise a jour de l'index...", flush=True)
    t0 = time.time()
    INDEXEUR.enregistrer(RACINE, lire("_configuration.json", {}), ICI)
    print("Index pret en %.0f s." % (time.time() - t0), flush=True)
    class Local(ThreadingHTTPServer):
        allow_reuse_address = False
    serveur = None
    for port in range(9100, 9200):
        try:
            serveur = Local(("127.0.0.1", port), Handler)
            break
        except OSError:
            continue
    if serveur is None:
        sys.exit("Aucun port local disponible.")
    url = "http://127.0.0.1:%d/serveur/NAVIGATEUR.html" % port
    print("Bibliotheque : " + url + "\nGardez cette fenetre ouverte. Ctrl+C pour arreter.")
    threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        serveur.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        serveur.server_close()


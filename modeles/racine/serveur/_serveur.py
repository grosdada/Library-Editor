# -*- coding: utf-8 -*-
"""Accueil portable des bibliotheques compatibles presentes a cote de serveur."""
import argparse
import importlib.util
import json
import ntpath
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import build_opener, ProxyHandler
import webbrowser

sys.dont_write_bytecode = True
ICI = Path(__file__).resolve().parent
RACINE = ICI.parent
IDENTITE = ("bibliotheque-assets-ia-v3:" + os.path.normcase(str(RACINE))).encode("utf-8")
FICHIER_ONGLETS = ICI / "_onglets.json"
ID_ONGLET = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
HTTP = build_opener(ProxyHandler({}))
ACTIFS = {}
VERROU = threading.Lock()
VERROU_MAJ = threading.Lock()


def _charger_maj():
    """_maj.py, depose par Library Editor : la mise a jour du programme de
    cette racine et de ses banques depuis GitHub. Absent : pas de bouton."""
    chemin = ICI / "_maj.py"
    if not chemin.is_file():
        return None
    try:
        spec = importlib.util.spec_from_file_location("_maj_racine", chemin)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


MAJ = _charger_maj()


class ServeurLocal(ThreadingHTTPServer):
    allow_reuse_address = False


def organisation():
    try:
        valeur = json.loads(FICHIER_ONGLETS.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, json.JSONDecodeError):
        valeur = {}
    if not isinstance(valeur, dict):
        valeur = {}
    onglets, ids, noms = [], set(), set()
    bruts = valeur.get("onglets", [])
    if not isinstance(bruts, list):
        bruts = []
    for brut in bruts[:40]:
        if not isinstance(brut, dict):
            continue
        identifiant = brut.get("id")
        nom = " ".join(str(brut.get("nom", "")).split())
        if not isinstance(identifiant, str) or not ID_ONGLET.fullmatch(identifiant):
            continue
        if not nom or len(nom) > 60 or identifiant in ids or nom.casefold() in noms:
            continue
        ids.add(identifiant)
        noms.add(nom.casefold())
        onglets.append({"id": identifiant, "nom": nom})
    classement = {}
    brut_classement = valeur.get("classement", {})
    if isinstance(brut_classement, dict):
        for bibliotheque, identifiant in brut_classement.items():
            if isinstance(bibliotheque, str) and identifiant in ids:
                classement[bibliotheque] = identifiant
    return {"version": 1, "onglets": onglets, "classement": classement}


def candidats():
    resultat = []
    bases = [RACINE]
    if (RACINE / "bibliotheques").is_dir():
        bases.append(RACINE / "bibliotheques")
    for base in bases:
        for dossier in sorted(base.iterdir(), key=lambda p: p.name.casefold()):
            if dossier.name == "serveur" or not dossier.is_dir():
                continue
            technique = dossier / "serveur"
            if (technique / "_serveur.py").is_file() and (technique / "NAVIGATEUR.html").is_file():
                resultat.append(dossier)
    return resultat


def preparer_index(dossier):
    index = dossier / "serveur" / "_donnees.js"
    scan = dossier / "serveur" / "_scan.py"
    if not scan.exists():
        return
    contenu = index.read_text(encoding="utf-8-sig") if index.exists() else ""
    match = re.search(r"const RACINE=(.*);", contenu)
    if match:
        ancien = json.loads(match.group(1))
        # Convention des banques existantes : RACINE indique leur dossier d'images.
        attendu = dossier / ntpath.basename(ancien.rstrip("/\\"))
        if os.path.normcase(ancien) == os.path.normcase(str(attendu)):
            return
        if not attendu.is_dir():
            raise RuntimeError("Dossier d'images absent : " + attendu.name)
    sauvegarde = ICI / "sauvegardes"
    sauvegarde.mkdir(exist_ok=True)
    copie = sauvegarde / (str(dossier.relative_to(RACINE)).replace(os.sep, "_") + "-donnees.js")
    if index.exists() and not copie.exists():
        copie.write_bytes(index.read_bytes())
    # Une banque configurable (_configuration.json) ne porte aucun chemin
    # absolu : on ne « met a jour les chemins » que pour les anciennes.
    print(("Mise a jour des chemins : " if match else "Index : ")
          + dossier.name, flush=True)
    subprocess.run([sys.executable, str(scan)], check=True)


def nouveau_service(handler, debut):
    for port in range(debut, debut + 100):
        try:
            return ServeurLocal(("127.0.0.1", port), handler)
        except OSError as erreur:
            if getattr(erreur, "winerror", None) not in (10048, 10013) and erreur.errno not in (98, 48, 10048, 10013):
                raise
    raise RuntimeError("Aucun port local disponible.")


def actualiser():
    with VERROU:
        resultat = []
        for dossier in candidats():
            identifiant = dossier.relative_to(RACINE).as_posix()
            info = {"id": identifiant, "nom": dossier.name}
            try:
                if identifiant not in ACTIFS:
                    preparer_index(dossier)
                    fichier = dossier / "serveur" / "_serveur.py"
                    spec = importlib.util.spec_from_file_location("banque_" + str(len(ACTIFS)), fichier)
                    module = importlib.util.module_from_spec(spec)
                    # Importer les fonctions sans executer le lancement __main__.
                    spec.loader.exec_module(module)
                    if not hasattr(module, "Handler"):
                        raise RuntimeError("Classe Handler absente du serveur.")
                    service = nouveau_service(module.Handler, 8890)
                    threading.Thread(target=service.serve_forever, daemon=True).start()
                    ACTIFS[identifiant] = service
                    print(dossier.name + " : pret.", flush=True)
                port = ACTIFS[identifiant].server_address[1]
                info["url"] = "http://127.0.0.1:%d/serveur/NAVIGATEUR.html" % port
            except Exception as erreur:
                info["erreur"] = str(erreur)
                print(dossier.name + " : " + str(erreur), file=sys.stderr, flush=True)
            resultat.append(info)
        return resultat


class Accueil(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ICI), **kwargs)

    def repondre(self, contenu, type_contenu, code=200):
        self.send_response(code)
        self.send_header("Content-Type", type_contenu)
        self.send_header("Content-Length", str(len(contenu)))
        self.end_headers()
        self.wfile.write(contenu)

    def json(self, valeur, code=200):
        self.repondre(json.dumps(valeur, ensure_ascii=False).encode("utf-8"),
                      "application/json; charset=utf-8", code)

    def do_POST(self):
        # Une seule action, la mise a jour du programme ; seulement depuis
        # cette page (une page d un autre site ne peut pas la declencher).
        n = int(self.headers.get("Content-Length") or 0)
        if n:
            self.rfile.read(min(n, 100000))
        origine = self.headers.get("Origin")
        if ((origine and origine != "http://" + self.headers.get("Host", ""))
                or self.headers.get("Sec-Fetch-Site") == "cross-site"):
            return self.json({"erreur": "Origine refusee."}, 403)
        if self.path.split("?")[0] != "/maj" or not MAJ:
            return self.json({"erreur": "Action inconnue."}, 404)
        if not VERROU_MAJ.acquire(blocking=False):
            return self.json({"erreur": "Une mise a jour est deja en cours."}, 409)
        try:
            return self.json(MAJ.appliquer_en_ligne("racine", str(RACINE)))
        except Exception as erreur:
            return self.json({"erreur": str(erreur)}, 502)
        finally:
            VERROU_MAJ.release()

    def do_GET(self):
        chemin = self.path.split("?")[0]
        if chemin == "/identite":
            self.repondre(IDENTITE, "text/plain; charset=utf-8")
        elif chemin == "/maj":
            # Y a-t-il plus recent sur GitHub, pour cette racine et ses banques ?
            if not MAJ:
                return self.json({"erreur": "Mise a jour indisponible."}, 404)
            try:
                self.json(MAJ.verifier_en_ligne("racine", str(RACINE)))
            except Exception as erreur:
                self.json({"erreur": str(erreur)}, 502)
        elif chemin == "/bibliotheques":
            self.repondre(json.dumps(actualiser(), ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
        elif chemin == "/organisation":
            self.repondre(json.dumps(organisation(), ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
        elif chemin in ("/", "/NAVIGATEUR.html"):
            self.path = "/NAVIGATEUR.html"
            super().do_GET()
        else:
            self.send_error(404)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, *args):
        pass


def retrouver():
    fichier = ICI / "etat-local.json"
    try:
        port = json.loads(fichier.read_text())["port"]
        if not isinstance(port, int) or not 8883 <= port < 8983:
            return None
        url = "http://127.0.0.1:%d/" % port
        with HTTP.open(url + "identite", timeout=1) as reponse:
            if reponse.read() == IDENTITE:
                return url
    except Exception:
        pass
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sans-navigateur", action="store_true")
    options = parser.parse_args()
    url = retrouver()
    if url:
        print("La bibliotheque generale est deja ouverte : " + url)
        if not options.sans_navigateur:
            webbrowser.open(url)
        return 0
    accueil = None
    try:
        accueil = nouveau_service(Accueil, 8883)
        url = "http://127.0.0.1:%d/" % accueil.server_address[1]
        (ICI / "etat-local.json").write_text(json.dumps({"port": accueil.server_address[1]}))
        actualiser()
        print("\nBibliotheque generale : " + url)
        print("Gardez cette fenetre ouverte. Ctrl+C pour arreter.", flush=True)
        if not options.sans_navigateur:
            threading.Timer(0.5, lambda: webbrowser.open(url)).start()
        accueil.serve_forever()
    except KeyboardInterrupt:
        print("\nArret.")
    except Exception as erreur:
        print("Impossible de demarrer : " + str(erreur), file=sys.stderr)
        return 1
    finally:
        for service in ACTIFS.values():
            service.shutdown()
            service.server_close()
        if accueil:
            accueil.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())


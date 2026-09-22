# -*- coding: utf-8 -*-
"""Petit preparateur manuel : aucune action sur un dossier sans selection explicite."""
import argparse
import hashlib
import importlib.util
import json
import os
import re
import signal
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import uuid
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from urllib.request import build_opener, ProxyHandler
import webbrowser

sys.dont_write_bytecode = True
ICI = Path(__file__).resolve().parent
RACINE = ICI.parent.parent
MODELES = ICI / "modeles"
FICHIER_ONGLETS = RACINE / "serveur" / "_onglets.json"
ID_ONGLET = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
VERROU = threading.Lock()
EXCLUS = {"serveur", "bibliotheques", "node_modules", "__pycache__", "$recycle.bin", "system volume information"}
spec = importlib.util.spec_from_file_location("indexeur_preparateur", MODELES / "_scan.py")
INDEXEUR = importlib.util.module_from_spec(spec)
spec.loader.exec_module(INDEXEUR)
HTTP = build_opener(ProxyHandler({}))
IDENTITE = ("preparateur-bibliotheques-v1:" + os.path.normcase(str(RACINE))).encode("utf-8")


def choisir(nom):
    if not isinstance(nom, str) or not nom or Path(nom).name != nom or "/" in nom or "\\" in nom:
        raise ValueError("Choisissez un dossier de la liste.")
    if nom.startswith(".") or nom.casefold() in EXCLUS:
        raise ValueError("Dossier technique exclu.")
    chemin = RACINE / nom
    if not chemin.is_dir() or chemin.is_symlink() or chemin.resolve().parent != RACINE.resolve():
        raise ValueError("Dossier absent ou situe hors de la racine.")
    return chemin.resolve()


def liste():
    resultat = []
    for dossier in sorted(RACINE.iterdir(), key=lambda p: p.name.casefold()):
        try:
            dossier = choisir(dossier.name)
        except ValueError:
            continue
        serveur = dossier / "serveur"
        complet = all((serveur / f).is_file() for f in ("_serveur.py", "NAVIGATEUR.html", "_scan.py"))
        info = {"nom": dossier.name, "etat": "existante" if complet else "bloquee" if serveur.exists() else "nouvelle"}
        if complet:
            try:
                configuration = json.loads((serveur / "_configuration.json").read_text(encoding="utf-8-sig"))
                info["vignette"] = str(configuration.get("vignette", "_source"))
            except (OSError, ValueError, json.JSONDecodeError, AttributeError):
                info["vignette"] = "_source"
        resultat.append(info)
    return resultat


def bibliotheques_preparees():
    return [d["nom"] for d in liste() if d["etat"] == "existante"]


def normaliser_organisation(valeur, stricte=False):
    if not isinstance(valeur, dict):
        if stricte:
            raise ValueError("Configuration des onglets invalide.")
        valeur = {}
    bruts = valeur.get("onglets", [])
    if not isinstance(bruts, list):
        if stricte:
            raise ValueError("La liste des onglets est invalide.")
        bruts = []
    if len(bruts) > 40:
        raise ValueError("Le nombre maximal d'onglets est 40.")
    onglets, ids, noms = [], set(), set()
    for brut in bruts:
        if not isinstance(brut, dict):
            if stricte:
                raise ValueError("Un onglet est invalide.")
            continue
        identifiant = brut.get("id")
        nom = " ".join(str(brut.get("nom", "")).split())
        valide = isinstance(identifiant, str) and ID_ONGLET.fullmatch(identifiant)
        valide = bool(valide and nom and len(nom) <= 60)
        if not valide or identifiant in ids or nom.casefold() in noms:
            if stricte:
                raise ValueError("Chaque onglet doit avoir un nom unique de 1 a 60 caracteres.")
            continue
        ids.add(identifiant)
        noms.add(nom.casefold())
        onglets.append({"id": identifiant, "nom": nom})
    preparees = bibliotheques_preparees()
    autorisees = set(preparees)
    brut_classement = valeur.get("classement", {})
    if not isinstance(brut_classement, dict):
        if stricte:
            raise ValueError("Le classement des bibliotheques est invalide.")
        brut_classement = {}
    classement = {}
    for bibliotheque, identifiant in brut_classement.items():
        if bibliotheque in autorisees and identifiant in ids:
            classement[bibliotheque] = identifiant
    return {
        "version": 1,
        "onglets": onglets,
        "classement": classement,
        "bibliotheques": [
            {"id": nom, "nom": nom, "onglet": classement.get(nom)}
            for nom in preparees
        ],
    }


def lire_organisation():
    try:
        valeur = json.loads(FICHIER_ONGLETS.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, json.JSONDecodeError):
        valeur = {}
    return normaliser_organisation(valeur)


def enregistrer_organisation(valeur):
    with VERROU:
        organisation = normaliser_organisation(valeur, stricte=True)
        donnees = {
            "version": 1,
            "onglets": organisation["onglets"],
            "classement": organisation["classement"],
        }
        temporaire = FICHIER_ONGLETS.with_name("._onglets-" + uuid.uuid4().hex + ".tmp")
        try:
            temporaire.write_text(
                json.dumps(donnees, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(temporaire, FICHIER_ONGLETS)
        finally:
            if temporaire.exists():
                temporaire.unlink()
        organisation["message"] = "Onglets et classement enregistres."
        return organisation


def nouveau(nom):
    dossier = choisir(nom)
    if (dossier / "serveur").exists():
        raise ValueError("Ce dossier contient deja un serveur. Aucun fichier ne sera remplace.")
    return dossier


def apercu(nom, config):
    dossier = nouveau(nom)
    return INDEXEUR.analyser(dossier, config)


def creer(nom, config):
    with VERROU:
        dossier = nouveau(nom)
        config = INDEXEUR.configuration(config)
        controle = INDEXEUR.analyser(dossier, config)
        if config.get("mode") == "dossier" and controle["stats"]["vignettes_multiples"]:
            raise ValueError("Plusieurs miniatures correspondent dans un meme dossier. Precisez le suffixe pour obtenir une seule miniature par dossier.")
        if not controle["items"]:
            raise ValueError("Aucune vignette ne correspond. Verifiez le suffixe avant de creer.")
        provisoire = dossier / (".preparation-" + uuid.uuid4().hex)
        provisoire.mkdir()
        try:
            for fichier in ("_serveur.py", "_scan.py", "NAVIGATEUR.html", "biblio.bat"):
                shutil.copyfile(MODELES / fichier, provisoire / fichier)
            (provisoire / "_configuration.json").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
            (provisoire / "_marques.json").write_text("{}", encoding="utf-8")
            donnees = INDEXEUR.enregistrer(dossier, config, provisoire)
            if config.get("mode") == "dossier" and donnees["stats"]["vignettes_multiples"]:
                raise ValueError("Plusieurs miniatures correspondent : creation annulee sans modifier les sources.")
            if not donnees["items"]:
                raise ValueError("Les images ont change pendant la preparation. Recommencez l'apercu.")
            # Publication complete en une seule operation. Ne jamais remplacer serveur.
            if (dossier / "serveur").exists():
                raise ValueError("Un serveur a ete ajoute pendant la preparation. Creation annulee.")
            provisoire.rename(dossier / "serveur")
            return {"ok": True, "nom": nom, "assets": len(donnees["items"]),
                    "message": "Bibliotheque creee. Dans l'accueil general, cliquez sur Actualiser les bibliotheques."}
        finally:
            if provisoire.exists():
                # Ce dossier temporaire a ete cree par cette operation et ne contient que nos sorties.
                if provisoire.resolve().parent == dossier and provisoire.name.startswith(".preparation-"):
                    shutil.rmtree(provisoire)


def apercu_reinitialisation(nom, config):
    dossier = choisir(nom)
    technique = dossier / "serveur"
    if not all((technique / f).is_file() for f in ("_serveur.py", "NAVIGATEUR.html", "_scan.py")):
        raise ValueError("Le dossier ne contient pas une bibliotheque reinitialisable.")
    return INDEXEUR.analyser(dossier, config)


def arreter_serveurs_bibliotheque(technique):
    if os.name != "nt":
        return 0
    commande = (
        "Get-CimInstance Win32_Process | "
        "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"
    )
    try:
        resultat = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", commande],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW, timeout=15,
        )
        if resultat.returncode or not resultat.stdout.strip():
            return 0
        processus = json.loads(resultat.stdout)
        if isinstance(processus, dict):
            processus = [processus]
        cible = os.path.normcase(str((technique / "_serveur.py").resolve()))
        arretes = 0
        for processus_candidat in processus:
            ligne = os.path.normcase(str(processus_candidat.get("CommandLine") or ""))
            pid = int(processus_candidat.get("ProcessId") or 0)
            if cible in ligne and pid and pid != os.getpid():
                try:
                    os.kill(pid, signal.SIGTERM)
                    arretes += 1
                except OSError:
                    pass
        if arretes:
            time.sleep(1.5)
        return arretes
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0


def vider_dossier(chemin):
    for enfant in chemin.iterdir():
        if enfant.is_dir() and not enfant.is_symlink():
            shutil.rmtree(enfant)
        else:
            enfant.unlink()


def copier_contenu(source, destination):
    for enfant in source.iterdir():
        cible = destination / enfant.name
        if enfant.is_dir() and not enfant.is_symlink():
            shutil.copytree(enfant, cible)
        else:
            shutil.copy2(enfant, cible)


def reinitialiser(nom, config):
    with VERROU:
        dossier = choisir(nom)
        technique = dossier / "serveur"
        if not all((technique / f).is_file() for f in ("_serveur.py", "NAVIGATEUR.html", "_scan.py")):
            raise ValueError("Le dossier ne contient pas une bibliotheque reinitialisable.")
        config = INDEXEUR.configuration(config)
        controle = INDEXEUR.analyser(dossier, config)
        if config.get("mode") == "dossier" and controle["stats"]["vignettes_multiples"]:
            raise ValueError("Plusieurs miniatures correspondent dans un meme dossier. Precisez le suffixe avant de reinitialiser.")
        if not controle["items"]:
            raise ValueError("Aucune vignette ne correspond. Verifiez le suffixe avant de reinitialiser.")

        identifiant = uuid.uuid4().hex
        provisoire = dossier / (".reinitialisation-" + identifiant)
        ancien = dossier / (".ancien-serveur-" + identifiant)
        sauvegarde = ICI / "sauvegardes" / (
            "reset-" + nom + "-" + time.strftime("%Y%m%d-%H%M%S") + "-" + identifiant[:6]
        )
        provisoire.mkdir()
        publie = False
        try:
            for fichier in ("_serveur.py", "_scan.py", "NAVIGATEUR.html", "biblio.bat"):
                shutil.copyfile(MODELES / fichier, provisoire / fichier)
            (provisoire / "_configuration.json").write_text(
                json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            (provisoire / "_marques.json").write_text("{}", encoding="utf-8")
            donnees = INDEXEUR.enregistrer(dossier, config, provisoire)
            if config.get("mode") == "dossier" and donnees["stats"]["vignettes_multiples"]:
                raise ValueError("Plusieurs miniatures correspondent : reinitialisation annulee.")
            if not donnees["items"]:
                raise ValueError("Les images ont change pendant la verification. Recommencez.")

            shutil.copytree(technique, sauvegarde)
            arreter_serveurs_bibliotheque(technique)
            try:
                technique.rename(ancien)
            except OSError as erreur_renommage:
                if getattr(erreur_renommage, "winerror", None) != 32:
                    raise
                # Un terminal peut encore conserver ce dossier comme repertoire courant.
                # Dans ce cas, remplace son contenu tout en gardant le dossier lui-meme.
                try:
                    vider_dossier(technique)
                    for enfant in list(provisoire.iterdir()):
                        shutil.move(str(enfant), str(technique / enfant.name))
                    publie = True
                except Exception:
                    try:
                        vider_dossier(technique)
                        copier_contenu(sauvegarde, technique)
                    except Exception:
                        pass
                    raise
            else:
                try:
                    provisoire.rename(technique)
                    publie = True
                except Exception:
                    ancien.rename(technique)
                    raise
                try:
                    shutil.rmtree(ancien)
                except OSError:
                    pass
            return {
                "ok": True,
                "nom": nom,
                "assets": len(donnees["items"]),
                "message": "Bibliotheque reinitialisee. Favoris, couleurs et reglages remis a zero.",
                "sauvegarde": str(sauvegarde),
            }
        finally:
            if provisoire.exists() and provisoire.resolve().parent == dossier:
                shutil.rmtree(provisoire)
            if ancien.exists() and not publie and not technique.exists():
                ancien.rename(technique)


def reparer(nom):
    with VERROU:
        dossier = choisir(nom)
        technique = dossier / "serveur"
        if not all((technique / f).is_file() for f in ("_serveur.py", "NAVIGATEUR.html", "_scan.py")):
            raise ValueError("Le dossier ne contient pas une bibliotheque avec un scan compatible.")
        proteges = ["_marques.json", "_marques.js", "_configuration.json", "_serveur.py", "_scan.py", "NAVIGATEUR.html"]
        avant = {f: (technique / f).read_bytes() if (technique / f).exists() else None for f in proteges}
        sauvegarde = ICI / "sauvegardes" / (nom + "-" + time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6])
        sauvegarde.mkdir(parents=True)
        derives = {}
        for f in ("_donnees.js", "_donnees.json"):
            if (technique / f).exists():
                derives[f] = (technique / f).read_bytes()
                (sauvegarde / f).write_bytes(derives[f])
        environnement = dict(os.environ, PYTHONIOENCODING="utf-8")
        resultat = subprocess.run([sys.executable, str(technique / "_scan.py")], capture_output=True,
                                  encoding="utf-8", errors="replace", env=environnement)
        modifies = []
        for f, contenu in avant.items():
            chemin = technique / f
            apres = chemin.read_bytes() if chemin.exists() else None
            if contenu is not None and apres != contenu:
                chemin.write_bytes(contenu)
                modifies.append(f)
        if resultat.returncode or modifies:
            for f, contenu in derives.items():
                (technique / f).write_bytes(contenu)
            raise ValueError("Indexation non terminee. Donnees precedentes restaurees. " +
                             ("Le scan a tente de modifier des fichiers proteges." if modifies else (resultat.stderr or resultat.stdout)[-1200:]))
        return {"ok": True, "nom": nom, "message": "Chemins et index actualises. Marquages et configuration conserves.",
                "details": resultat.stdout.strip()[-1200:]}

def ouvrir_bibliotheque(nom):
    dossier = choisir(nom)
    technique = dossier / "serveur"
    serveur = technique / "_serveur.py"
    if not all((technique / f).is_file() for f in ("_serveur.py", "NAVIGATEUR.html", "_scan.py")):
        raise ValueError("Le dossier selectionne ne contient pas une bibliotheque ouvrable.")
    options = {"cwd": str(technique)}
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW
    subprocess.Popen([sys.executable, str(serveur)], **options)
    return {"ok": True, "message": "Bibliotheque ouverte : " + dossier.name}
def programmer_suppression_generale(demande):
    if (demande.get("confirmation") != "are you sure"
            or demande.get("confirmation_finale") != "are you really sure"):
        raise ValueError("Les deux confirmations sont obligatoires.")

    serveur_general = (RACINE / "serveur").resolve()
    if serveur_general.parent != RACINE.resolve() or not serveur_general.is_dir():
        raise ValueError("Le dossier technique de la bibliotheque generale est introuvable.")

    # Arrete uniquement le serveur general identifie pour cette racine, s'il tourne.
    try:
        etat = serveur_general / "etat-local.json"
        port = json.loads(etat.read_text(encoding="utf-8-sig")).get("port")
        if isinstance(port, int) and 9000 <= port < 9100:
            url = "http://127.0.0.1:%d/" % port
            with HTTP.open(url + "identite", timeout=0.8) as reponse:
                identite = json.load(reponse).get("identite", "")
            racine_normale = os.path.normcase(str(RACINE))
            if identite.startswith("bibliotheque-generale-") and identite.endswith(racine_normale):
                pid = pid_ecoutant(port)
                if pid and pid != os.getpid():
                    os.kill(pid, signal.SIGTERM)
    except Exception:
        pass

    nettoyeur = (
        "import os,shutil,signal,sys,time\n"
        "parent=int(sys.argv[1]); serveur=sys.argv[2]; racine=sys.argv[3]\n"
        "time.sleep(2)\n"
        "try:\n os.kill(parent,signal.SIGTERM)\n"
        "except OSError:\n pass\n"
        "time.sleep(2)\n"
        "supprime=False\n"
        "for _ in range(30):\n"
        " try:\n  shutil.rmtree(serveur); supprime=True; break\n"
        " except OSError:\n  time.sleep(1)\n"
        "if not supprime:\n sys.exit(2)\n"
        "for nom in ('Bibliotheque generale.bat','Bibliothèque générale.bat',"
        "'Preparer une bibliotheque.bat','Préparer une bibliothèque.bat',"
        "'Bibliotheque generale.exe','Preparer une bibliotheque.exe'):\n"
        " try:\n  os.unlink(os.path.join(racine,nom))\n"
        " except FileNotFoundError:\n  pass\n"
    )
    options = {"cwd": str(RACINE.parent)}
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
    else:
        options["start_new_session"] = True
    subprocess.Popen(
        [sys.executable, "-c", nettoyeur, str(os.getpid()), str(serveur_general), str(RACINE)],
        **options,
    )
    return {
        "ok": True,
        "message": "Suppression de la bibliotheque generale programmee. Les dossiers d'images et les bibliotheques individuelles sont conserves.",
    }


def ouvrir_generale():
    serveur = RACINE / "serveur" / "_serveur.py"
    if not serveur.is_file():
        raise ValueError("Le serveur de la bibliotheque generale est introuvable.")
    options = {"cwd": str(serveur.parent)}
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW
    subprocess.Popen([sys.executable, str(serveur)], **options)
    return {"ok": True, "message": "Ouverture de la bibliotheque generale..."}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ICI), **kwargs)

    def json(self, code, d):
        corps = json.dumps(d, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corps)))
        self.end_headers()
        self.wfile.write(corps)

    def do_GET(self):
        chemin = urlparse(self.path).path
        if chemin == "/image":
            try:
                query = parse_qs(urlparse(self.path).query)
                dossier = choisir(query.get("dossier", [""])[0])
                fichier = (dossier / query.get("p", [""])[0]).resolve()
                relatif = fichier.relative_to(dossier)
                if any(p.startswith(".") or p.casefold() in EXCLUS for p in relatif.parts) or fichier.suffix.lower() not in INDEXEUR.EXTENSIONS:
                    raise ValueError("Image refusee.")
                contenu = fichier.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", self.guess_type(str(fichier)))
                self.send_header("Content-Length", str(len(contenu)))
                self.end_headers()
                return self.wfile.write(contenu)
            except (ValueError, OSError):
                return self.json(404, {"erreur": "Image introuvable."})
        if chemin == "/dossiers":
            return self.json(200, liste())
        if chemin == "/organisation":
            return self.json(200, lire_organisation())
        if chemin == "/identite":
            return self.json(200, {"identite": IDENTITE.decode("utf-8")})
        if chemin in ("/", "/PREPARER.html"):
            contenu = (ICI / "PREPARER.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(contenu)))
            self.end_headers()
            return self.wfile.write(contenu)
        self.json(404, {"erreur": "Ressource inconnue."})

    def do_POST(self):
        origine = self.headers.get("Origin")
        if (origine and origine != "http://" + self.headers.get("Host", "")) or self.headers.get("Sec-Fetch-Site") == "cross-site":
            return self.json(403, {"erreur": "Origine refusee."})
        try:
            taille = int(self.headers.get("Content-Length", 0))
            if not 0 < taille <= 20000:
                raise ValueError("Requete invalide.")
            d = json.loads(self.rfile.read(taille).decode("utf-8"))
            if not isinstance(d, dict):
                raise ValueError("Requete invalide.")
            route = urlparse(self.path).path
            if route == "/organisation":
                resultat = enregistrer_organisation(d)
            elif route == "/apercu":
                resultat = apercu(d.get("dossier"), d.get("config"))
            elif route == "/apercu-reset":
                resultat = apercu_reinitialisation(d.get("dossier"), d.get("config"))
            elif route == "/creer":
                resultat = creer(d.get("dossier"), d.get("config"))
            elif route == "/reset":
                resultat = reinitialiser(d.get("dossier"), d.get("config"))
            elif route == "/reparer":
                resultat = reparer(d.get("dossier"))
            elif route == "/ouvrir-bibliotheque":
                resultat = ouvrir_bibliotheque(d.get("dossier"))
            elif route == "/ouvrir-generale":
                resultat = ouvrir_generale()
            elif route == "/delete-general":
                resultat = programmer_suppression_generale(d)
            else:
                return self.json(404, {"erreur": "Action inconnue."})
            return self.json(200, resultat)
        except Exception as erreur:
            return self.json(400, {"erreur": str(erreur)})

    def do_HEAD(self):
        self.send_error(405)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def log_message(self, *args):
        pass


def pid_ecoutant(port):
    if os.name != "nt":
        return None
    try:
        sortie = subprocess.check_output(["netstat", "-ano", "-p", "tcp"], text=True,
                                          encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError):
        return None
    for ligne in sortie.splitlines():
        morceaux = ligne.split()
        if len(morceaux) >= 5 and morceaux[0] == "TCP" and morceaux[3] == "LISTENING":
            if morceaux[1].rsplit(":", 1)[-1] == str(port):
                try:
                    return int(morceaux[4])
                except ValueError:
                    return None
    return None


def arreter_instance(port, url):
    pid = pid_ecoutant(port)
    if pid is None or pid == os.getpid():
        raise RuntimeError("Impossible d'identifier l'ancien preparateur.")
    os.kill(pid, signal.SIGTERM)
    for _ in range(30):
        try:
            with HTTP.open(url + "identite", timeout=0.2):
                pass
        except Exception:
            return
        time.sleep(0.1)
    raise RuntimeError("L'ancien preparateur ne s'est pas arrete.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sans-navigateur", action="store_true")
    parser.add_argument("--remplacer", action="store_true")
    args = parser.parse_args()
    etat = ICI / "etat-local.json"
    try:
        port = json.loads(etat.read_text())["port"]
        if isinstance(port, int) and 9300 <= port < 9400:
            url = "http://127.0.0.1:%d/" % port
            with HTTP.open(url + "identite", timeout=1) as r:
                meme_instance = json.load(r)["identite"] == IDENTITE.decode("utf-8")
            if meme_instance:
                if args.remplacer:
                    arreter_instance(port, url)
                else:
                    if not args.sans_navigateur:
                        webbrowser.open(url)
                    print("Le preparateur est deja ouvert : " + url)
                    return 0
    except RuntimeError as erreur:
        print(str(erreur), file=sys.stderr)
        return 1
    except Exception:
        pass
    class Local(ThreadingHTTPServer):
        allow_reuse_address = False
    serveur = None
    for port in range(9300, 9400):
        try:
            serveur = Local(("127.0.0.1", port), Handler)
            break
        except OSError:
            continue
    if serveur is None:
        print("Aucun port local disponible.", file=sys.stderr)
        return 1
    etat.write_text(json.dumps({"port": port}), encoding="utf-8")
    url = "http://127.0.0.1:%d/" % port
    print("Preparer une bibliotheque : " + url)
    print("Gardez cette fenetre ouverte. Ctrl+C pour fermer.", flush=True)
    if not args.sans_navigateur:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        serveur.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        serveur.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())


# -*- coding: utf-8 -*-
"""Mises a jour — cote Library Editor.

Deux choses :
  1. mettre a jour UNE bibliotheque (films, racine a onglets et ses banques,
     banque seule) avec les fichiers que Library Editor embarque. Meme moteur
     et memes regles que le bouton des bibliotheques (modeles/commun/_maj.py) :
     version reconnue ou rien, fichiers modifies a la main gardes, sauvegarde
     avant remplacement, donnees jamais touchees. Les lanceurs .bat ne sont
     remplaces que si la bibliotheque est FERMEE ;
  2. se mettre a jour LUI-MEME depuis GitHub : la derniere version publiee
     (version.json, section « installeur ») est telechargee, verifiee
     (SHA-256), puis un petit script remplace l application une fois fermee
     et la relance.
"""
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import time
import urllib.request
import zipfile

import le_commun as C

_MAJ = None


def moteur():
    """Le module _maj.py du depot — celui qu on depose dans les
    bibliotheques."""
    global _MAJ
    if _MAJ is None:
        spec = importlib.util.spec_from_file_location("_maj_editeur", C.maj_py())
        _MAJ = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_MAJ)
    return _MAJ


def manifeste():
    """Le manifeste de CETTE version de Library Editor. Hors gel, calcule
    sur le dossier du projet (les modifications en cours comptent) ; gele,
    celui qui a ete fige a la construction."""
    if not C.GELE:
        sys.path.insert(0, C.ICI)
        import manifeste as M
        return M.generer()
    with open(C.depot("version.json"), encoding="utf-8") as f:
        return json.load(f)


def lecteur_local(chemin_depot):
    with open(C.depot(chemin_depot), "rb") as f:
        return f.read()


def genre_de(detection):
    return {"films": "films", "racine": "racine", "images": "banque"}.get(
        (detection or {}).get("genre"))


def marquer_installe(genre, racine):
    """Apres une installation : la version et l empreinte de chaque fichier
    de programme en place, dans _version.json. C est ce qui permettra, a la
    prochaine mise a jour, de distinguer « officiel » de « modifie »."""
    M, m = moteur(), manifeste()
    lignes = M.plan_complet(m, genre, racine)
    fichiers = {l["fichier"]: l["sha256"] for l in lignes if l["etat"] == "a_jour"}
    C.ecrire_json(os.path.join(M.dossier_version(genre, racine), M.NOM_VERSION),
                  {"version": m.get("version"), "maj": time.strftime("%Y-%m-%d %H:%M"),
                   "genre": genre, "fichiers": fichiers, "lanceurs_en_attente": []})


# ---------------------------------------------------------------------------
#  La bibliotheque est-elle ouverte ?
# ---------------------------------------------------------------------------
def _get(url, delai=1.0):
    try:
        with urllib.request.urlopen(url, timeout=delai) as r:
            return r.read()
    except Exception:
        return None


def ouverte(racine, detection):
    """Vrai si son serveur tourne : ses lanceurs .bat sont alors en cours
    de lecture par une console, et on n y touche pas."""
    racine = os.path.abspath(racine)
    g = genre_de(detection)
    if g == "films":
        port = (detection.get("reglages") or {}).get("port") or 8779
        b = _get("http://127.0.0.1:%d/api/projets" % int(port))
        if b:
            try:
                r = json.loads(b.decode("utf-8")).get("racine") or ""
                return os.path.normcase(os.path.abspath(r)) == os.path.normcase(racine)
            except Exception:
                return True
        return False
    if g == "racine":
        etat = C.lire_json(os.path.join(racine, "serveur", "etat-local.json"), {}) or {}
        port = etat.get("port")
        if isinstance(port, int):
            b = _get("http://127.0.0.1:%d/identite" % port)
            if b and b.decode("utf-8", "replace").endswith(os.path.normcase(racine)):
                return True
    # Banque seule (port choisi au vol), et filet pour les autres : un
    # Python dont la ligne de commande vise ce dossier.
    return _processus_sur(racine)


def _processus_sur(racine):
    if os.name != "nt":
        return False
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='python.exe' or "
             "Name='pythonw.exe' or Name='py.exe'\" | ForEach-Object "
             "{ $_.CommandLine }"],
            capture_output=True, timeout=20, creationflags=C.SANS_CONSOLE)
        lignes = r.stdout.decode("utf-8", "replace").lower()
        return os.path.normcase(os.path.abspath(racine)) in lignes
    except Exception:
        return False


# ---------------------------------------------------------------------------
#  Mettre a jour une bibliotheque
# ---------------------------------------------------------------------------
def etat(racine):
    racine = os.path.abspath(racine)
    det = C.detecter(racine)
    g = genre_de(det)
    if not g:
        raise ValueError("Aucune bibliotheque reconnue dans ce dossier.")
    M, m = moteur(), manifeste()
    lignes = M.plan_complet(m, g, racine)
    installe = M.lire_installe(M.dossier_version(g, racine))
    ouv = ouverte(racine, det)
    res = M.resume(m, lignes, installe, avec_lanceurs=not ouv)
    candidats = []
    if g == "films":
        regl = det.get("reglages") or {}
        if regl.get("projets_dans") == "." and isinstance(regl.get("projets"), list):
            import le_films
            for n in sorted(os.listdir(racine), key=str.lower):
                p = os.path.join(racine, n)
                if (os.path.isdir(p) and not n.startswith((".", "_"))
                        and n.lower() not in le_films.TECHNIQUES):
                    candidats.append({"nom": n, "coche": n in regl["projets"]})
    return dict(res, genre=g, racine=racine, detection=det, ouverte=ouv,
                candidats=candidats, a_jour=not res["a_faire"],
                moteur_disponible=bool(C.moteur_source()))


def appliquer(tache, racine, options):
    racine = os.path.abspath(racine)
    det = C.detecter(racine)
    g = genre_de(det)
    if not g:
        raise ValueError("Aucune bibliotheque reconnue dans ce dossier.")
    M, m = moteur(), manifeste()
    ouv = ouverte(racine, det)
    tache.etape_suivante("Mise a jour du programme (version %s)" % m.get("version"))
    if ouv:
        tache.ligne("La bibliotheque est ouverte : ses lanceurs .bat ne sont pas "
                    "touches (une console est en train de les lire).", "alerte")

    def rapporter(quoi, n, total, fichier):
        tache.progres(n, total)
        if quoi == "ecrit":
            tache.ligne("%s mis a jour" % fichier, "ok")

    res = M.appliquer(m, g, racine, lecteur_local, avec_lanceurs=not ouv,
                      rapporter=rapporter, forcer=bool(options.get("forcer")))
    if not res["faits"]:
        tache.ligne("Programme deja a jour.")
    for f in res["modifies"]:
        tache.ligne("%s : modifie a la main, garde tel quel" % f, "alerte")
    ajoutes, fiches, preuve = [], [], []
    if options.get("moteur") and C.moteur_source():
        tache.etape_suivante("Moteur Python embarque")
        dest = os.path.join(racine, "_app" if g == "films" else "serveur", "_python")
        n = C.poser_moteur(dest, lambda f, t: tache.progres(f, t))
        tache.ligne("Moteur Python : %d fichiers" % n, "ok")
    if g == "films" and options.get("projets"):
        import le_films
        ajoutes, fiches, preuve = le_films.ajouter_projets(
            tache, racine, options["projets"], "maj-" + time.strftime("%Y%m%d-%H%M"))
    d = C.detecter(racine)
    C.noter_recent(racine, d.get("genre"), d.get("titre"), d.get("port"))
    tache.terminer_etapes()
    return {"genre": g, "racine": racine, "remplaces": res["faits"],
            "modifies": res["modifies"], "lanceurs_en_attente": res["lanceurs_en_attente"],
            "version": res["version"], "ajoutes": ajoutes, "projets": fiches,
            "preuve": preuve, "titre": d.get("titre"), "port": d.get("port")}


# ---------------------------------------------------------------------------
#  Se mettre a jour soi-meme
# ---------------------------------------------------------------------------
def _version_tuple(v):
    try:
        return tuple(int(x) for x in str(v).split("."))
    except Exception:
        return (0,)


def etat_editeur():
    m = moteur().manifeste_distant()
    inst = m.get("installeur") or {}
    distante = inst.get("version") or m.get("version")
    return {"version_locale": C.VERSION, "version_distante": distante,
            "disponible": _version_tuple(distante) > _version_tuple(C.VERSION),
            "octets": inst.get("octets"), "notes": m.get("notes", ""),
            "gele": C.GELE, "depot": C.DEPOT_GITHUB}


def maj_editeur(tache):
    """Telecharge la nouvelle version, la verifie, et prepare son
    remplacement : il se fera des que cette application sera fermee."""
    if not C.GELE:
        raise RuntimeError("Library Editor tourne depuis ses sources : mettez-"
                           "les a jour avec git pull.")
    m = moteur().manifeste_distant()
    inst = m.get("installeur") or {}
    if not inst.get("url") or not inst.get("sha256"):
        raise RuntimeError("Aucune version telechargeable n est publiee.")
    version = inst.get("version")
    dossier = os.path.join(C.LOCAL, "maj")
    os.makedirs(dossier, exist_ok=True)
    zip_ = os.path.join(dossier, "Library-Editor-%s.zip" % version)
    tache.etape_suivante("Telechargement de la version %s" % version,
                         inst.get("octets") or 0)
    h = hashlib.sha256()
    req = urllib.request.Request(inst["url"], headers={"User-Agent": "Library-Editor"})
    with urllib.request.urlopen(req, timeout=60) as r, open(zip_ + ".part", "wb") as f:
        lu = 0
        while True:
            bloc = r.read(1 << 20)
            if not bloc:
                break
            f.write(bloc)
            h.update(bloc)
            lu += len(bloc)
            tache.progres(lu)
            tache.verifier()
    if h.hexdigest() != inst["sha256"]:
        os.remove(zip_ + ".part")
        raise RuntimeError("Le fichier telecharge ne correspond pas a la version "
                           "publiee (empreinte). Rien n a ete change.")
    os.replace(zip_ + ".part", zip_)
    tache.etape_suivante("Verification et preparation")
    tache.ligne("Archive téléchargée (%s), empreinte vérifiée : %s…"
                % (C.taille_humaine(os.path.getsize(zip_)), h.hexdigest()[:16]), "ok")
    cible = os.path.join(dossier, version)
    if os.path.isdir(cible):
        import shutil
        shutil.rmtree(cible)
    with zipfile.ZipFile(zip_) as z:
        z.extractall(cible)
    nouveau = os.path.join(cible, C.NOM)
    if not os.path.isfile(os.path.join(nouveau, C.NOM + ".exe")):
        raise RuntimeError("Archive inattendue : %s.exe absent." % C.NOM)
    actuel = os.path.dirname(sys.executable)
    if not os.path.isfile(os.path.join(actuel, C.NOM + ".exe")):
        raise RuntimeError("Dossier de l application introuvable.")
    tache.ligne("Version %s dépliée dans %s" % (version, cible))
    # Le remplacement n a lieu que quand cette application est FERMEE : ses
    # fichiers sont verrouilles tant qu elle tourne, et recopier par-dessus
    # en laisserait la moitie. Si elle reste ouverte, on ne remplace rien.
    script = os.path.join(dossier, "remplacer.ps1")
    C.ecrire_texte(script, "\r\n".join([
        "param([int]$Attendre, [string]$Source, [string]$Cible, [string]$Exe)",
        "$fin = (Get-Date).AddMinutes(20)",
        "while (Get-Process -Id $Attendre -ErrorAction SilentlyContinue) {",
        "  if ((Get-Date) -gt $fin) { exit 1 }",
        "  Start-Sleep -Seconds 1",
        "}",
        "Start-Sleep -Milliseconds 700",
        "robocopy $Source $Cible /E /R:6 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null",
        "Start-Process -FilePath $Exe",
    ]) + "\r\n")
    subprocess.Popen(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle",
         "Hidden", "-File", script, "-Attendre", str(os.getpid()), "-Source", nouveau,
         "-Cible", actuel, "-Exe", os.path.join(actuel, C.NOM + ".exe")],
        creationflags=0x00000008 | 0x00000200 | C.SANS_CONSOLE,
        close_fds=True)
    tache.terminer_etapes()
    return {"version": version, "redemarrage": True}

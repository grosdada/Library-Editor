# -*- coding: utf-8 -*-
"""Fabrique Library Editor.exe.

    python source/build.py            -> tout (moteur puis application)
    python source/build.py moteur     -> seulement le moteur Python embarque
    python source/build.py app        -> seulement l application

Deux gels PyInstaller, en mode « onedir » (le mode « onefile » declenche
plus de faux positifs antivirus, piege 10 du brief) :

  1. build/moteur/python/python.exe — le moteur depose dans chaque
     bibliotheque (_app/_python ou serveur/_python). Console, toute la
     bibliotheque standard, Tkinter, Pillow.
  2. dist/Library Editor/Library Editor.exe — l application, sans console,
     qui embarque les modeles, l interface et une copie du moteur.

Le modele video vient TOUJOURS de template/_app (serveur.py, app.html) :
une seule source, celle que les essais eprouvent.
"""
import os
import shutil
import subprocess
import sys

ICI = os.path.dirname(os.path.abspath(__file__))
PROJET = os.path.dirname(ICI)
BUILD = os.path.join(PROJET, "build")
DIST = os.path.join(PROJET, "dist")
MOTEUR_DIST = os.path.join(BUILD, "moteur")
NOM_APP = "Library Editor"

# Ce qui ne sert jamais a une bibliotheque et pese lourd ou casse le gel.
EXCLUS = {
    "test", "idlelib", "turtledemo", "lib2to3", "ensurepip", "venv",
    "distutils", "pydoc_data", "msilib", "curses", "readline", "nis",
    "grp", "pwd", "spwd", "crypt", "termios", "tty", "pty", "fcntl",
    "posix", "resource", "syslog", "ossaudiodev", "_posixsubprocess",
    "_curses", "_curses_panel", "antigravity", "this", "__phello__",
    "_testcapi", "_testinternalcapi", "_testbuffer", "_testimportmultiple",
    "_testmultiphase", "_xxsubinterpreters", "_xxtestfuzz", "xxlimited",
    "xxlimited_35", "xxsubtype", "_ctypes_test", "tkinter.test",
    "sqlite3.test", "ctypes.test", "unittest.test", "lib2to3.tests",
    # Tires par Pillow s ils sont installes : 27 Mo pour rien.
    "numpy", "charset_normalizer", "PyQt5", "PyQt6", "PySide2", "PySide6",
}
PAQUETS = ["asyncio", "collections", "concurrent", "ctypes", "dbm", "email",
           "encodings", "html", "http", "importlib", "json", "logging",
           "multiprocessing", "sqlite3", "tkinter", "urllib",
           "wsgiref", "xml", "xmlrpc", "zoneinfo"]


def alleger(dossier):
    """Les 607 fichiers de fuseaux horaires de Tcl ne servent qu a sa
    commande clock : ni Tk ni ses boites de dialogue n y touchent. Sur un
    disque reseau, 600 petits fichiers de moins se sentent a chaque copie."""
    tz = os.path.join(dossier, "_internal", "_tcl_data", "tzdata")
    if os.path.isdir(tz):
        shutil.rmtree(tz)


def bibliotheque_standard():
    """Tous les modules de la bibliotheque standard importables ici."""
    import importlib
    noms = []
    for n in sorted(getattr(sys, "stdlib_module_names", ())):
        if n in EXCLUS or n.startswith("_test"):
            continue
        try:
            importlib.import_module(n)
        except Exception:
            continue
        noms.append(n)
    return noms


def options_stdlib():
    opts = []
    for n in bibliotheque_standard():
        opts += ["--hidden-import", n]
    for p in PAQUETS:
        opts += ["--collect-submodules", p]
    for n in sorted(EXCLUS):
        opts += ["--exclude-module", n]
    opts += ["--collect-submodules", "PIL", "--hidden-import", "PIL.Image",
             "--hidden-import", "PIL.ImageOps"]
    return opts


def icone():
    """Une icone sobre : trois dos de livres et un repere, en .ico."""
    cible = os.path.join(ICI, "icone.ico")
    if os.path.isfile(cible):
        return cible
    from PIL import Image, ImageDraw
    tailles = [256, 128, 64, 48, 32, 24, 16]
    grand = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    d = ImageDraw.Draw(grand)
    d.rounded_rectangle((8, 8, 248, 248), radius=56, fill=(24, 25, 28, 255))
    # trois dos de livres, le dernier incline
    d.rounded_rectangle((58, 70, 92, 190), radius=6, fill=(232, 228, 220, 255))
    d.rounded_rectangle((102, 56, 136, 190), radius=6, fill=(214, 164, 92, 255))
    livre = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    dl = ImageDraw.Draw(livre)
    dl.rounded_rectangle((150, 78, 184, 198), radius=6,
                         fill=(150, 156, 166, 255))
    livre = livre.rotate(-14, resample=Image.BICUBIC, center=(167, 198))
    grand.alpha_composite(livre)
    d = ImageDraw.Draw(grand)
    d.rounded_rectangle((50, 196, 206, 206), radius=4, fill=(232, 228, 220, 255))
    grand.save(cible, sizes=[(t, t) for t in tailles])
    png = os.path.join(ICI, "ui", "icone.png")
    grand.resize((128, 128), Image.LANCZOS).save(png)
    return cible


def construire_lanceur():
    """Le petit .exe a icone qui lance le .bat du meme nom (lanceur.cs),
    compile par le csc du .NET Framework 4 — present sur tout Windows 10/11.
    Refait seulement si la source a bouge : l absence de csc n arrete pas la
    construction, les bibliotheques garderont leurs .bat nus."""
    src = os.path.join(ICI, "lanceur.cs")
    cible = os.path.join(PROJET, "modeles", "lanceur", "lanceur.exe")
    if (os.path.isfile(cible)
            and os.path.getmtime(cible) >= os.path.getmtime(src)
            and os.path.getmtime(cible) >= os.path.getmtime(icone())):
        return cible
    csc = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                       "Microsoft.NET", "Framework64", "v4.0.30319", "csc.exe")
    if not os.path.isfile(csc):
        print("csc introuvable : les lanceurs resteront des .bat sans icone.")
        return None
    os.makedirs(os.path.dirname(cible), exist_ok=True)
    r = subprocess.run([csc, "/nologo", "/target:winexe", "/optimize+",
                        "/win32icon:" + icone(), "/out:" + cible,
                        "/reference:System.dll",
                        "/reference:System.Windows.Forms.dll", src],
                       capture_output=True, text=True)
    print((r.stdout or r.stderr).strip() or "lanceur.exe : ok")
    if r.returncode or not os.path.isfile(cible):
        sys.exit("Compilation du lanceur impossible.")
    return cible


def ecrire_manifeste():
    """version.json a la racine du depot : ce qu est le programme de chaque
    genre de bibliotheque dans CETTE version. Il part avec l application (les
    bibliotheques hors ligne s en servent) et sera publie sur GitHub."""
    sys.path.insert(0, ICI)
    import manifeste
    m = manifeste.generer()
    chemin = os.path.join(PROJET, "version.json")
    with open(chemin, "w", encoding="utf-8", newline="\n") as f:
        import json
        json.dump(m, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print("version.json %s : %d fichiers" % (
        m["version"], sum(len(g["fichiers"]) for g in m["genres"].values())))
    return chemin


def emballer():
    """dist/Library Editor -> build/Library-Editor-<version>.zip, l archive
    que la mise a jour de l application telecharge et verifie."""
    sys.path.insert(0, ICI)
    import le_commun
    import zipfile
    source = os.path.join(DIST, NOM_APP)
    if not os.path.isdir(source):
        sys.exit("Rien a emballer : construisez l application d abord.")
    cible = os.path.join(BUILD, "Library-Editor-%s.zip" % le_commun.VERSION)
    with zipfile.ZipFile(cible, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for rep, _, fics in os.walk(source):
            for n in fics:
                p = os.path.join(rep, n)
                z.write(p, os.path.join(NOM_APP, os.path.relpath(p, source)))
    import hashlib
    h = hashlib.sha256()
    with open(cible, "rb") as f:
        for bloc in iter(lambda: f.read(1 << 20), b""):
            h.update(bloc)
    print("Archive : %s\n  %d octets\n  sha256 %s"
          % (cible, os.path.getsize(cible), h.hexdigest()))
    return cible


def pyinstaller(args):
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
           "--log-level", "WARN"] + args
    print("> " + " ".join(a if " " not in a else '"%s"' % a for a in cmd[:12])
          + " ...", flush=True)
    r = subprocess.run(cmd, cwd=PROJET)
    if r.returncode:
        sys.exit("PyInstaller a echoue (%d)" % r.returncode)


def construire_moteur():
    travail = os.path.join(BUILD, "travail-moteur")
    pyinstaller(["--onedir", "--console", "--name", "python",
                 "--icon", icone(),
                 "--distpath", MOTEUR_DIST, "--workpath", travail,
                 "--specpath", travail] + options_stdlib()
                + [os.path.join(ICI, "moteur.py")])
    alleger(os.path.join(MOTEUR_DIST, "python"))
    exe = os.path.join(MOTEUR_DIST, "python", "python.exe")
    r = subprocess.run([exe, "-c", "import sys, tkinter, PIL.Image, "
                        "http.server, json; print('moteur ok', "
                        "sys.version.split()[0])"],
                       capture_output=True, text=True)
    print((r.stdout or r.stderr).strip())
    if r.returncode:
        sys.exit("Le moteur ne repond pas comme prevu.")


def construire_app():
    moteur = os.path.join(MOTEUR_DIST, "python")
    if not os.path.isfile(os.path.join(moteur, "python.exe")):
        construire_moteur()
    construire_lanceur()
    ecrire_manifeste()
    travail = os.path.join(BUILD, "travail-app")
    sep = os.pathsep
    # L application embarque une copie du depot, aux MEMES chemins que
    # version.json (depot/modeles/..., depot/template/...) : ce qu elle
    # installe et ce que les bibliotheques telechargent ne peuvent pas
    # diverger.
    donnees = [
        (os.path.join(ICI, "ui"), "ui"),
        (os.path.join(PROJET, "modeles"), os.path.join("depot", "modeles")),
        (os.path.join(PROJET, "template", "_app", "serveur.py"),
         os.path.join("depot", "template", "_app")),
        (os.path.join(PROJET, "template", "_app", "app.html"),
         os.path.join("depot", "template", "_app")),
        (os.path.join(PROJET, "version.json"), "depot"),
        (moteur, os.path.join("moteur", "python")),
    ]
    args = ["--onedir", "--windowed", "--name", NOM_APP, "--icon", icone(),
            "--distpath", DIST, "--workpath", travail, "--specpath", travail]
    for src, dst in donnees:
        args += ["--add-data", src + sep + dst]
    args += options_stdlib()
    args += [os.path.join(ICI, "library_editor.py")]
    pyinstaller(args)
    alleger(os.path.join(DIST, NOM_APP))
    print("Application : %s" % os.path.join(DIST, NOM_APP, NOM_APP + ".exe"))


if __name__ == "__main__":
    quoi = sys.argv[1] if len(sys.argv) > 1 else "tout"
    if quoi in ("moteur", "tout"):
        construire_moteur()
    if quoi in ("lanceur",):
        construire_lanceur()
    if quoi in ("manifeste",):
        ecrire_manifeste()
    if quoi in ("app", "tout"):
        construire_app()
    if quoi in ("zip", "tout"):
        emballer()

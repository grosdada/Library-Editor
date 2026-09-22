# -*- coding: utf-8 -*-
"""La mise a jour de Library Editor lui-meme, de bout en bout.

    python tests/maj_editeur_essais.py ["dist/Library Editor"]

Il faut une application CONSTRUITE (python source/build.py) : c est elle qui
se met a jour. Rien n est touche hors d un dossier temporaire — l application
d essai est une copie, le depot est local (file://), et le remplacement vise
un dossier neuf.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile

ICI = os.path.dirname(os.path.abspath(__file__))
PROJET = os.path.dirname(ICI)
APP = (os.path.abspath(sys.argv[1]) if len(sys.argv) > 1
       else os.path.join(PROJET, "dist", "Library Editor"))
TRAVAIL = os.path.join(tempfile.gettempdir(), "le-maj-editeur")
COPIE = os.path.join(TRAVAIL, "app", "Library Editor")
DEPOT = os.path.join(TRAVAIL, "depot")
LOCAL = os.path.join(TRAVAIL, "local")          # %LOCALAPPDATA% de la copie
ok = ko = 0


def v(nom, cond, detail=""):
    global ok, ko
    print(("  ok    " if cond else "  ECHEC ") + nom +
          ("" if cond or not detail else "   " + str(detail)[:400]))
    globals().__setitem__("ok" if cond else "ko", (ok if cond else ko) + 1)


if os.path.isdir(TRAVAIL):
    shutil.rmtree(TRAVAIL)
os.makedirs(DEPOT)
os.makedirs(LOCAL)

print("\n1. Une copie de l application, et un depot local")
if not os.path.isfile(os.path.join(APP, "Library Editor.exe")):
    sys.exit("Application introuvable : %s (python source/build.py)" % APP)
shutil.copytree(APP, COPIE)
archive = os.path.join(DEPOT, "Library-Editor-9.9.9.zip")
with zipfile.ZipFile(archive, "w", zipfile.ZIP_STORED) as z:
    for rep, _, fics in os.walk(COPIE):
        for n in fics:
            p = os.path.join(rep, n)
            z.write(p, os.path.join("Library Editor", os.path.relpath(p, COPIE)))
sha = hashlib.sha256(open(archive, "rb").read()).hexdigest()
m = json.load(open(os.path.join(PROJET, "version.json"), encoding="utf-8"))
m["installeur"] = {"version": "9.9.9",
                   "url": "file:///" + archive.replace("\\", "/").replace(" ", "%20"),
                   "octets": os.path.getsize(archive), "sha256": sha}
m["notes"] = "Essai de mise a jour de l application."
with open(os.path.join(DEPOT, "version.json"), "w", encoding="utf-8") as f:
    json.dump(m, f, ensure_ascii=False)
v("archive d essai fabriquee", os.path.getsize(archive) > 1000000,
  os.path.getsize(archive))

print("\n2. La copie tourne, et voit la version 9.9.9")
env = dict(os.environ, LIBRARY_EDITOR_DEPOT="file:///" + DEPOT.replace("\\", "/") + "/",
           LOCALAPPDATA=LOCAL, APPDATA=os.path.join(TRAVAIL, "roaming"))
proc = subprocess.Popen([os.path.join(COPIE, "Library Editor.exe"),
                         "--sans-fenetre", "--port", "8771"], env=env,
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
time.sleep(6)


def page():
    with urllib.request.urlopen("http://127.0.0.1:8771/", timeout=10) as r:
        return r.read().decode("utf-8")


def api(route, corps=None):
    t = page()
    jeton = t.split('const JETON = "', 1)[1].split('"', 1)[0]
    req = urllib.request.Request(
        "http://127.0.0.1:8771" + route,
        data=json.dumps(corps or {}).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-LE-Jeton": jeton})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))


try:
    e = api("/api/editeur/maj/etat")
    v("version 9.9.9 proposee", e["disponible"] and e["version_distante"] == "9.9.9", e)

    print("\n3. Telechargement, verification, preparation")
    api("/api/editeur/maj/lancer")
    fini = None
    for _ in range(120):
        time.sleep(1)
        t = json.loads(urllib.request.urlopen(
            "http://127.0.0.1:8771/api/tache?j=" + page().split('const JETON = "', 1)[1]
            .split('"', 1)[0], timeout=20).read().decode("utf-8"))
        if t["etat"] != "encours":
            fini = t
            break
    v("la tache aboutit", fini and fini["etat"] == "fini",
      fini and (fini.get("erreur") or fini["etat"]))
    if fini and fini["etat"] == "fini":
        v("version annoncee", fini["resultat"]["version"] == "9.9.9", fini["resultat"])
    cible = os.path.join(LOCAL, "Library Editor", "maj", "9.9.9", "Library Editor")
    v("archive extraite, exe present",
      os.path.isfile(os.path.join(cible, "Library Editor.exe")), cible)
    script = os.path.join(LOCAL, "Library Editor", "maj", "remplacer.ps1")
    texte = open(script, encoding="utf-8").read() if os.path.isfile(script) else ""
    v("script de remplacement ecrit", "robocopy" in texte and "Get-Process" in texte
      and "Start-Process" in texte, texte[:200])
    v("le journal dit ce qui s est passe",
      any("9.9.9" in l["texte"] for l in fini["lignes"]) if fini else False,
      [l["texte"] for l in (fini or {}).get("lignes", [])][:4])
finally:
    # Le script attend la fin de l application pour remplacer : on l arrete
    # AVANT, puis l application. Rien n est remplace, rien n est relance.
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    "Get-CimInstance Win32_Process -Filter \"Name='powershell.exe'\" | "
                    "Where-Object { $_.CommandLine -like '*remplacer.ps1*' } | "
                    "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"],
                   capture_output=True)
    proc.terminate()
    try:
        proc.wait(timeout=20)
    except Exception:
        proc.kill()

v("l application d essai est arretee", proc.poll() is not None)

print("\n4. Le script de remplacement, pour de vrai (vers un dossier d essai)")
# L application est arretee : le script doit recopier la nouvelle version et
# relancer. Ici il recopie vers un dossier neuf et « relance » un .bat temoin.
cible2 = os.path.join(TRAVAIL, "remplacee")
temoin = os.path.join(TRAVAIL, "temoin.bat")
marque = os.path.join(TRAVAIL, "relance.txt")
open(temoin, "w").write("@echo off\r\necho relance > \"%s\"\r\n" % marque)
r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                    script, "-Attendre", str(proc.pid), "-Source",
                    os.path.join(LOCAL, "Library Editor", "maj", "9.9.9", "Library Editor"),
                    "-Cible", cible2, "-Exe", temoin],
                   capture_output=True, text=True, timeout=300)
for _ in range(50):
    if os.path.isfile(marque):
        break
    time.sleep(0.2)
v("la nouvelle version est recopiee",
  os.path.isfile(os.path.join(cible2, "Library Editor.exe"))
  and os.path.isdir(os.path.join(cible2, "_internal")), (r.returncode, r.stdout[-200:]))
v("l application est relancee apres le remplacement", os.path.isfile(marque))
print("\n%d ok, %d echecs" % (ok, ko))
sys.exit(1 if ko else 0)

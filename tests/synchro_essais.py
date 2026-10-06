# -*- coding: utf-8 -*-
"""Eprouve synchro_enligne() contre un faux site en memoire.

    python tests/synchro_essais.py "<racine d une bibliotheque d ESSAI>"

La bibliotheque doit avoir deux projets ProjA et ProjB. Leurs sequences et
rangements sont EFFACES au depart : jamais sur une vraie bibliotheque. Le
serveur du modele y est copie."""
import copy, json, os, shutil, sys
ICI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ICI, "..", "source"))
import le_films as F

R = os.path.abspath(sys.argv[1])
shutil.copy2(os.path.join(ICI, "..", "template", "_app", "serveur.py"),
             os.path.join(R, "_app", "serveur.py"))
srv = F.charger_serveur(R)
# repart d un etat propre
for pr in ("ProjA", "ProjB"):
    d = srv.montages_de(pr)
    if os.path.isdir(d):
        for f in os.listdir(d):
            if f.endswith(".json") or ".avant-synchro" in f:
                os.remove(os.path.join(d, f))
    srv.ecrire_rangement(pr, srv.rangement_propre({"dossiers": [], "ou": {}}))
if os.path.exists(srv.FICHIER_SYNCHRO):
    os.remove(srv.FICHIER_SYNCHRO)


class Faux(object):
    def __init__(self):
        self.m = {}      # (pr, nom) -> montage
        self.r = {}      # pr -> rangement
        self.qui = "essai"

    def appel(self, route, corps=None, delai=0):
        if route == "projets":
            return {"projets": [{"nom": "ProjA"}, {"nom": "ProjB"}, {"nom": "GR-ailleurs"}]}
        if route.startswith("rangement?projet="):
            pr = route.split("=", 1)[1]
            return copy.deepcopy(self.r.get(pr, {"dossiers": [], "ou": {}}))
        if route == "rangement":
            r = srv.rangement_propre(corps)
            self.r[corps["projet"]] = {"dossiers": r["dossiers"], "ou": r["ou"]}
            return dict(self.r[corps["projet"]], ok=True)
        if route == "montage":
            self.m[(corps["projet"], corps["nom"])] = copy.deepcopy(corps["montage"])
            return {"ok": True}
        raise RuntimeError("route " + route)

    def montages(self, pr):
        return [{"nom": n} for (p, n) in self.m if p == pr]

    def montage(self, pr, nom):
        return copy.deepcopy(self.m.get((pr, nom)))


ok = ko = 0


def v(nom, cond, det=""):
    global ok, ko
    if cond:
        ok += 1; print("  ok    " + nom)
    else:
        ko += 1; print("  ECHEC " + nom + "  " + str(det))


f = Faux()
mA = {"version": 5, "clips": [{"uid": 1, "piste": "V1"}], "rendu": {"plans": [1]}}
srv._ecrire_montage_local("ProjA", "local1", mA)
f.m[("ProjA", "enligne1")] = {"version": 5, "clips": [{"uid": 9, "piste": "V1"}]}
f.r["ProjA"] = {"dossiers": ["Vol", "ice"], "ou": {"aaaaaaaaaaaa": "Vol"}}

r = srv.synchro_enligne(f)
v("premiere synchro : la locale part en ligne", "ProjA / local1" in r["pousses"], r)
v("premiere synchro : celle du site arrive ici",
  srv._montage_local("ProjA", "enligne1") is not None, r)
v("rangement vide ici : celui du site arrive",
  srv.lire_rangement("ProjA")["dossiers"] == ["Vol", "ice"], srv.lire_rangement("ProjA"))
v("un projet absent d ici est signale, pas cree", r["absents"] == ["GR-ailleurs"], r["absents"])

r = srv.synchro_enligne(f)
v("seconde synchro sans changement : rien ne bouge",
  not r["tires"] and not r["pousses"] and not r["conflits"], r)

# change en ligne seulement
f.m[("ProjA", "enligne1")]["clips"].append({"uid": 10})
r = srv.synchro_enligne(f)
v("change en ligne : on le ramene", r["tires"] == ["ProjA / enligne1"], r)
v("la copie d avant est gardee", os.path.isfile(os.path.join(
  srv.montages_de("ProjA"), "enligne1.json.avant-synchro")))

# change ici seulement
m = srv._montage_local("ProjA", "local1"); m["clips"].append({"uid": 2})
srv._ecrire_montage_local("ProjA", "local1", m)
r = srv.synchro_enligne(f)
v("change ici : on l envoie", r["pousses"] == ["ProjA / local1"], r)
v("le site a bien la nouvelle", len(f.m[("ProjA", "local1")]["clips"]) == 2)

# change des deux cotes
m = srv._montage_local("ProjA", "local1"); m["clips"].append({"uid": 3})
srv._ecrire_montage_local("ProjA", "local1", m)
f.m[("ProjA", "local1")]["clips"].append({"uid": 4})
r = srv.synchro_enligne(f)
v("change des deux cotes : conflit, rien d ecrase", len(r["conflits"]) == 1, r)
v("la version d ici est intacte",
  [c["uid"] for c in srv._montage_local("ProjA", "local1")["clips"]] == [1, 2, 3])
autre = [n for n in os.listdir(srv.montages_de("ProjA")) if n.startswith("local1 (online")]
v("la version du site est gardee sous un autre nom", len(autre) == 1, autre)

# rangements : les deux changent -> fusion
srv.ecrire_rangement("ProjA", srv.rangement_propre(
    {"dossiers": ["Vol", "ice", "marine"], "ou": {"aaaaaaaaaaaa": "Vol", "bbbbbbbbbbbb": "marine"}}))
f.r["ProjA"] = {"dossiers": ["Vol", "ice", "space"], "ou": {"aaaaaaaaaaaa": "space", "cccccccccccc": "ice"}}
r = srv.synchro_enligne(f)
loc = srv.lire_rangement("ProjA")
v("rangements changes des deux cotes : fusion", r["fusions"] == ["ProjA / My folders"], r)
v("la fusion garde tous les dossiers, dans l ordre d ici",
  loc["dossiers"] == ["Vol", "ice", "marine", "space"], loc["dossiers"])
v("un rush range des deux cotes : le site gagne", loc["ou"].get("aaaaaaaaaaaa") == "space", loc["ou"])
v("rien n est perdu des deux cotes",
  loc["ou"].get("bbbbbbbbbbbb") == "marine" and loc["ou"].get("cccccccccccc") == "ice", loc["ou"])
v("le site a la meme fusion", f.r["ProjA"]["dossiers"] == loc["dossiers"], f.r["ProjA"])
r = srv.synchro_enligne(f)
v("apres fusion, une synchro de plus ne bouge rien",
  not r["tires"] and not r["pousses"] and not r["fusions"] and not r["conflits"], r)

# efface en ligne apres synchro : on ne le renvoie pas, on ne l efface pas ici
del f.m[("ProjA", "enligne1")]
r = srv.synchro_enligne(f)
v("efface en ligne : ni renvoye, ni efface ici",
  ("ProjA", "enligne1") not in f.m and srv._montage_local("ProjA", "enligne1") is not None, r)

print("\n%d verifications passees, %d echec(s)" % (ok, ko))
sys.exit(1 if ko else 0)

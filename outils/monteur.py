# -*- coding: utf-8 -*-
"""Monter dans une bibliotheque video sans passer par la page.

    python outils/monteur.py bibliotheques
    python outils/monteur.py projets   "EP-06-Bambozoo H34"
    python outils/monteur.py catalogue "EP-06" --projet audio --cherche moteur
    python outils/monteur.py montages  "EP-06"
    python outils/monteur.py lire      "EP-06" --projet audio --nom "claude - essai"
    python outils/monteur.py ecrire    "EP-06" plan.json
    python outils/monteur.py --mcp                 (serveur MCP, entree/sortie standard)

Une sequence ecrite ici porte TOUJOURS le prefixe « claude - » : au premier
coup d oeil sur la liste des sequences, David sait ce qui vient de moi.

Rien n est demarre, aucun port n est ouvert : on importe le serveur.py de la
bibliotheque visee — c est un module de configuration tant qu on ne lance pas
demarrer() — et on se sert de SES fonctions pour trouver les catalogues et le
dossier des sequences. Une seule verite sur les chemins, la sienne.

Ce qui est ecrit : un fichier dans <projet>/_projet/_montages/. Jamais rien
dans les dossiers de rushes, jamais un catalogue, jamais une sequence qui ne
porte pas le prefixe.
"""
import argparse
import datetime
import hashlib
import importlib.util
import io
import json
import os
import re
import sys

NOM_APP = "Library Editor"
PREFIXE = "claude - "
VERSION_MONTAGE = 5

# Les pistes d un montage neuf, si le plan n en demande pas d autres.
PISTES_DEFAUT = [{"id": "V1", "type": "v", "mute": False, "solo": False},
                 {"id": "A1", "type": "a", "mute": False, "solo": False},
                 {"id": "M1", "type": "m", "mute": False, "solo": False}]


class Refus(Exception):
    """Une demande impossible, dite en une phrase."""


# ---------------------------------------------------------------------------
#  Trouver les bibliotheques : le registre de Library Editor
# ---------------------------------------------------------------------------
def fichier_reglages():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, NOM_APP, "reglages.json")


def lire_json(chemin, defaut=None):
    try:
        with io.open(chemin, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return defaut


def bibliotheques():
    """Les bibliotheques connues, la plus recente d abord. On garde celles
    qui existent encore sur le disque et qui ont une table de montage."""
    r = lire_json(fichier_reglages(), {}) or {}
    out = []
    for x in r.get("recents") or []:
        chemin = x.get("chemin") or ""
        if not chemin or not os.path.isdir(chemin):
            continue
        app = os.path.join(chemin, "_app", "serveur.py")
        out.append({
            "titre": x.get("titre") or os.path.basename(chemin),
            "dossier": os.path.basename(chemin),
            "chemin": chemin,
            "genre": x.get("genre") or "",
            "port": x.get("port"),
            "montage": os.path.isfile(app),   # bibliotheque de films
        })
    return out


def trouver(nom):
    """La bibliotheque que designe ce nom : son titre, son dossier, ou un
    morceau de l un des deux. Ambigu : on le dit, avec la liste."""
    if not nom:
        raise Refus("Nommez la bibliotheque (essayez « bibliotheques »).")
    if os.path.isdir(nom) and os.path.isfile(
            os.path.join(nom, "_app", "serveur.py")):
        return {"titre": os.path.basename(nom), "dossier": os.path.basename(nom),
                "chemin": os.path.abspath(nom), "genre": "films", "port": None,
                "montage": True}
    l = [b for b in bibliotheques() if b["montage"]]
    bas = nom.strip().lower()
    exact = [b for b in l if bas in (b["titre"].lower(), b["dossier"].lower())]
    if len(exact) == 1:
        return exact[0]
    partiel = [b for b in l if bas in b["titre"].lower()
               or bas in b["dossier"].lower()]
    if len(partiel) == 1:
        return partiel[0]
    if not partiel:
        raise Refus("Aucune bibliotheque de films ne repond a « %s ». Connues : %s"
                    % (nom, ", ".join(b["titre"] for b in l) or "aucune"))
    raise Refus("« %s » designe %d bibliotheques : %s"
                % (nom, len(partiel), ", ".join(b["titre"] for b in partiel)))


# ---------------------------------------------------------------------------
#  Le serveur de la bibliotheque, comme module
# ---------------------------------------------------------------------------
_MODULES = {}


def moteur(biblio):
    """Le serveur.py de CETTE bibliotheque, importe sans rien demarrer : on
    herite de ses chemins, de ses reglages et de sa notion de projet."""
    chemin = biblio["chemin"]
    if chemin in _MODULES:
        return _MODULES[chemin]
    src = os.path.join(chemin, "_app", "serveur.py")
    if not os.path.isfile(src):
        raise Refus("Pas de table de montage dans %s" % chemin)
    nom = "serveur_" + hashlib.md5(chemin.encode("utf-8")).hexdigest()[:10]
    spec = importlib.util.spec_from_file_location(nom, src)
    m = importlib.util.module_from_spec(spec)
    sys.modules[nom] = m
    spec.loader.exec_module(m)
    _MODULES[chemin] = m
    return m


def projets(biblio):
    m = moteur(biblio)
    out = []
    partagees = set(m.biblis_disque())
    for nom in m.projets_disque() + m.biblis_disque():
        cat = m.lire_catalogue(nom) if m.catalogue_existe(nom) else None
        films = (cat or {}).get("films") or []
        vivants = [f for f in films if not f.get("absent")]
        out.append({
            "nom": nom,
            # Une bibliotheque partagee (musique, sons) n accueille jamais une
            # sequence : c est une reserve, pas un lieu de travail.
            "genre": "bibliotheque" if nom in partagees else "projet",
            "scanne": bool(cat),
            "clips": len(vivants),
            "sons": sum(1 for f in vivants if f.get("son_seul")),
            "images": sum(1 for f in vivants if f.get("image")),
            "sequences": len([x for x in _sequences(m, nom)]),
        })
    return out


def _sequences(m, projet):
    d = m.montages_de(projet)
    if not os.path.isdir(d):
        return []
    return sorted(x[:-5] for x in os.listdir(d) if x.lower().endswith(".json"))


def nom_de_projet(biblio, projet):
    """Le projet que designe ce nom, exact ou partiel."""
    l = projets(biblio)
    bas = (projet or "").strip().lower()
    for p in l:
        if p["nom"].lower() == bas:
            return p["nom"]
    proches = [p for p in l if bas and bas in p["nom"].lower()]
    if len(proches) == 1:
        return proches[0]["nom"]
    raise Refus("Projet inconnu : « %s ». Il y a : %s"
                % (projet, ", ".join(p["nom"] for p in l) or "rien"))


def projet_par_defaut(biblio, projet=None):
    """Pour lire : le projet nomme, sinon le seul qui ait des clips."""
    if projet:
        return nom_de_projet(biblio, projet)
    pleins = [p for p in projets(biblio) if p["clips"]]
    if len(pleins) == 1:
        return pleins[0]["nom"]
    raise Refus("Dites le projet : %s"
                % ", ".join(p["nom"] for p in projets(biblio)))


def hote_par_defaut(biblio, demande, clips):
    """Ou la sequence s enregistre. Jamais dans une bibliotheque partagee :
    c est la regle de l application, on la tient aussi ici. A defaut de
    consigne, le projet du premier plan image."""
    l = projets(biblio)
    vrais = {p["nom"] for p in l if p["genre"] == "projet"}
    if demande:
        n = nom_de_projet(biblio, demande)
        if n not in vrais:
            raise Refus("« %s » est une reserve partagee : une sequence ne s y "
                        "enregistre pas. Choisissez un projet (%s)."
                        % (n, ", ".join(sorted(vrais))))
        return n
    for c in clips:
        if c.get("pj") in vrais:
            return c["pj"]
    pleins = [p["nom"] for p in l if p["clips"] and p["nom"] in vrais]
    if pleins:
        return pleins[0]
    raise Refus("Aucun projet ou enregistrer la sequence.")


# ---------------------------------------------------------------------------
#  Le catalogue
# ---------------------------------------------------------------------------
def fiches(biblio, projet):
    """Les fiches d un projet, chacune sachant d ou elle vient."""
    m = moteur(biblio)
    cat = m.lire_catalogue(projet) if m.catalogue_existe(projet) else {}
    out = []
    for f in cat.get("films") or []:
        f = dict(f)
        f["_pj"] = projet
        out.append(f)
    return out


def toutes_fiches(biblio, projet=None):
    """Tout ce qu on peut poser sur une timeline : un montage melange les
    projets (l image d un cote, la musique de l autre)."""
    if projet:
        return fiches(biblio, projet)
    out = []
    for p in projets(biblio):
        out.extend(fiches(biblio, p["nom"]))
    return out


def catalogue(biblio, projet=None, cherche="", dossier="", genre="",
              maximum=120):
    """Les fiches, en court. « genre » : video, son, image. Sans projet, on
    cherche dans toute la bibliotheque."""
    out = []
    bas = (cherche or "").strip().lower()
    dos = (dossier or "").strip().lower()
    for f in toutes_fiches(biblio, projet):
        if f.get("absent"):
            continue
        if bas and bas not in (f.get("nom") or "").lower():
            continue
        if dos and dos not in (f.get("dossier") or "").lower():
            continue
        if genre == "son" and not f.get("son_seul"):
            continue
        if genre == "image" and not f.get("image"):
            continue
        if genre == "video" and (f.get("son_seul") or f.get("image")):
            continue
        out.append({
            "id": f.get("id"), "nom": f.get("nom"),
            "projet": f.get("_pj") or projet or "",
            "dossier": f.get("dossier") or "",
            "s": round(float(f.get("s") or 0), 2),
            "format": ("%dx%d" % (f["w"], f["h"])) if f.get("w") else "",
            "genre": "son" if f.get("son_seul")
                     else ("image" if f.get("image") else "video"),
            "muet": (not f.get("a")) and not f.get("son_seul")
                    and not f.get("image"),
            "fav": bool(f.get("fav")), "coul": f.get("coul") or 0,
        })
    out.sort(key=lambda x: (x["projet"], x["dossier"], x["nom"]))
    return {"projet": projet or "toute la bibliotheque", "total": len(out),
            "fiches": out[:maximum], "tronque": len(out) > maximum}


def _cherche_rush(index, demande, projet=None):
    """Un rush designe par son identifiant, son nom exact, ou un morceau de
    nom, dans toute la bibliotheque ou dans un projet donne. Ambigu ou
    absent : on refuse en disant pourquoi."""
    d = str(demande or "").strip()
    if not d:
        raise Refus("Un plan sans rush : donnez « rush », « texte » ou « couleur ».")
    if d in index["par_id"] and not projet:
        return index["par_id"][d]
    films = [f for f in index["films"]
             if not projet or f.get("_pj", "").lower() == projet.lower()]
    if projet and d in index["par_id"] and index["par_id"][d] in films:
        return index["par_id"][d]
    bas = d.lower()
    exact = [f for f in films if (f.get("nom") or "").lower() == bas]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise Refus("« %s » : %d rushes portent ce nom exact (%s). Donnez l identifiant."
                    % (d, len(exact), ", ".join(f["id"] for f in exact[:6])))
    partiel = [f for f in films if bas in (f.get("nom") or "").lower()]
    if len(partiel) == 1:
        return partiel[0]
    if not partiel:
        raise Refus("Aucun rush ne repond a « %s »%s."
                    % (d, " dans " + projet if projet else ""))
    raise Refus("« %s » designe %d rushes : %s. Precisez (identifiant, ou "
                "« projet »)." % (d, len(partiel), ", ".join(
                    "%s [%s]" % (f.get("nom") or "?", f.get("_pj"))
                    for f in partiel[:8])))


# ---------------------------------------------------------------------------
#  Lire une sequence : une table, pas du JSON
# ---------------------------------------------------------------------------
def _tc(s):
    s = max(0.0, float(s or 0))
    return "%02d:%02d:%05.2f" % (int(s // 3600), int(s % 3600 // 60), s % 60)


def ou_est(biblio, nom, projet=None):
    """Dans quel projet vit cette sequence. Sans consigne, on regarde
    partout : David dit un nom, pas un emplacement."""
    m = moteur(biblio)
    propre = m.nom_propre(nom or "")
    candidats = [projet] if projet else [p["nom"] for p in projets(biblio)]
    for pr in candidats:
        if propre in _sequences(m, pr):
            return pr
    toutes = [(p["nom"], s) for p in projets(biblio)
              for s in _sequences(m, p["nom"])]
    raise Refus("Pas de sequence « %s »%s. Il y a : %s"
                % (nom, " dans " + projet if projet else "",
                   ", ".join("%s [%s]" % (s, p) for p, s in toutes) or "rien"))


def lire_montage(biblio, projet, nom):
    m = moteur(biblio)
    projet = ou_est(biblio, nom, projet)
    f = os.path.join(m.montages_de(projet), m.nom_propre(nom) + ".json")
    mo = lire_json(f, {}) or {}
    par_id = {x["id"]: x for x in toutes_fiches(biblio)}
    lignes = []
    for c in mo.get("clips") or []:
        fiche = par_id.get(c.get("film")) or {}
        v = abs(float(c.get("vitesse") or 1)) or 1
        duree = max(0.0, (float(c.get("o") or 0) - float(c.get("e") or 0)) / v)
        lignes.append({
            "piste": c.get("piste"),
            "debut": round(float(c.get("t0") or 0), 2),
            "fin": round(float(c.get("t0") or 0) + duree, 2),
            "duree": round(duree, 2),
            "quoi": (c.get("genre") or fiche.get("nom")
                     or c.get("fichier") or "?"),
            "entree": round(float(c.get("e") or 0), 2),
            "sortie": round(float(c.get("o") or 0), 2),
            "vitesse": round(float(c.get("vitesse") or 1), 3),
            "envers": bool(c.get("rev")),
            "fondus": [round(float(c.get("fi") or 0), 2),
                       round(float(c.get("fo") or 0), 2)],
            "opacite": round(float(c.get("opac", 1)), 2),
            "gain": round(float(c.get("gain", 1)), 2),
        })
    lignes.sort(key=lambda x: (x["piste"], x["debut"]))
    p = mo.get("projet") or {}
    return {
        "nom": nom, "projet": projet, "fichier": f,
        "format": "%dx%d" % (p.get("w") or 0, p.get("h") or 0),
        "fps": p.get("fps") or mo.get("fps"),
        "duree": round(max([x["fin"] for x in lignes] or [0]), 2),
        "pistes": [x["id"] for x in (mo.get("pistes") or PISTES_DEFAUT)],
        "blocs": lignes,
    }


# ---------------------------------------------------------------------------
#  Ecrire une sequence
# ---------------------------------------------------------------------------
def _type_piste(pid):
    t = (pid or "V1")[0].upper()
    return {"V": "v", "A": "a", "M": "m"}.get(t, "v")


def _pistes_du_plan(plans, demandees):
    """Les pistes citees par les plans, plus celles demandees, plus les trois
    de base. L ordre de l application : les V, puis les A, puis les M."""
    ids = []
    for x in (demandees or []) + [p.get("piste") or "V1" for p in plans]:
        x = str(x).upper()
        if x not in ids:
            ids.append(x)
    for d in ("V1", "A1", "M1"):
        if d not in ids:
            ids.append(d)
    ordre = {"v": 0, "a": 1, "m": 2}
    ids.sort(key=lambda x: (ordre[_type_piste(x)],
                            int(re.sub(r"\D", "", x) or 0)))
    return [{"id": x, "type": _type_piste(x), "mute": False, "solo": False}
            for x in ids]


def construire(biblio, nom, plan, hote_demande=None):
    """Le plan (des phrases simples) devient un vrai montage : identifiants,
    debuts enchaines, points d entree et de sortie, fondus. Les rushes sont
    cherches dans TOUTE la bibliotheque ; chaque bloc garde son projet."""
    m = moteur(biblio)
    films = [f for f in toutes_fiches(biblio) if not f.get("absent")]
    index = {"films": films, "par_id": {f["id"]: f for f in films}}
    plans = plan.get("plans") or plan.get("blocs") or []
    if not plans:
        raise Refus("Le plan ne contient aucun bloc.")

    reglages = m.REGLAGES or {}
    fmt = plan.get("format") or reglages.get("format") or [1280, 720]
    fps = float(plan.get("fps") or reglages.get("fps") or 24)
    pistes = _pistes_du_plan(plans, plan.get("pistes"))
    connues = {p["id"] for p in pistes}

    clips, fin_de = [], {}
    uid, lien = 1, 1
    avertissements = []
    for i, p in enumerate(plans, 1):
        piste = str(p.get("piste") or "V1").upper()
        if piste not in connues:
            raise Refus("Bloc %d : piste inconnue « %s »." % (i, piste))
        type_piste = _type_piste(piste)
        c = {"uid": uid, "piste": piste, "film": "", "t0": 0.0, "e": 0.0,
             "o": 1.0, "ech": 1, "dx": 0, "dy": 0, "mode": p.get("cadrage")
             or "contain", "gain": float(p.get("gain", 1)),
             "opac": float(p.get("opacite", 1)),
             "vitesse": abs(float(p.get("vitesse", 1))) or 1,
             "couleur": int(p.get("couleur", 0)), "fi": 0.0, "fo": 0.0,
             "lien": None}
        uid += 1

        if p.get("texte") is not None:
            c["genre"] = "texte"
            c["txt"] = str(p["texte"])
            c["police"] = p.get("police") or "noir"
            c["taille"] = float(p.get("taille", 7))
            c["teinte"] = p.get("teinte") or "#ffffff"
            source = float(p.get("duree", 3))
        elif p.get("couleur_fond") or p.get("fond"):
            c["genre"] = "couleur"
            c["fond"] = p.get("couleur_fond") or p.get("fond")
            source = float(p.get("duree", 2))
        else:
            f = _cherche_rush(index, p.get("rush") or p.get("nom"),
                              p.get("projet"))
            est_son = bool(f.get("son_seul"))
            est_image = bool(f.get("image"))
            if type_piste in ("a", "m") and not est_son:
                raise Refus("Bloc %d : « %s » n est pas un fichier de son, il "
                            "ne peut pas aller sur %s." % (i, f["nom"], piste))
            if type_piste == "v" and est_son:
                raise Refus("Bloc %d : « %s » est un son seul, il ne peut pas "
                            "aller sur une piste image." % (i, f["nom"]))
            c["film"] = f["id"]
            c["pj"] = f.get("_pj") or ""
            c["fichier"] = f.get("rel") or ""
            source = float(f.get("s") or 0) or (m.DUREE_IMAGE if est_image else 0)
            if est_image:
                c["_libre"] = True

        # entree / sortie dans la source
        e = float(p.get("entree", 0))
        if p.get("sortie") is not None:
            o = float(p["sortie"])
        elif p.get("duree") is not None:
            o = e + float(p["duree"]) * c["vitesse"]
        else:
            o = source
        if o <= e:
            raise Refus("Bloc %d : sortie (%.2f) avant entree (%.2f)." % (i, o, e))
        # Une image ou un calque n a pas de duree derriere : on ne borne pas.
        if source and not c.get("_libre") and not c.get("genre"):
            if o > source + 1e-6:
                avertissements.append(
                    "bloc %d : sortie ramenee a %.2f s (le rush fait %.2f s)"
                    % (i, source, source))
                o = source
        c.pop("_libre", None)
        c["e"], c["o"] = round(e, 3), round(o, 3)
        duree = (o - e) / c["vitesse"]

        # debut sur la timeline : dit, ou a la suite de la piste
        if p.get("debut") is not None:
            t0 = max(0.0, float(p["debut"]))
        else:
            t0 = fin_de.get(piste, 0.0)
        c["t0"] = round(t0, 3)
        fin_de[piste] = max(fin_de.get(piste, 0.0), t0 + duree)

        fi = float(p.get("fondu_in", p.get("fondu", 0)) or 0)
        fo = float(p.get("fondu_out", p.get("fondu", 0)) or 0)
        c["fi"] = round(min(fi, duree / 2), 3)
        c["fo"] = round(min(fo, duree / 2), 3)
        if p.get("envers"):
            c["rev"] = True
        clips.append(c)

    hote = hote_par_defaut(biblio, hote_demande, clips)
    montage = {
        "version": VERSION_MONTAGE,
        "genere": datetime.datetime.now().isoformat(timespec="seconds"),
        "projet": {"nom": nom, "w": int(fmt[0]), "h": int(fmt[1]), "fps": fps},
        "hote": hote,
        "projets": sorted({c.get("pj") for c in clips if c.get("pj")}),
        "fps": fps, "format": {"w": int(fmt[0]), "h": int(fmt[1])},
        "tIn": plan.get("tIn"), "tOut": plan.get("tOut"),
        "PPS": plan.get("PPS") or 40,
        "marqueurs": plan.get("marqueurs") or [],
        "pistes": pistes,
        "clips": clips,
        # D ou vient cette sequence : l application n en fait rien, mais un
        # humain qui ouvre le fichier doit pouvoir le savoir.
        "auteur": "claude",
        "theme": plan.get("theme") or "",
    }
    return montage, hote, avertissements


def nom_claude(nom):
    """Le prefixe n est pas negociable : c est la seule marque qui dit a David
    que cette sequence vient de moi."""
    n = (nom or "").strip()
    bas = n.lower()
    if bas.startswith(PREFIXE):
        n = n[len(PREFIXE):].strip()
    elif bas.startswith("claude"):
        n = n[len("claude"):].lstrip(" -_").strip()
    return PREFIXE + (n or "sequence")


def ecrire(biblio, nom, plan, hote=None, ecraser=False):
    m = moteur(biblio)
    nom = m.nom_propre(nom_claude(nom))
    montage, projet, avertissements = construire(biblio, nom, plan, hote)
    montage["projet"]["nom"] = nom
    dossier = m.montages_de(projet)
    os.makedirs(dossier, exist_ok=True)
    cible = os.path.join(dossier, nom + ".json")
    if os.path.isfile(cible):
        if not ecraser:
            raise Refus("« %s » existe deja. Donnez un autre nom, ou "
                        "ecraser=true (l ancienne est sauvegardee)." % nom)
        sauve = cible + ".avant-claude"
        with io.open(cible, encoding="utf-8") as f:
            ancien = f.read()
        with io.open(sauve, "w", encoding="utf-8", newline="\n") as f:
            f.write(ancien)
        avertissements.append("ancienne version gardee en %s"
                              % os.path.basename(sauve))
    with io.open(cible, "w", encoding="utf-8", newline="\n") as f:
        json.dump(montage, f, ensure_ascii=False, indent=1)
        f.write("\n")
    duree = max([c["t0"] + (c["o"] - c["e"]) / c["vitesse"] for c in
                 montage["clips"]] or [0])
    return {"ok": True, "nom": nom, "projet": projet, "fichier": cible,
            "blocs": len(montage["clips"]), "duree": round(duree, 2),
            "pistes": [p["id"] for p in montage["pistes"]],
            "avertissements": avertissements,
            "ouvrir": "Dans la bibliotheque : Sequences > « %s »" % nom}


# ---------------------------------------------------------------------------
#  MCP : les memes gestes, par l entree standard
# ---------------------------------------------------------------------------
OUTILS = [
    {"name": "bibliotheques",
     "description": "Les bibliotheques video connues de Library Editor "
                    "(titre, dossier, chemin). Commencer par la.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "projets",
     "description": "Les projets d une bibliotheque : nombre de clips, de "
                    "sons, d images, de sequences.",
     "inputSchema": {"type": "object", "properties": {
         "bibliotheque": {"type": "string"}}, "required": ["bibliotheque"]}},
    {"name": "catalogue",
     "description": "Les rushes d un projet, en court. Filtres : cherche (dans "
                    "le nom), dossier, genre (video|son|image).",
     "inputSchema": {"type": "object", "properties": {
         "bibliotheque": {"type": "string"}, "projet": {"type": "string"},
         "cherche": {"type": "string"}, "dossier": {"type": "string"},
         "genre": {"type": "string", "enum": ["video", "son", "image"]},
         "maximum": {"type": "integer"}}, "required": ["bibliotheque"]}},
    {"name": "sequences",
     "description": "Les sequences deja enregistrees dans un projet.",
     "inputSchema": {"type": "object", "properties": {
         "bibliotheque": {"type": "string"}, "projet": {"type": "string"}},
         "required": ["bibliotheque"]}},
    {"name": "lire_sequence",
     "description": "Une sequence, bloc par bloc (piste, debut, fin, rush, "
                    "entree/sortie, vitesse, fondus).",
     "inputSchema": {"type": "object", "properties": {
         "bibliotheque": {"type": "string"}, "projet": {"type": "string"},
         "nom": {"type": "string"}}, "required": ["bibliotheque", "nom"]}},
    {"name": "ecrire_sequence",
     "description": "Ecrit une sequence montee. Le nom recoit TOUJOURS le "
                    "prefixe « claude - ». Chaque bloc : rush (identifiant ou "
                    "nom) ou texte ou fond, piste (V1/A1/M1...), entree, "
                    "sortie ou duree, debut (sinon a la suite), fondu_in, "
                    "fondu_out, vitesse, opacite, gain, couleur, cadrage.",
     "inputSchema": {"type": "object", "properties": {
         "bibliotheque": {"type": "string"}, "projet": {"type": "string"},
         "nom": {"type": "string"}, "theme": {"type": "string"},
         "format": {"type": "array", "items": {"type": "number"}},
         "fps": {"type": "number"},
         "ecraser": {"type": "boolean"},
         "plans": {"type": "array", "items": {"type": "object"}}},
         "required": ["bibliotheque", "nom", "plans"]}},
]


def appeler(nom, a):
    b = lambda: trouver(a.get("bibliotheque"))            # noqa: E731
    if nom == "bibliotheques":
        return {"bibliotheques": bibliotheques()}
    if nom == "projets":
        return {"projets": projets(b())}
    if nom == "catalogue":
        bb = b()
        pr = nom_de_projet(bb, a["projet"]) if a.get("projet") else None
        return catalogue(bb, pr, a.get("cherche", ""), a.get("dossier", ""),
                         a.get("genre", ""), int(a.get("maximum") or 120))
    if nom == "sequences":
        bb = b()
        m = moteur(bb)
        if a.get("projet"):
            pr = nom_de_projet(bb, a["projet"])
            return {"projet": pr, "sequences": _sequences(m, pr)}
        return {"sequences": [{"projet": p["nom"], "nom": s}
                              for p in projets(bb)
                              for s in _sequences(m, p["nom"])]}
    if nom == "lire_sequence":
        bb = b()
        pr = nom_de_projet(bb, a["projet"]) if a.get("projet") else None
        return lire_montage(bb, pr, a.get("nom"))
    if nom == "ecrire_sequence":
        bb = b()
        return ecrire(bb, a.get("nom"), a, a.get("projet"),
                      bool(a.get("ecraser")))
    raise Refus("Outil inconnu : %s" % nom)


def _en_utf8(strict=True):
    """Windows parle cp1252 par defaut : un « dans une phrase suffit a casser
    le dialogue MCP (verifie). On impose l UTF-8 des deux cotes."""
    for flux, sens in ((sys.stdout, "w"), (sys.stderr, "w"), (sys.stdin, "r")):
        try:
            flux.reconfigure(encoding="utf-8",
                             errors=None if strict else "replace",
                             **({"newline": chr(10)} if sens == "w" else {}))
        except Exception:
            pass


def _repondre(o):
    sys.stdout.write(json.dumps(o, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def mcp():
    """Le dialogue MCP, a la main : la bibliotheque standard suffit."""
    _en_utf8()
    for ligne in sys.stdin:
        ligne = ligne.strip()
        if not ligne:
            continue
        try:
            msg = json.loads(ligne)
        except Exception:
            continue
        mid, methode = msg.get("id"), msg.get("method")
        if methode == "initialize":
            _repondre({"jsonrpc": "2.0", "id": mid, "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "bibliotheques-video",
                               "version": "1.0.0"}}})
        elif methode == "tools/list":
            _repondre({"jsonrpc": "2.0", "id": mid,
                       "result": {"tools": OUTILS}})
        elif methode == "tools/call":
            p = msg.get("params") or {}
            try:
                r = appeler(p.get("name"), p.get("arguments") or {})
                texte = json.dumps(r, ensure_ascii=False, indent=1)
                erreur = False
            except Refus as e:
                texte, erreur = str(e), True
            except Exception as e:                       # noqa: BLE001
                texte, erreur = "%s : %s" % (type(e).__name__, e), True
            _repondre({"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text", "text": texte}],
                "isError": erreur}})
        elif methode == "ping":
            _repondre({"jsonrpc": "2.0", "id": mid, "result": {}})
        elif mid is not None:
            _repondre({"jsonrpc": "2.0", "id": mid, "error": {
                "code": -32601, "message": "methode inconnue : %s" % methode}})


# ---------------------------------------------------------------------------
#  Ligne de commande
# ---------------------------------------------------------------------------
def _table(lignes, colonnes):
    if not lignes:
        return "  (rien)"
    larg = [max(len(str(c)), max(len(str(l.get(c, ""))) for l in lignes))
            for c in colonnes]
    out = ["  " + "  ".join(str(c).ljust(w) for c, w in zip(colonnes, larg))]
    out.append("  " + "  ".join("-" * w for w in larg))
    for l in lignes:
        out.append("  " + "  ".join(str(l.get(c, "")).ljust(w)
                                    for c, w in zip(colonnes, larg)))
    return "\n".join(out)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("action", nargs="?", default="bibliotheques")
    p.add_argument("cible", nargs="?", default="")
    p.add_argument("fichier", nargs="?", default="")
    p.add_argument("--projet", default="")
    p.add_argument("--nom", default="")
    p.add_argument("--cherche", default="")
    p.add_argument("--dossier", default="")
    p.add_argument("--genre", default="")
    p.add_argument("--maximum", type=int, default=120)
    p.add_argument("--ecraser", action="store_true")
    p.add_argument("--json", action="store_true")
    p.add_argument("--mcp", action="store_true")
    a = p.parse_args(argv)
    # En ligne de commande, une console qui ne sait pas afficher un guillemet
    # ne doit pas faire echouer la commande : on remplace, on ne casse pas.
    _en_utf8(strict=False)

    if a.mcp:
        mcp()
        return 0

    try:
        if a.action == "bibliotheques":
            r = {"bibliotheques": bibliotheques()}
            if not a.json:
                print(_table([{k: b[k] for k in ("titre", "genre", "port",
                                                 "chemin")}
                              for b in r["bibliotheques"]],
                             ["titre", "genre", "port", "chemin"]))
                return 0
        elif a.action == "projets":
            r = {"projets": projets(trouver(a.cible))}
            if not a.json:
                print(_table(r["projets"],
                             ["nom", "clips", "sons", "images", "sequences"]))
                return 0
        elif a.action == "catalogue":
            b = trouver(a.cible)
            pr = nom_de_projet(b, a.projet) if a.projet else None
            r = catalogue(b, pr, a.cherche, a.dossier, a.genre, a.maximum)
            if not a.json:
                print("%s : %d fiches%s" % (r["projet"], r["total"],
                                            " (tronque)" if r["tronque"] else ""))
                print(_table(r["fiches"],
                             ["id", "nom", "projet", "dossier", "s", "genre",
                              "format"]))
                return 0
        elif a.action in ("montages", "sequences"):
            b = trouver(a.cible)
            m = moteur(b)
            pres = [nom_de_projet(b, a.projet)] if a.projet \
                else [p["nom"] for p in projets(b)]
            r = {"sequences": [{"projet": pr, "nom": s}
                               for pr in pres for s in _sequences(m, pr)]}
            if not a.json:
                print(_table(r["sequences"], ["projet", "nom"]))
                return 0
        elif a.action == "lire":
            b = trouver(a.cible)
            pr = nom_de_projet(b, a.projet) if a.projet else None
            r = lire_montage(b, pr, a.nom or a.fichier)
            if not a.json:
                print("%s · %s · %s · %.2f s"
                      % (r["nom"], r["projet"], r["format"], r["duree"]))
                print(_table(r["blocs"], ["piste", "debut", "fin", "duree",
                                          "quoi", "entree", "sortie",
                                          "vitesse", "fondus"]))
                return 0
        elif a.action == "ecrire":
            b = trouver(a.cible)
            plan = lire_json(a.fichier)
            if plan is None:
                raise Refus("Plan illisible : %s" % a.fichier)
            r = ecrire(b, a.nom or plan.get("nom"), plan,
                       a.projet or plan.get("projet"),
                       a.ecraser or bool(plan.get("ecraser")))
            if not a.json:
                print("Ecrite : %s  (projet %s)" % (r["fichier"], r["projet"]))
                print("  %d blocs · %.2f s · pistes %s"
                      % (r["blocs"], r["duree"], ", ".join(r["pistes"])))
                for x in r["avertissements"]:
                    print("  ! " + x)
                return 0
        else:
            raise Refus("Action inconnue : %s" % a.action)
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return 0
    except Refus as e:
        print("Refus : %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

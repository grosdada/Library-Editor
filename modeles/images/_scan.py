# -*- coding: utf-8 -*-
"""Indexeur configurable : chemins relatifs, aucune modification des sources."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time

EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".avif"}
EXCLUS = {"serveur", ".git", ".codex", "__pycache__", "node_modules", "$recycle.bin", "system volume information"}
TYPE = "bibliotheque-configurable-v1"


def configuration(valeur):
    if not isinstance(valeur, dict):
        raise ValueError("Configuration invalide.")
    def suffixe(texte):
        if not isinstance(texte, str):
            raise ValueError("Indiquez un suffixe.")
        texte = texte.strip()
        if not texte or len(texte) > 120 or any(c in texte for c in '/\\*?<>|"'):
            raise ValueError("Utilisez un suffixe non vide, sans chemin ni joker.")
        # Une extension saisie est acceptee, mais le filtre couvre toutes les extensions.
        for ext in sorted(EXTENSIONS, key=len, reverse=True):
            if texte.lower().endswith(ext):
                texte = texte[:-len(ext)]
                break
        if not texte:
            raise ValueError("Le suffixe doit preciser une fin de nom, avant l'extension.")
        return texte
    if valeur.get("mode") == "image":
        # Une fiche par image : ni suffixe ni vignette a choisir.
        return {"type": TYPE, "mode": "image"}
    if valeur.get("mode") == "dossier" or "vues" not in valeur:
        return {"type": TYPE, "mode": "dossier", "vignette": suffixe(valeur.get("vignette"))}
    vues = valeur.get("vues", [])
    if not isinstance(vues, list) or not 1 <= len(vues) <= 20:
        raise ValueError("Ajoutez entre 1 et 20 vues detaillees.")
    resultat = []
    for vue in vues:
        nom = str(vue.get("nom", "")).strip() if isinstance(vue, dict) else ""
        if not nom or len(nom) > 80:
            raise ValueError("Donnez un nom court a chaque vue.")
        resultat.append({"nom": nom, "suffixe": suffixe(vue.get("suffixe"))})
    return {"type": TYPE, "vignette": suffixe(valeur.get("vignette")), "vues": resultat}


def fichiers(root):
    root = Path(root).resolve()
    resultat, erreurs = [], []
    def echec(erreur):
        erreurs.append(str(erreur))
    for courant, dossiers, noms in os.walk(root, followlinks=False, onerror=echec):
        base = Path(courant)
        dossiers[:] = sorted(d for d in dossiers if not d.startswith(".") and d.casefold() not in EXCLUS
                            and not (base / d).is_symlink()
                            and (base / d).resolve().parent == base.resolve())
        for nom in sorted(noms):
            chemin = base / nom
            if nom.startswith(".") or chemin.suffix.lower() not in EXTENSIONS or chemin.is_symlink():
                continue
            try:
                chemin.resolve().relative_to(root)
                resultat.append(chemin)
            except (OSError, ValueError) as erreur:
                erreurs.append(str(erreur))
    return resultat, erreurs



def empreinte(chemin):
    digest = hashlib.sha256()
    with Path(chemin).open("rb") as fichier:
        for bloc in iter(lambda: fichier.read(1024 * 1024), b""):
            digest.update(bloc)
    return digest.hexdigest()


# L index precedent, par identifiant : rempli par enregistrer() le temps d un
# scan, pour ne pas relire ce qui n a pas bouge.
_PRECEDENT = {}


def actualiser_images(entree, root, sortie, forcer=False):
    # Le contenu est verifie au scan, meme si taille et date ont ete conservees
    # — sauf au scan AUTOMATIQUE du lancement : une image dont la taille et la
    # date n ont pas bouge depuis le dernier index garde son empreinte sans
    # etre relue. Sur un disque reseau, relire 4 Go a chaque ouverture prenait
    # deux minutes de console muette. « Mettre a jour » (forcer) relit tout.
    ancien = None if forcer else _PRECEDENT.get(entree["id"])
    versions, stamps = {}, {}
    for p in entree["fichiers"]:
        st = (root / p).stat()
        stamps[p] = [st.st_size, st.st_mtime_ns]
        if (ancien and (ancien.get("stamps") or {}).get(p) == stamps[p]
                and p in (ancien.get("versions") or {})):
            versions[p] = ancien["versions"][p]
        else:
            versions[p] = empreinte(root / p)
    entree["versions"] = versions
    entree["stamps"] = stamps
    cache = Path(sortie) / "_vignettes"
    cache.mkdir(exist_ok=True)
    cible = cache / (entree["id"] + ".jpg")
    signature = cible.with_suffix(".sha256")
    version = entree["versions"][entree["vignette"]]
    # Vignette deja faite pour cette version : elle et son empreinte restent.
    if (ancien and ancien.get("miniature") == cible.name
            and (ancien.get("versions") or {}).get(entree["vignette"]) == version
            and ancien.get("miniature_version") and cible.exists()):
        entree["miniature"] = cible.name
        entree["miniature_version"] = ancien["miniature_version"]
        return
    ancienne = signature.read_text(encoding="ascii") if signature.exists() else ""
    if forcer or not cible.exists() or ancienne != version:
        from PIL import Image, ImageOps
        temporaire = cible.with_suffix(".jpg.tmp")
        with Image.open(root / entree["vignette"]) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            im.thumbnail((480, 640))
            im.save(temporaire, "JPEG", quality=85)
        os.replace(temporaire, cible)
        signature.write_text(version, encoding="ascii")
    entree["miniature"] = cible.name
    entree["miniature_version"] = empreinte(cible)


def analyser_dossiers(root, config, sortie=None, forcer=False):
    chemins, erreurs = fichiers(root)
    par_dossier = {}
    for chemin in chemins:
        par_dossier.setdefault(chemin.parent, []).append(chemin)
    items, absentes, multiples = [], [], []
    nombre_vignettes = 0
    suffixe = config["vignette"]
    for dossier, images in sorted(par_dossier.items()):
        relatif = dossier.relative_to(root).as_posix()
        miniatures = [p for p in images if p.stem.casefold().endswith(suffixe.casefold())]
        nombre_vignettes += len(miniatures)
        if not miniatures:
            absentes.append(relatif)
            continue
        if len(miniatures) > 1:
            multiples.append(relatif)
            continue
        vignette = miniatures[0]
        prefixe = vignette.stem[:-len(suffixe)]
        # Meme identifiant qu'avant pour une vignette inchangee, notamment Police.
        cle = relatif + "/" + prefixe.casefold()
        identifiant = hashlib.sha256(cle.encode("utf-8")).hexdigest()[:24]
        entree = {"id": identifiant, "nom": dossier.name if relatif != "." else root.name,
                  "dossier": relatif, "vignette": vignette.relative_to(root).as_posix(),
                  "vues": [{"nom": p.stem, "fichier": p.relative_to(root).as_posix()} for p in images],
                  "fichiers": [p.relative_to(root).as_posix() for p in images],
                  "date": int(max(p.stat().st_mtime for p in images))}
        if sortie is not None:
            try:
                actualiser_images(entree, root, sortie, forcer)
            except ImportError:
                pass
            except Exception as erreur:
                erreurs.append("Vignette " + entree["nom"] + " : " + str(erreur))
        items.append(entree)
    return {"nom": root.name, "mode": "dossier", "maj": time.strftime("%d/%m/%Y %H:%M"),
            "items": items, "stats": {"images": len(chemins), "assets": len(items),
            "correspondances": [nombre_vignettes], "sans_vignette": absentes,
            "vues_manquantes": [], "vignettes_multiples": multiples, "erreurs": erreurs}}

def analyser_images(root, config, sortie=None, forcer=False):
    """Une fiche par image, pour un dossier d images en vrac.

    Meme format de fiche que le mode dossier : NAVIGATEUR.html n a rien a
    savoir. L identifiant depend du chemin de l image, il reste le meme d un
    scan a l autre tant que l image ne bouge pas."""
    chemins, erreurs = fichiers(root)
    items = []
    for chemin in chemins:
        relatif = chemin.relative_to(root).as_posix()
        dossier = chemin.parent.relative_to(root).as_posix()
        identifiant = hashlib.sha256(("image:" + relatif.casefold()).encode("utf-8")).hexdigest()[:24]
        entree = {"id": identifiant, "nom": chemin.stem, "dossier": dossier,
                  "vignette": relatif, "vues": [{"nom": chemin.stem, "fichier": relatif}],
                  "fichiers": [relatif], "date": int(chemin.stat().st_mtime)}
        if sortie is not None:
            try:
                actualiser_images(entree, root, sortie, forcer)
            except ImportError:
                pass
            except Exception as erreur:
                erreurs.append("Vignette " + entree["nom"] + " : " + str(erreur))
        items.append(entree)
    return {"nom": root.name, "mode": "image", "maj": time.strftime("%d/%m/%Y %H:%M"),
            "items": items, "stats": {"images": len(chemins), "assets": len(items),
            "correspondances": [len(items)], "sans_vignette": [],
            "vues_manquantes": [], "vignettes_multiples": [], "erreurs": erreurs}}


def analyser(root, config, sortie=None, forcer=False):
    root = Path(root).resolve()
    config = configuration(config)
    if config.get("mode") == "image":
        return analyser_images(root, config, sortie, forcer)
    if config.get("mode") == "dossier":
        return analyser_dossiers(root, config, sortie, forcer)
    chemins, erreurs = fichiers(root)
    groupes = {}
    suffixes = [config["vignette"]] + [v["suffixe"] for v in config["vues"]]
    correspondances = [0] * len(suffixes)
    for chemin in chemins:
        stem = chemin.stem
        for i, suffixe in enumerate(suffixes):
            if not stem.casefold().endswith(suffixe.casefold()):
                continue
            prefixe = stem[:-len(suffixe)]
            # Une image sans prefixe forme un asset portant le nom de son dossier.
            relatif = chemin.parent.relative_to(root).as_posix()
            cle = relatif + "/" + prefixe.casefold()
            groupe = groupes.setdefault(cle, {"prefixe": prefixe, "dossier": relatif,
                                             "fichiers": [[] for _ in suffixes]})
            groupe["fichiers"][i].append(chemin)
            correspondances[i] += 1

    # Un seul asset dans un dossier : rattacher ses vues uniques meme si
    # leur prefixe differe (ex. robot-Grid.png et robot-Grid_solo_01.png).
    par_dossier = {}
    for groupe in groupes.values():
        par_dossier.setdefault(groupe["dossier"], []).append(groupe)
    for voisins in par_dossier.values():
        porteurs = [g for g in voisins if g["fichiers"][0]]
        if len(porteurs) != 1:
            continue
        cible = porteurs[0]
        for i in range(1, len(suffixes)):
            if cible["fichiers"][i]:
                continue
            possibles = [(g, p) for g in voisins for p in g["fichiers"][i]]
            if len(possibles) == 1:
                origine, chemin = possibles[0]
                cible["fichiers"][i].append(chemin)
                origine["fichiers"][i].remove(chemin)

    items, sans_vignette, manquantes, ambiguites = [], [], [], []
    for cle, groupe in sorted(groupes.items()):
        liste = groupe["fichiers"]
        if not any(liste):
            continue
        nom = groupe["prefixe"].strip("_- ") or Path(groupe["dossier"]).name or root.name
        if not liste[0]:
            sans_vignette.append(nom)
            continue
        identifiant = hashlib.sha256(cle.encode("utf-8")).hexdigest()[:24]
        vues = []
        for i, vue in enumerate(config["vues"], 1):
            if not liste[i]:
                manquantes.append({"asset": nom, "vue": vue["nom"]})
            for chemin in liste[i]:
                vues.append({"nom": vue["nom"], "fichier": chemin.relative_to(root).as_posix()})
        if len(liste[0]) > 1:
            ambiguites.append(nom)
        vignette = liste[0][0]
        tous = {p for sous_liste in liste for p in sous_liste}
        entree = {"id": identifiant, "nom": nom, "dossier": groupe["dossier"],
                  "vignette": vignette.relative_to(root).as_posix(), "vues": vues,
                  "fichiers": sorted(p.relative_to(root).as_posix() for p in tous),
                  "date": int(max(p.stat().st_mtime for p in tous))}
        if sortie is not None:
            try:
                actualiser_images(entree, root, sortie, forcer)
            except ImportError:
                pass
            except Exception as erreur:
                erreurs.append("Vignette " + nom + " : " + str(erreur))
        items.append(entree)
    stats = {"images": len(chemins), "assets": len(items), "correspondances": correspondances,
             "sans_vignette": sans_vignette, "vues_manquantes": manquantes,
             "vignettes_multiples": ambiguites, "erreurs": erreurs}
    return {"nom": root.name, "maj": time.strftime("%d/%m/%Y %H:%M"), "items": items, "stats": stats}


def enregistrer(root, config, sortie, forcer=False):
    global _PRECEDENT
    sortie = Path(sortie)
    cible = sortie / "_donnees.json"
    _PRECEDENT = {}
    if not forcer and cible.exists():
        try:
            for x in json.loads(cible.read_text(encoding="utf-8")).get("items", []):
                if isinstance(x, dict) and x.get("id"):
                    _PRECEDENT[x["id"]] = x
        except Exception:
            _PRECEDENT = {}
    try:
        donnees = analyser(root, config, sortie, forcer)
    finally:
        _PRECEDENT = {}
    temporaire = cible.with_suffix(".json.tmp")
    temporaire.write_text(json.dumps(donnees, ensure_ascii=False), encoding="utf-8")
    os.replace(temporaire, cible)
    return donnees


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--racine", default=str(Path(__file__).resolve().parent.parent))
    parser.add_argument("--sortie", default=str(Path(__file__).resolve().parent))
    args = parser.parse_args()
    config = json.loads((Path(args.sortie) / "_configuration.json").read_text(encoding="utf-8-sig"))
    d = enregistrer(args.racine, config, args.sortie)
    print(str(d["stats"]["assets"]) + " assets indexes.")



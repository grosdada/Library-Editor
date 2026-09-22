# -*- coding: utf-8 -*-
"""Mise a jour du programme d une bibliotheque — Library Editor.

Le depot https://github.com/grosdada/Library-Editor publie a sa racine un
manifeste, version.json. Pour chaque genre de bibliotheque (« films »,
« racine » d images a onglets, « banque » d images), il liste les fichiers de
PROGRAMME, avec leur chemin dans le depot, leur empreinte SHA-256, et les
empreintes de toutes les versions officielles precedentes (« historique »).
Les fichiers sont lus a un commit fixe (« commit » du manifeste) : un depot
mis a jour pendant qu on telecharge ne peut pas melanger deux versions.

Regles, dans cet ordre :
  - on ne remplace qu un fichier dont on reconnait la version : une version
    officielle, ou celle inscrite dans _version.json a la derniere
    installation. Un fichier modifie a la main (la « 3d » des banques de LDR,
    par exemple) est LAISSE tel quel, et signale ;
  - chaque fichier telecharge est verifie (SHA-256) avant d etre ecrit ;
    chaque fichier remplace est sauvegarde en .avant-maj-<version>-<date> ;
  - les donnees (catalogues, marques, sequences, vignettes...) ne sont jamais
    touchees : elles ne sont pas dans le manifeste ;
  - les lanceurs .bat (« lanceur ») ne sont remplaces que si l appelant le
    permet : une console en train d executer un .bat le relit au fil de
    l eau, et le changer sous ses pieds lui ferait executer n importe quoi.
    Depuis une bibliotheque ouverte, on les laisse a Library Editor.

Aucune dependance hors de la bibliotheque standard.
"""
import hashlib
import io
import json
import os
import time
import urllib.parse
import urllib.request

DEPOT = (os.environ.get("LIBRARY_EDITOR_DEPOT")
         or "https://raw.githubusercontent.com/grosdada/Library-Editor/main/")
NOM_VERSION = "_version.json"


def sha256(chemin):
    h = hashlib.sha256()
    with open(chemin, "rb") as f:
        for bloc in iter(lambda: f.read(1 << 20), b""):
            h.update(bloc)
    return h.hexdigest()


def telecharger(url, delai=30):
    req = urllib.request.Request(url, headers={"User-Agent": "Library-Editor"})
    with urllib.request.urlopen(req, timeout=delai) as r:
        return r.read()


def manifeste_distant(depot=None):
    """Le version.json publie. Leve une erreur lisible sans reseau."""
    depot = depot or DEPOT
    url = depot + "version.json"
    # Contre les caches intermediaires — mais seulement sur le web : un depot
    # local (file://, un miroir sur le reseau) n a pas de cache, et une
    # interrogation collee au nom de fichier en ferait un chemin invalide.
    if url.startswith(("http://", "https://")):
        url += "?t=%d" % int(time.time())
    try:
        brut = telecharger(url, 15)
    except Exception as e:
        raise RuntimeError("GitHub injoignable (%s) : verifiez la connexion, "
                           "puis reessayez." % (getattr(e, "reason", "") or e))
    try:
        return json.loads(brut.decode("utf-8"))
    except Exception:
        raise RuntimeError("Manifeste illisible sur GitHub.")


def lecteur_distant(manifeste, depot=None):
    """Lit un fichier du depot au commit du manifeste (ou a la branche)."""
    depot = depot or DEPOT
    commit = manifeste.get("commit")
    if commit and depot.endswith("/main/"):
        depot = depot[:-len("main/")] + commit + "/"

    def lire(chemin_depot):
        # Deux lanceurs portent un nom a espaces (« Bibliotheque generale.bat ») :
        # sans encodage, l adresse est refusee avant meme d etre envoyee.
        return telecharger(depot + urllib.parse.quote(chemin_depot))
    return lire


def lire_installe(dossier_version):
    try:
        with io.open(os.path.join(dossier_version, NOM_VERSION),
                     encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def banques(racine):
    """Les banques d une racine a onglets : sous-dossiers equipes d un
    serveur de banque configurable."""
    out = []
    try:
        noms = sorted(os.listdir(racine), key=str.lower)
    except OSError:
        return out
    for n in noms:
        s = os.path.join(racine, n, "serveur")
        if n.startswith((".", "_")) or n.lower() == "serveur":
            continue
        if all(os.path.isfile(os.path.join(s, f))
               for f in ("_serveur.py", "_scan.py", "NAVIGATEUR.html")):
            out.append(n)
    return out


def plan(manifeste, genre, racine, installe=None, prefixe=""):
    """Ce qu il faudrait faire, fichier par fichier, sans rien faire.

    etat : « a_jour », « a_installer » (absent), « a_remplacer » (version
    officielle ou connue), « modifie » (inconnu : garde).
    """
    installe = installe or {}
    connus_installes = (installe.get("fichiers") or {})
    g = (manifeste.get("genres") or {}).get(genre)
    if not g:
        raise RuntimeError("Genre inconnu du manifeste : %s" % genre)
    lignes = []
    for rel, info in sorted(g["fichiers"].items()):
        cible = os.path.join(racine, *rel.split("/"))
        cle = (prefixe + rel) if prefixe else rel
        ligne = {"fichier": cle, "rel": rel, "cible": cible,
                 "depot": info["depot"], "sha256": info["sha256"],
                 "lanceur": bool(info.get("lanceur")),
                 "cache": bool(info.get("cache"))}
        jumeau = info.get("si_jumeau")
        if not os.path.isfile(cible):
            # Un lanceur que cette bibliotheque n a jamais eu n est pas ajoute
            # (si_present) ; un .exe a icone ne vient qu a cote de son .bat.
            if info.get("si_present") or (
                    jumeau and not os.path.isfile(os.path.join(racine, *jumeau.split("/")))):
                ligne["etat"] = "sans_objet"
            else:
                ligne["etat"] = "a_installer"
        else:
            local = sha256(cible)
            if local == info["sha256"]:
                ligne["etat"] = "a_jour"
            elif (local in (info.get("historique") or [])
                  or connus_installes.get(cle) == local):
                ligne["etat"] = "a_remplacer"
            else:
                ligne["etat"] = "modifie"
        lignes.append(ligne)
    return lignes


def plan_complet(manifeste, genre, racine):
    """Le plan d une bibliotheque entiere : pour une racine a onglets, ses
    fichiers ET ceux de chacune de ses banques."""
    dossier_v = dossier_version(genre, racine)
    installe = lire_installe(dossier_v)
    lignes = plan(manifeste, genre, racine, installe)
    if genre == "racine":
        for b in banques(racine):
            lignes += plan(manifeste, "banque", os.path.join(racine, b),
                           installe, prefixe=b + "/")
    return lignes


def dossier_version(genre, racine):
    return os.path.join(racine, "_app" if genre == "films" else "serveur")


def resume(manifeste, lignes, installe, avec_lanceurs):
    a_faire = [l for l in lignes if l["etat"] in ("a_installer", "a_remplacer")
               and (avec_lanceurs or not l["lanceur"])]
    return {"version_distante": manifeste.get("version"),
            "version_locale": installe.get("version") or "inconnue",
            "a_faire": [l["fichier"] for l in a_faire],
            "modifies": [l["fichier"] for l in lignes if l["etat"] == "modifie"],
            "lanceurs_en_attente": [l["fichier"] for l in lignes
                                    if l["lanceur"] and not avec_lanceurs
                                    and l["etat"] in ("a_installer", "a_remplacer")],
            "fichiers": [{k: l[k] for k in ("fichier", "etat", "lanceur")}
                         for l in lignes]}


def _ecrire(cible, contenu):
    """Ecriture atomique, qui passe outre l attribut « cache » de Windows
    (un fichier cache refuse d etre ecrase) et le remet ensuite."""
    os.makedirs(os.path.dirname(cible), exist_ok=True)
    cache = attribut_cache(cible)
    if cache:
        poser_cache(cible, False)
    tmp = cible + ".maj-tmp"
    with open(tmp, "wb") as f:
        f.write(contenu)
    os.replace(tmp, cible)
    if cache:
        poser_cache(cible, True)


def attribut_cache(chemin):
    if os.name != "nt" or not os.path.exists(chemin):
        return False
    try:
        import ctypes
        a = ctypes.windll.kernel32.GetFileAttributesW(str(chemin))
        return a != -1 and bool(a & 0x2)
    except Exception:
        return False


def poser_cache(chemin, cache=True):
    if os.name != "nt" or not os.path.exists(chemin):
        return
    try:
        import ctypes
        k = ctypes.windll.kernel32
        a = k.GetFileAttributesW(str(chemin))
        if a == -1:
            return
        a = (a | 0x2) if cache else (a & ~0x2)
        k.SetFileAttributesW(str(chemin), a & 0xFFFF or 0x80)
    except Exception:
        pass


def appliquer(manifeste, genre, racine, lire, avec_lanceurs=False,
              rapporter=None, forcer=False):
    """Telecharge, verifie, sauvegarde, remplace. Renvoie le compte rendu.
    `lire(chemin_depot) -> octets` : distant (GitHub) ou local (Library
    Editor, qui embarque le depot). `forcer` : remplacer aussi les fichiers
    modifies a la main (sauvegardes d abord) — sur demande expresse."""
    lignes = plan_complet(manifeste, genre, racine)
    if forcer:
        for l in lignes:
            if l["etat"] == "modifie":
                l["etat"] = "a_remplacer"
    dossier_v = dossier_version(genre, racine)
    installe = lire_installe(dossier_v)
    a_faire = [l for l in lignes if l["etat"] in ("a_installer", "a_remplacer")
               and (avec_lanceurs or not l["lanceur"])]
    # Tout est telecharge et verifie AVANT la premiere ecriture : une coupure
    # reseau ne laisse jamais une bibliotheque a moitie d une version.
    contenus = {}
    for i, l in enumerate(a_faire):
        brut = lire(l["depot"])
        if hashlib.sha256(brut).hexdigest() != l["sha256"]:
            raise RuntimeError("Empreinte inattendue pour %s : le depot vient "
                               "peut-etre de changer, reessayez dans quelques "
                               "minutes. Rien n a ete modifie." % l["fichier"])
        contenus[l["fichier"]] = brut
        if rapporter:
            rapporter("verifie", i + 1, len(a_faire), l["fichier"])
    version = manifeste.get("version") or "?"
    motif = "avant-maj-%s-%s" % (version, time.strftime("%Y%m%d-%H%M"))
    faits, sauvegardes = [], []
    for i, l in enumerate(a_faire):
        cible = l["cible"]
        if os.path.isfile(cible):
            sauve = cible + "." + motif
            n = 2
            while os.path.exists(sauve):
                sauve = "%s.%s-%d" % (cible, motif, n)
                n += 1
            with open(cible, "rb") as f:
                ancien = f.read()
            with open(sauve, "wb") as f:
                f.write(ancien)
            sauvegardes.append(os.path.basename(sauve))
        _ecrire(cible, contenus[l["fichier"]])
        if l["cache"]:
            poser_cache(cible, True)
        # Un lanceur a icone vient d arriver : son .bat jumeau se cache, on ne
        # voit plus que lui. (Changer un attribut ne touche pas au contenu : sans
        # danger meme pour un .bat en cours de lecture.)
        if cible.lower().endswith(".exe"):
            poser_cache(os.path.splitext(cible)[0] + ".bat", True)
        faits.append(l["fichier"])
        if rapporter:
            rapporter("ecrit", i + 1, len(a_faire), l["fichier"])
    # Ce qui est desormais en place, pour reconnaitre ces fichiers la
    # prochaine fois — y compris ceux qu on a laisses (modifies a la main).
    fichiers = dict(installe.get("fichiers") or {})
    for l in plan_complet(manifeste, genre, racine):
        if l["etat"] == "a_jour":
            fichiers[l["fichier"]] = l["sha256"]
    attente = [l["fichier"] for l in lignes
               if l["lanceur"] and not avec_lanceurs
               and l["etat"] in ("a_installer", "a_remplacer")]
    nouveau = {"version": version, "maj": time.strftime("%Y-%m-%d %H:%M"),
               "genre": genre, "fichiers": fichiers,
               "lanceurs_en_attente": attente}
    _ecrire(os.path.join(dossier_v, NOM_VERSION),
            json.dumps(nouveau, ensure_ascii=False, indent=1).encode("utf-8"))
    return {"version": version, "faits": faits, "sauvegardes": sauvegardes,
            "modifies": [l["fichier"] for l in lignes if l["etat"] == "modifie"],
            "lanceurs_en_attente": attente}


# ---------------------------------------------------------------------------
#  Pour un serveur de bibliotheque : verifier, puis appliquer depuis GitHub
# ---------------------------------------------------------------------------
def verifier_en_ligne(genre, racine):
    m = manifeste_distant()
    lignes = plan_complet(m, genre, racine)
    installe = lire_installe(dossier_version(genre, racine))
    return resume(m, lignes, installe, avec_lanceurs=False)


def appliquer_en_ligne(genre, racine):
    m = manifeste_distant()
    return appliquer(m, genre, racine, lecteur_distant(m), avec_lanceurs=False)

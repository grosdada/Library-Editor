# -*- coding: utf-8 -*-
"""Moteur Python embarque dans chaque bibliotheque.

Un interprete minimal : il execute le script qu on lui donne, exactement
comme « python script.py arguments », et comprend aussi « -c code » (le
selecteur de dossier de serveur.py s en sert : c est le piege 1 du brief,
un serveur gele ignorait -c). Gele par PyInstaller avec toute la
bibliotheque standard, Tkinter et Pillow, il permet a une bibliotheque de
tourner sur un PC ou Python n est pas installe.

Le script reste un fichier texte ordinaire, a cote : on peut toujours le
corriger a la main (sauvegarde .avant-quoi d abord), rien n est fige dedans.
"""
import os
import runpy
import sys

# Options d interprete sans objet ici : on les accepte pour qu un lanceur
# ecrit pour le vrai Python marche tel quel.
SANS_EFFET = {"-u", "-B", "-E", "-s", "-S", "-I", "-O", "-OO", "-q"}


def main():
    args = sys.argv[1:]
    while args and args[0] in SANS_EFFET:
        args = args[1:]
    if not args:
        sys.stdout.write("Moteur Python %s des bibliotheques. Usage : "
                         "python.exe script.py [arguments]\n"
                         % sys.version.split()[0])
        return 0
    if args[0] in ("-V", "--version"):
        sys.stdout.write("Python %s\n" % sys.version.split()[0])
        return 0
    if args[0] == "-c":
        if len(args) < 2:
            sys.stderr.write("Argument attendu apres -c\n")
            return 2
        sys.argv = ["-c"] + args[2:]
        espace = {"__name__": "__main__", "__builtins__": __builtins__}
        exec(compile(args[1], "<string>", "exec"), espace)
        return 0
    if args[0] == "-m":
        if len(args) < 2:
            sys.stderr.write("Argument attendu apres -m\n")
            return 2
        sys.argv = [args[1]] + args[2:]
        runpy.run_module(args[1], run_name="__main__", alter_sys=True)
        return 0
    script = os.path.abspath(args[0])
    if not os.path.isfile(script):
        sys.stderr.write("Script introuvable : %s\n" % script)
        return 2
    sys.argv = [script] + args[1:]
    sys.path.insert(0, os.path.dirname(script))
    runpy.run_path(script, run_name="__main__")
    return 0


if __name__ == "__main__":
    sys.exit(main())

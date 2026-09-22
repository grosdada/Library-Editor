@echo off
chcp 65001 >nul
title Bibliotheque video - ne pas fermer pendant l utilisation
cd /d "%~dp0"

py -3 --version >nul 2>&1
if %errorlevel%==0 (
  py -3 serveur.py
  goto fin
)

python --version >nul 2>&1
if %errorlevel%==0 (
  python serveur.py
  goto fin
)

echo.
echo   Python n'a pas ete trouve sur cette machine.
echo.
echo   Installe-le depuis  https://www.python.org/downloads/
echo   en cochant bien la case "Add python.exe to PATH",
echo   puis relance ce fichier.
echo.
pause
goto vraifin

:fin
echo.
echo   Le serveur s'est arrete.
echo   Si un message d'erreur s'affiche au-dessus, note-le avant de fermer.
echo.
pause

:vraifin

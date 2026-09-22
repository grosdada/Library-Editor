@echo off
chcp 65001 >nul
title Bibliotheque video - ne pas fermer pendant l utilisation
cd /d "%~dp0"

rem Le moteur Python embarque d abord : la bibliotheque marche alors sur
rem un PC sans Python. Sinon, le Python installe, comme avant.
if exist "%~dp0_python\python.exe" goto moteur

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

:moteur
"%~dp0_python\python.exe" serveur.py

:fin
echo.
echo   Le serveur s'est arrete.
echo   Si un message d'erreur s'affiche au-dessus, note-le avant de fermer.
echo.
pause

:vraifin

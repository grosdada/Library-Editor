@echo off
setlocal
chcp 65001 >nul
title Bibliotheque generale
rem pushd accepte aussi un chemin UNC et cree un lecteur temporaire.
pushd "%~dp0"
if errorlevel 1 (
  echo Le dossier serveur est inaccessible. Verifiez la connexion au NAS.
  pause
  exit /b 1
)
set "PY="
if exist "%~dp0_python\python.exe" set PY="%~dp0_python\python.exe"
if not defined PY if exist "C:\Program Files\Python310\python.exe" set PY="C:\Program Files\Python310\python.exe"
if not defined PY (where py >nul 2>&1 && set PY=py -3)
if not defined PY (where python >nul 2>&1 && set PY=python)
if not defined PY (
  echo Python 3 est introuvable. Installez Python 3 puis relancez.
  popd
  pause
  exit /b 1
)
%PY% "%~dp0_serveur.py" %*
set "RESULTAT=%ERRORLEVEL%"
popd
if not "%RESULTAT%"=="0" pause
exit /b %RESULTAT%


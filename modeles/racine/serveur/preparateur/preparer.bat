@echo off
setlocal
chcp 65001 >nul
title Preparer une bibliotheque
pushd "%~dp0"
if errorlevel 1 (
  echo Dossier inaccessible. Verifiez le disque ou la connexion reseau.
  pause
  exit /b 1
)
set "PY="
if exist "%~dp0..\_python\python.exe" set PY="%~dp0..\_python\python.exe"
if not defined PY if exist "C:\Program Files\Python310\python.exe" set PY="C:\Program Files\Python310\python.exe"
if not defined PY (where py >nul 2>&1 && set PY=py -3)
if not defined PY (where python >nul 2>&1 && set PY=python)
if not defined PY (
  echo Python 3 est requis pour utiliser cette application.
  popd
  pause
  exit /b 1
)
%PY% "%~dp0_preparateur.py" --remplacer %*
set "RESULTAT=%ERRORLEVEL%"
popd
if not "%RESULTAT%"=="0" pause
exit /b %RESULTAT%


@echo off
cd /d "%~dp0_app"
rem Chemin complet : marche aussi quand cmd ne cherche pas dans le dossier courant.
call "%~dp0_app\LANCER.bat"

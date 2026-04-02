@echo off
echo Lancement de l'environnement Docker...
docker-compose up -d

echo Attente du demarrage du serveur (patientez quelques secondes)...
:: Met le script en pause pendant 5 secondes (tu peux ajuster ce nombre)
timeout /t 5 /nobreak > NUL

echo Ouverture de l'application dans votre navigateur...
start http://localhost:5000/

echo Termine ! Vous pouvez fermer cette fenetre.
pause
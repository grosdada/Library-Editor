<?php
// ===========================================================================
//  montage.placenta.tv — reglages
// ===========================================================================
// Le seul fichier a toucher quand l hebergement change. Tout le reste en
// depend et ne connait aucun chemin en dur.

// Ou vivent les catalogues, les montages et les prereglages. En dehors de la
// racine web si l hebergeur le permet ; sinon protege par son .htaccess.
define('DOSSIER_DATA', __DIR__ . '/_data');

// D ou viennent les medias. Vide = servis par ce meme hebergeur, sous
// _media/. Sinon l adresse complete du stockage objet, barre finale comprise.
//
//   define('BASE_MEDIA', 'https://media.placenta.tv/');
//
// Passer de l un a l autre ne demande QUE cette ligne : l application lit
// cette valeur dans la reponse de /api/projets et fabrique ses URL avec.
define('BASE_MEDIA', '_media/');

// Ou sont les vignettes. Elles restent toujours ici : 412 posters pesent
// 6,7 Mo, et ils doivent s afficher vite.
define('BASE_POSTERS', '_posters/');

// Version de l API, la meme que le serveur de bureau : l application refuse
// de s ouvrir en dessous de 5.
define('API', 5);

// Taille maximale d un montage enregistre. Un montage de 500 blocs pese
// environ 300 Ko ; 4 Mo laissent toute la marge voulue sans ouvrir la porte
// a un depot abusif.
define('MAX_MONTAGE', 4 * 1024 * 1024);
define('MAX_PRESETS', 400);

// ---------------------------------------------------------------------------
//  Qui travaille
// ---------------------------------------------------------------------------
// Les montages sont ranges par utilisateur DES MAINTENANT, avant meme que les
// comptes existent : « commun » aujourd hui, un identifiant demain. Ajouter
// cette dimension apres coup aurait voulu dire deplacer des fichiers dont des
// montages dependent.
function utilisateur_courant()
{
    if (session_status() === PHP_SESSION_NONE) {
        @session_start();
    }
    $u = isset($_SESSION['utilisateur']) ? $_SESSION['utilisateur'] : '';
    return preg_match('/^[A-Za-z0-9_-]{1,32}$/', $u) ? $u : 'commun';
}

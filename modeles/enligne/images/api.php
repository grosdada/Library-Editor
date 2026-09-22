<?php
// ===========================================================================
//  Bibliotheque d images en ligne — Library Editor
// ===========================================================================
// Les memes routes que serveur/_serveur.py, au JSON pres : la page (le
// NAVIGATEUR.html de la bibliotheque, copie en index.html) n a pas besoin de
// savoir si elle tourne sur l ordinateur ou chez l hebergeur.
//
//   GET  donnees    l index des fiches (_data/_donnees.json)
//   GET  marques    favoris et pastilles
//   POST marques    enregistre des favoris et pastilles
//   GET  fichier    une image (?p=chemin relatif)
//   GET  vignette   une vignette (?id=<24 hexa>.jpg)
//   POST zip        telecharge une selection, en ZIP fabrique a la volee
//   POST scan       relit l index (la mise a jour se fait sur l ordinateur)
//   POST ouvrir     n existe que sur l ordinateur
//
// Tout vit dans _data/, que son .htaccess ferme au web : seules ces routes y
// donnent acces. Aucun mot de passe ici : la protection de l acces se regle
// dans hPanel (protection du dossier par mot de passe).

define('DATA', __DIR__ . '/_data');
define('FICHIERS', DATA . '/fichiers');
define('VIGNETTES', DATA . '/_vignettes');
define('MAX_ZIP', 3900 * 1024 * 1024);   // sans ZIP64 : moins de 4 Go

header('X-Content-Type-Options: nosniff');

function repondre($obj, $code = 200)
{
    http_response_code($code);
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store');
    echo json_encode($obj, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    exit;
}

function erreur($message, $code = 400)
{
    repondre(array('erreur' => $message), $code);
}

function lire_json($chemin, $defaut)
{
    if (!is_file($chemin)) {
        return $defaut;
    }
    $d = json_decode((string) @file_get_contents($chemin), true);
    return is_array($d) ? $d : $defaut;
}

// Ecriture atomique : on ecrit a cote, puis on renomme.
function ecrire_json($chemin, $obj)
{
    $tmp = $chemin . '.' . getmypid() . '.tmp';
    $t = json_encode($obj, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    if ($t === false || @file_put_contents($tmp, $t, LOCK_EX) === false) {
        return false;
    }
    if (!@rename($tmp, $chemin)) {
        @unlink($tmp);
        return false;
    }
    return true;
}

// Un chemin relatif venu de la page : rien ne doit sortir de fichiers/.
function chemin_image($rel)
{
    $rel = str_replace(chr(92), '/', (string) $rel);
    if ($rel === '' || strlen($rel) > 1000 || $rel[0] === '/') {
        return null;
    }
    foreach (explode('/', $rel) as $bout) {
        if ($bout === '' || $bout === '.' || $bout === '..' || $bout[0] === '.') {
            return null;
        }
    }
    $ext = strtolower(pathinfo($rel, PATHINFO_EXTENSION));
    if (!in_array($ext, array('jpg', 'jpeg', 'png', 'webp', 'gif', 'bmp', 'tif',
            'tiff', 'avif'), true)) {
        return null;
    }
    $plein = FICHIERS . '/' . $rel;
    return is_file($plein) ? $plein : null;
}

function type_image($chemin)
{
    $types = array('jpg' => 'image/jpeg', 'jpeg' => 'image/jpeg',
        'png' => 'image/png', 'webp' => 'image/webp', 'gif' => 'image/gif',
        'bmp' => 'image/bmp', 'tif' => 'image/tiff', 'tiff' => 'image/tiff',
        'avif' => 'image/avif');
    $e = strtolower(pathinfo($chemin, PATHINFO_EXTENSION));
    return isset($types[$e]) ? $types[$e] : 'application/octet-stream';
}

function envoyer_fichier($chemin)
{
    // Une version (?v=) change quand l image change : un an de cache sans
    // risque. Sans version, pas de cache.
    $v = isset($_GET['v']) ? (string) $_GET['v'] : '';
    header('Content-Type: ' . type_image($chemin));
    header('Content-Length: ' . filesize($chemin));
    header('Cache-Control: ' . ($v !== '' ? 'private, max-age=31536000, immutable'
                                          : 'no-store'));
    readfile($chemin);
    exit;
}

// Favoris et pastilles : ceux deposes depuis l ordinateur (_marques.depot.json,
// reecrit a chaque publication) et ceux poses en ligne (_marques.json). Pour
// chaque fiche, la marque la plus recente gagne — la regle de _serveur.py.
function marques()
{
    $depot = lire_json(DATA . '/_marques.depot.json', array());
    $ici = lire_json(DATA . '/_marques.json', array());
    $out = $depot;
    foreach ($ici as $id => $m) {
        if (!is_array($m)) {
            continue;
        }
        if (!isset($out[$id]) || (int) (isset($m['t']) ? $m['t'] : 0)
                >= (int) (isset($out[$id]['t']) ? $out[$id]['t'] : 0)) {
            $out[$id] = $m;
        }
    }
    return $out;
}

// Une requete d ecriture doit venir de cette page, pas d un autre site.
function meme_origine()
{
    if (isset($_SERVER['HTTP_SEC_FETCH_SITE'])
            && $_SERVER['HTTP_SEC_FETCH_SITE'] === 'cross-site') {
        erreur('Origine refusee.', 403);
    }
    if (!empty($_SERVER['HTTP_ORIGIN'])) {
        $hote = parse_url($_SERVER['HTTP_ORIGIN'], PHP_URL_HOST);
        $ici = isset($_SERVER['HTTP_HOST']) ? preg_replace('/:\d+$/', '', $_SERVER['HTTP_HOST']) : '';
        if ($hote !== $ici) {
            erreur('Origine refusee.', 403);
        }
    }
}

// ZIP sans compression, ecrit au fil de l envoi : ni fichier temporaire ni
// memoire, quelle que soit la taille de la selection (moins de 4 Go).
function zip_flux($liste)
{
    @set_time_limit(0);
    while (ob_get_level()) {
        ob_end_clean();
    }
    header('Content-Type: application/zip');
    header('Content-Disposition: attachment; filename="selection.zip"');
    header('Cache-Control: no-store');
    $central = '';
    $decalage = 0;
    $n = 0;
    foreach ($liste as $f) {
        $chemin = $f[0];
        $nom = $f[1];
        $taille = filesize($chemin);
        $crc = hexdec(hash_file('crc32b', $chemin));
        $t = getdate(filemtime($chemin));
        $heure = ($t['hours'] << 11) | ($t['minutes'] << 5) | intdiv($t['seconds'], 2);
        $date = ((max(1980, $t['year']) - 1980) << 9) | ($t['mon'] << 5) | $t['mday'];
        $local = pack('VvvvvvVVVvv', 0x04034b50, 20, 0x0800, 0, $heure, $date,
            $crc, $taille, $taille, strlen($nom), 0) . $nom;
        echo $local;
        readfile($chemin);
        flush();
        $central .= pack('VvvvvvvVVVvvvvvVV', 0x02014b50, 20, 20, 0x0800, 0,
            $heure, $date, $crc, $taille, $taille, strlen($nom), 0, 0, 0, 0, 0,
            $decalage) . $nom;
        $decalage += strlen($local) + $taille;
        $n++;
    }
    echo $central . pack('VvvvvVVv', 0x06054b50, 0, 0, $n, $n, strlen($central),
        $decalage, 0);
    exit;
}

// ---------------------------------------------------------------------------
//  Routage : .htaccess envoie /donnees, /marques... ici avec ?r= ; a defaut,
//  on lit la fin de l adresse.
// ---------------------------------------------------------------------------
$route = isset($_GET['r']) ? trim((string) $_GET['r'], '/') : '';
if ($route === '') {
    $route = basename(parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH));
}
$poste = ($_SERVER['REQUEST_METHOD'] === 'POST');

if ($route === 'donnees' || ($route === 'scan' && $poste)) {
    if ($poste) {
        meme_origine();
    }
    $f = DATA . '/_donnees.json';
    if (!is_file($f)) {
        repondre(array('nom' => '', 'items' => array()));
    }
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store');
    readfile($f);
    exit;
}

if ($route === 'marques' && !$poste) {
    repondre((object) marques());
}

if ($route === 'marques' && $poste) {
    meme_origine();
    $brut = file_get_contents('php://input');
    if ($brut === false || strlen($brut) > 4000000) {
        erreur('Requete invalide ou trop volumineuse.');
    }
    $d = json_decode($brut, true);
    if (!is_array($d)) {
        erreur('Objet JSON attendu.');
    }
    $verrou = @fopen(DATA . '/.marques.lock', 'c');
    if ($verrou) {
        flock($verrou, LOCK_EX);
    }
    $m = marques();
    foreach ($d as $id => $v) {
        if (!preg_match('/^[0-9a-f]{6,64}$/', (string) $id) || !is_array($v)) {
            continue;
        }
        $t = isset($v['t']) ? (int) $v['t'] : (int) round(microtime(true) * 1000);
        $ancien = isset($m[$id]['t']) ? (int) $m[$id]['t'] : 0;
        if ($t >= $ancien) {
            $m[$id] = array('fav' => !empty($v['fav']),
                'coul' => max(0, min(5, (int) (isset($v['coul']) ? $v['coul'] : 0))),
                't' => $t);
        }
    }
    $ok = ecrire_json(DATA . '/_marques.json', $m);
    if ($verrou) {
        flock($verrou, LOCK_UN);
        fclose($verrou);
    }
    if (!$ok) {
        erreur('Enregistrement impossible : droits du dossier _data ?', 500);
    }
    repondre((object) $m);
}

if ($route === 'fichier' && !$poste) {
    $c = chemin_image(isset($_GET['p']) ? $_GET['p'] : '');
    if ($c === null) {
        erreur('Image introuvable.', 404);
    }
    envoyer_fichier($c);
}

if ($route === 'vignette' && !$poste) {
    $id = isset($_GET['id']) ? (string) $_GET['id'] : '';
    if (!preg_match('/^[0-9a-f]{24}\.jpg$/', $id) || !is_file(VIGNETTES . '/' . $id)) {
        erreur('Vignette introuvable.', 404);
    }
    envoyer_fichier(VIGNETTES . '/' . $id);
}

if ($route === 'zip' && $poste) {
    meme_origine();
    $brut = isset($_POST['d']) ? (string) $_POST['d'] : file_get_contents('php://input');
    $d = json_decode($brut, true);
    $sel = (is_array($d) && isset($d['fichiers']) && is_array($d['fichiers']))
        ? $d['fichiers'] : array();
    if (!$sel) {
        erreur('Selection vide.');
    }
    $liste = array();
    $vus = array();
    $total = 0;
    foreach ($sel as $rel) {
        $c = chemin_image($rel);
        if ($c === null) {
            erreur('Image introuvable : ' . $rel, 404);
        }
        $rel = str_replace(chr(92), '/', (string) $rel);
        if (isset($vus[$rel])) {
            continue;
        }
        $vus[$rel] = true;
        $total += filesize($c);
        $liste[] = array($c, $rel);
    }
    if ($total > MAX_ZIP) {
        erreur('Selection trop lourde pour un seul ZIP (plus de 3,9 Go) : '
            . 'selectionnez moins de fiches.');
    }
    zip_flux($liste);
}

if ($route === 'ouvrir') {
    erreur("Ouvrir le dossier n'existe que sur l'ordinateur de la bibliotheque.",
        501);
}

erreur('Ressource inconnue.', 404);

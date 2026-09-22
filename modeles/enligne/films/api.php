<?php
// ===========================================================================
//  montage.placenta.tv — les routes
// ===========================================================================
// La version de bureau (serveur.py) expose 25 routes. Ici, dix suffisent :
// tout ce qui suppose ffmpeg, ffprobe ou un disque local a disparu. Les
// autres repondent le MEME JSON que la version de bureau, au champ pres —
// c est ce qui permet de n avoir qu un seul app.html des deux cotes.
//
// Ce fichier ne connait aucun chemin en dur : tout vient de config.php.

require __DIR__ . '/config.php';

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

// ---------------------------------------------------------------------------
//  Sortie
// ---------------------------------------------------------------------------
function repondre($obj, $code = 200)
{
    http_response_code($code);
    echo json_encode($obj, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    exit;
}

function erreur($message, $code = 400)
{
    repondre(array('ok' => false, 'erreur' => $message), $code);
}

// Une route qui n existe que sur le bureau. On le dit clairement plutot que de
// renvoyer « route inconnue » : l application sait alors afficher pourquoi, et
// la lecture des journaux ne laisse pas croire a un bug de routage.
function hors_ligne($quoi, $pourquoi)
{
    // Une seule raison pour vingt routes, c etait commode a ecrire et faux a
    // lire : creer un dossier n a jamais eu besoin de ffmpeg. Chaque route
    // porte donc la SIENNE, sinon le message envoie chercher au mauvais
    // endroit.
    repondre(array('ok' => false, 'horsligne' => true,
        'erreur' => $quoi . ' happens at home — ' . $pourquoi), 501);
}

// ---------------------------------------------------------------------------
//  Noms et chemins : rien ne doit pouvoir sortir de _data
// ---------------------------------------------------------------------------
// Un nom de projet est un segment simple. Ni separateur, ni point initial, ni
// souligne initial (les dossiers techniques commencent par un souligne).
function nom_projet($n)
{
    $n = trim((string) $n);
    if ($n === '' || strlen($n) > 120) {
        return null;
    }
    if (strpbrk($n, "/\\\0") !== false) {
        return null;
    }
    if ($n[0] === '.' || $n[0] === '_') {
        return null;
    }
    if (!is_dir(DOSSIER_DATA . '/' . $n)) {
        return null;
    }
    return $n;
}

// Le nom d un montage. Meme regle, plus les caracteres qu un systeme de
// fichiers refuse. On garde les accents et les espaces : ce sont des noms
// choisis par une personne, pas des identifiants.
function nom_propre($n)
{
    $n = trim((string) $n);
    if ($n === '' || strlen($n) > 120) {
        return null;
    }
    if (strpbrk($n, "/\\:*?\"<>|\0") !== false) {
        return null;
    }
    if ($n[0] === '.') {
        return null;
    }
    return $n;
}

function dossier_projet($pr)
{
    return DOSSIER_DATA . '/' . $pr;
}

function dossier_montages($pr)
{
    return dossier_projet($pr) . '/_montages/' . utilisateur_courant();
}

// ---------------------------------------------------------------------------
//  Lecture et ecriture
// ---------------------------------------------------------------------------
function lire_json($chemin, $defaut = null)
{
    if (!is_file($chemin)) {
        return $defaut;
    }
    $t = @file_get_contents($chemin);
    if ($t === false) {
        return $defaut;
    }
    $d = json_decode($t, true);
    return $d === null ? $defaut : $d;
}

// Ecriture atomique : on ecrit a cote, puis on renomme. Un montage a moitie
// ecrit n existe jamais, meme si l hebergeur coupe le script en plein milieu.
function ecrire_json($chemin, $obj)
{
    $dos = dirname($chemin);
    if (!is_dir($dos) && !@mkdir($dos, 0755, true)) {
        return false;
    }
    $tmp = $chemin . '.' . getmypid() . '.tmp';
    $t = json_encode($obj, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES
        | JSON_PRETTY_PRINT);
    if ($t === false) {
        return false;
    }
    if (@file_put_contents($tmp, $t, LOCK_EX) === false) {
        return false;
    }
    if (!@rename($tmp, $chemin)) {
        @unlink($tmp);
        return false;
    }
    return true;
}

function corps_json()
{
    $brut = file_get_contents('php://input');
    if ($brut === false || $brut === '') {
        return array();
    }
    if (strlen($brut) > MAX_MONTAGE) {
        erreur('sequence too large', 413);
    }
    $d = json_decode($brut, true);
    return is_array($d) ? $d : array();
}

// La liste des projets publies. Ecrite par « Publier » ; si elle manque, on
// retombe sur les dossiers presents, pour qu un depot manuel marche aussi.
function projets_publies()
{
    $l = lire_json(DOSSIER_DATA . '/projets.json', null);
    if (is_array($l) && isset($l['projets']) && is_array($l['projets'])) {
        return $l;
    }
    $noms = array();
    foreach ((array) @scandir(DOSSIER_DATA) as $n) {
        if ($n === '.' || $n === '..' || $n[0] === '_' || $n[0] === '.') {
            continue;
        }
        if (is_dir(DOSSIER_DATA . '/' . $n)) {
            $noms[] = $n;
        }
    }
    sort($noms);
    return array('projets' => $noms, 'biblis' => array());
}

// ---------------------------------------------------------------------------
//  Preregages — meme contrat que la version de bureau
// ---------------------------------------------------------------------------
function fichier_presets($genre)
{
    $g = strtolower(trim((string) $genre));
    if (!preg_match('/^[a-z0-9_-]{1,24}$/', $g)) {
        return null;
    }
    return DOSSIER_DATA . '/_presets/' . $g . '.json';
}

function nom_preset($n)
{
    $n = trim(preg_replace('/[\r\n\t]+/', ' ', (string) $n));
    return mb_substr($n, 0, 40);
}

// ---------------------------------------------------------------------------
//  Comptes
// ---------------------------------------------------------------------------
// Aucun mot de passe n est jamais ecrit ici, ni lu, ni transmis : le
// navigateur l envoie une fois, password_hash en garde une empreinte bcrypt,
// et c est tout ce que le disque connait. Meme l administrateur ne peut pas
// relire celui d un autre — il ne peut que le remplacer.
define('MAX_RANGEMENT', 1024 * 1024);

function fichier_comptes()
{
    return DOSSIER_DATA . '/_comptes.json';
}

function comptes()
{
    $c = lire_json(fichier_comptes(), array());
    return is_array($c) ? $c : array();
}

function identifiant_propre($n)
{
    $n = strtolower(trim((string) $n));
    return preg_match('/^[a-z0-9][a-z0-9_-]{1,31}$/', $n) ? $n : null;
}

function session_ouverte()
{
    if (session_status() === PHP_SESSION_NONE) {
        @session_set_cookie_params(array('httponly' => true,
            'samesite' => 'Lax',
            'secure' => (!empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off')));
        @session_start();
    }
}

function moi()
{
    session_ouverte();
    $m = isset($_SESSION['id']) ? $_SESSION['id'] : '';
    $m = identifiant_propre($m);
    if ($m === null) {
        return '';
    }
    // Un compte efface ne doit pas survivre dans une session ouverte.
    $c = comptes();
    return isset($c[$m]) ? $m : '';
}

function suis_admin()
{
    $m = moi();
    if ($m === '') {
        return false;
    }
    $c = comptes();
    return !empty($c[$m]['admin']);
}

function exiger_compte()
{
    if (moi() === '') {
        repondre(array('ok' => false, 'connexion' => true,
            'erreur' => 'sign in first'), 401);
    }
}

function exiger_admin()
{
    exiger_compte();
    if (!suis_admin()) {
        repondre(array('ok' => false, 'erreur' => 'administrator only'), 403);
    }
}

// ---------------------------------------------------------------------------
//  Rangement virtuel
// ---------------------------------------------------------------------------
// Des dossiers qui n existent nulle part sur un disque. Le catalogue n est
// JAMAIS touche : « id » et « rel » restent ceux du poste de David, ce qui
// laisse l export XML retrouver les fichiers a leur emplacement d origine,
// quelle que soit l organisation que chacun s est faite ici.
function fichier_rangement($pr, $qui)
{
    return dossier_projet($pr) . '/_rangement/' . $qui . '.json';
}

function chemin_dossier($p)
{
    $p = trim(str_replace('\\', '/', (string) $p), '/');
    if ($p === '') {
        return '';
    }
    $bouts = explode('/', $p);
    if (count($bouts) > 5) {
        return null;
    }
    $propres = array();
    foreach ($bouts as $b) {
        $b = trim($b);
        if ($b === '' || $b === '.' || $b === '..' || strlen($b) > 60) {
            return null;
        }
        if (strpbrk($b, "/\\:*?\"<>|\0") !== false) {
            return null;
        }
        $propres[] = $b;
    }
    return implode('/', $propres);
}

function rangement_propre($d)
{
    $dossiers = array();
    if (isset($d['dossiers']) && is_array($d['dossiers'])) {
        foreach ($d['dossiers'] as $x) {
            $p = chemin_dossier($x);
            if ($p === null || $p === '') {
                continue;
            }
            $dossiers[$p] = true;
            // Un sous-dossier implique ses parents : sinon un dossier
            // intermediaire efface ferait disparaitre tout ce qu il contient.
            $bouts = explode('/', $p);
            array_pop($bouts);
            while ($bouts) {
                $dossiers[implode('/', $bouts)] = true;
                array_pop($bouts);
            }
            if (count($dossiers) > 300) {
                break;
            }
        }
    }
    $ou = array();
    if (isset($d['ou']) && is_array($d['ou'])) {
        foreach ($d['ou'] as $id => $x) {
            if (!preg_match('/^[0-9a-f]{6,32}$/', (string) $id)) {
                continue;
            }
            $p = chemin_dossier($x);
            if ($p === null || $p === '' || !isset($dossiers[$p])) {
                continue;       // ranger dans un dossier absent = non range
            }
            $ou[(string) $id] = $p;
            if (count($ou) > 20000) {
                break;
            }
        }
    }
    $l = array_keys($dossiers);
    sort($l);
    return array('maj' => date('Y-m-d H:i'), 'dossiers' => $l, 'ou' => $ou);
}

// ---------------------------------------------------------------------------
//  Routage
// ---------------------------------------------------------------------------
// Le .htaccess envoie /api/<quoi> ici. Si la reecriture ne marchait pas, le
// parametre « r » fait le meme travail : une route de secours coute trois
// lignes et evite une soiree de diagnostic.
$route = isset($_GET['r']) ? trim($_GET['r'], '/') : '';
if ($route === '') {
    $chemin = parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH);
    $p = strpos($chemin, '/api/');
    if ($p !== false) {
        $route = trim(substr($chemin, $p + 5), '/');
    }
}
$poste = ($_SERVER['REQUEST_METHOD'] === 'POST');
$d = $poste ? corps_json() : array();

// ===========================================================================
//  Entrer, sortir, savoir qui on est
// ===========================================================================
// Ces trois routes-la sont les SEULES ouvertes sans compte : sans elles, une
// page qui ne sait pas encore si elle doit demander un mot de passe ne
// pourrait rien afficher du tout.

// ---- GET /api/moi ----------------------------------------------------------
if ($route === 'moi' && !$poste) {
    $c = comptes();
    repondre(array('identifiant' => moi(), 'admin' => suis_admin(),
        // Zero compte = site tout neuf : la page propose de creer
        // l administrateur, une fois, et l offre disparait ensuite.
        'comptes' => count($c)));
}

// ---- POST /api/entrer ------------------------------------------------------
if ($route === 'entrer' && $poste) {
    $id = identifiant_propre(isset($d['identifiant']) ? $d['identifiant'] : '');
    $mp = isset($d['motdepasse']) ? (string) $d['motdepasse'] : '';
    $c = comptes();
    // Une seule et meme reponse que l identifiant existe ou non : dire
    // « ce compte n existe pas » revient a publier la liste des comptes.
    if ($id === null || !isset($c[$id]) || $mp === ''
            || !password_verify($mp, (string) $c[$id]['hash'])) {
        usleep(400000);          // un essai toutes les 0,4 s, pas dix mille
        erreur('wrong name or password', 401);
    }
    session_ouverte();
    session_regenerate_id(true);
    $_SESSION['id'] = $id;
    repondre(array('ok' => true, 'identifiant' => $id,
        'admin' => !empty($c[$id]['admin'])));
}

// ---- POST /api/sortir ------------------------------------------------------
if ($route === 'sortir' && $poste) {
    session_ouverte();
    $_SESSION = array();
    @session_destroy();
    repondre(array('ok' => true));
}

// ---- POST /api/compte/creer ------------------------------------------------
// Ouverte UNIQUEMENT tant qu aucun compte n existe — c est l amorcage, et le
// premier cree est forcement administrateur. Ensuite, administrateur requis.
if ($route === 'compte/creer' && $poste) {
    $c = comptes();
    $amorce = (count($c) === 0);
    if (!$amorce) {
        exiger_admin();
    }
    $id = identifiant_propre(isset($d['identifiant']) ? $d['identifiant'] : '');
    $mp = isset($d['motdepasse']) ? (string) $d['motdepasse'] : '';
    if ($id === null) {
        erreur('the name must be 2 to 32 letters, digits, - or _');
    }
    if (isset($c[$id])) {
        erreur('this name is taken', 409);
    }
    if (strlen($mp) < 8) {
        erreur('the password must be at least 8 characters');
    }
    if (count($c) >= 200) {
        erreur('too many accounts');
    }
    $c[$id] = array(
        'hash' => password_hash($mp, PASSWORD_DEFAULT),
        'admin' => $amorce ? true : !empty($d['admin']),
        'cree' => date('Y-m-d H:i'),
    );
    if (!ecrire_json(fichier_comptes(), $c)) {
        erreur('could not save the account', 500);
    }
    if ($amorce) {           // on entre tout de suite : sinon personne ne peut
        session_ouverte();   // plus rien faire jusqu au prochain chargement
        session_regenerate_id(true);
        $_SESSION['id'] = $id;
    }
    repondre(array('ok' => true, 'identifiant' => $id,
        'admin' => !empty($c[$id]['admin'])));
}

// ---- POST /api/compte/motdepasse -------------------------------------------
// Un administrateur remplace celui d un autre ; il ne le lit jamais.
if ($route === 'compte/motdepasse' && $poste) {
    exiger_compte();
    $c = comptes();
    $id = identifiant_propre(isset($d['identifiant']) ? $d['identifiant'] : '');
    if ($id === null || !isset($c[$id])) {
        erreur('no such account', 404);
    }
    if ($id !== moi() && !suis_admin()) {
        erreur('administrator only', 403);
    }
    $mp = isset($d['motdepasse']) ? (string) $d['motdepasse'] : '';
    if (strlen($mp) < 8) {
        erreur('the password must be at least 8 characters');
    }
    $c[$id]['hash'] = password_hash($mp, PASSWORD_DEFAULT);
    if (!ecrire_json(fichier_comptes(), $c)) {
        erreur('could not save', 500);
    }
    repondre(array('ok' => true, 'identifiant' => $id));
}

// ---- POST /api/compte/effacer ----------------------------------------------
if ($route === 'compte/effacer' && $poste) {
    exiger_admin();
    $c = comptes();
    $id = identifiant_propre(isset($d['identifiant']) ? $d['identifiant'] : '');
    if ($id === null || !isset($c[$id])) {
        erreur('no such account', 404);
    }
    if ($id === moi()) {
        erreur('you cannot delete your own account');
    }
    $admins = 0;
    foreach ($c as $x) {
        if (!empty($x['admin'])) {
            $admins++;
        }
    }
    if (!empty($c[$id]['admin']) && $admins <= 1) {
        erreur('this is the last administrator');
    }
    unset($c[$id]);
    if (!ecrire_json(fichier_comptes(), $c)) {
        erreur('could not save', 500);
    }
    // Le rangement de cette personne reste sur le disque : effacer un compte
    // ne doit pas effacer un travail, et le nom se recree a l identique.
    repondre(array('ok' => true, 'identifiant' => $id));
}

// ---- GET /api/comptes ------------------------------------------------------
// La liste des identifiants, jamais les empreintes.
if ($route === 'comptes' && !$poste) {
    exiger_admin();
    $out = array();
    foreach (comptes() as $id => $x) {
        $out[] = array('identifiant' => $id, 'admin' => !empty($x['admin']),
            'cree' => isset($x['cree']) ? $x['cree'] : '');
    }
    repondre(array('comptes' => $out));
}

// ===========================================================================
//  A partir d ici, tout demande un compte
// ===========================================================================
exiger_compte();

// ---- GET /api/rangement ----------------------------------------------------
// Le sien, ou celui de n importe qui pour un administrateur.
if ($route === 'rangement' && !$poste) {
    $pr = nom_projet(isset($_GET['projet']) ? $_GET['projet'] : '');
    if ($pr === null) {
        erreur('unknown project', 404);
    }
    $qui = isset($_GET['qui']) ? identifiant_propre($_GET['qui']) : moi();
    if ($qui === null) {
        erreur('unknown account', 404);
    }
    if ($qui !== moi() && !suis_admin()) {
        erreur('administrator only', 403);
    }
    $r = lire_json(fichier_rangement($pr, $qui),
        array('dossiers' => array(), 'ou' => new stdClass()));
    if (!isset($r['ou']) || !is_array($r['ou'])) {
        $r['ou'] = array();
    }
    repondre(array('ok' => true, 'projet' => $pr, 'qui' => $qui,
        'dossiers' => isset($r['dossiers']) ? $r['dossiers'] : array(),
        'ou' => (object) $r['ou']));
}

// ---- POST /api/rangement ---------------------------------------------------
// On n ecrit que le SIEN. Un administrateur peut lire celui d un autre, pas
// le refaire : ce serait ranger a la place de quelqu un sans qu il le sache.
if ($route === 'rangement' && $poste) {
    $pr = nom_projet(isset($d['projet']) ? $d['projet'] : '');
    if ($pr === null) {
        erreur('unknown project', 404);
    }
    $r = rangement_propre($d);
    $t = json_encode($r);
    if ($t !== false && strlen($t) > MAX_RANGEMENT) {
        erreur('arrangement too large', 413);
    }
    if (!ecrire_json(fichier_rangement($pr, moi()), $r)) {
        erreur('could not save the arrangement', 500);
    }
    repondre(array('ok' => true, 'projet' => $pr, 'qui' => moi(),
        'dossiers' => $r['dossiers'], 'ou' => (object) $r['ou']));
}

// ---- GET /api/projets ------------------------------------------------------
if ($route === 'projets' && !$poste) {
    $l = projets_publies();
    $out = array();
    foreach ($l['projets'] as $n) {
        $cat = lire_json(dossier_projet($n) . '/catalogue.json',
            array('films' => array()));
        $vivants = 0;
        foreach ($cat['films'] as $f) {
            if (empty($f['absent'])) {
                $vivants++;
            }
        }
        $out[] = array('nom' => $n, 'scanne' => true, 'clips' => $vivants,
            'fichiers' => null);
    }
    repondre(array(
        'projets' => $out,
        'racine' => '',
        'jeton' => '',
        'biblis' => isset($l['biblis']) ? $l['biblis'] : array(),
        'api' => API,
        // Pas de ffmpeg : l application cache d elle-meme le scan, le rendu,
        // l import et le renommage.
        'ffmpeg' => false,
        'enligne' => true,
        'media' => BASE_MEDIA,
        'posters' => BASE_POSTERS,
        'utilisateur' => utilisateur_courant(),
    ));
}

// ---- GET /api/catalogue ----------------------------------------------------
if ($route === 'catalogue' && !$poste) {
    $pr = nom_projet(isset($_GET['projet']) ? $_GET['projet'] : '');
    if ($pr === null) {
        erreur('unknown project', 404);
    }
    $cat = lire_json(dossier_projet($pr) . '/catalogue.json',
        array('maj' => null, 'films' => array()));
    $cat['projet'] = $pr;
    if (!isset($cat['dossiers'])) {
        $dos = array();
        foreach ($cat['films'] as $f) {
            if (!empty($f['dossier'])) {
                $dos[$f['dossier']] = true;
            }
        }
        $cat['dossiers'] = array_keys($dos);
        sort($cat['dossiers']);
    }
    $cat['ffmpeg'] = false;
    $cat['enligne'] = true;
    // La version de bureau renvoie ici le chemin disque, dont l export XML a
    // besoin. En ligne il n existe pas : l export XML reste donc une affaire
    // de bureau, et l application le sait.
    $cat['racine_abs'] = '';
    $cat['api'] = API;
    repondre($cat);
}

// ---- GET /api/montages -----------------------------------------------------
if ($route === 'montages' && !$poste) {
    $pr = nom_projet(isset($_GET['projet']) ? $_GET['projet'] : '');
    if ($pr === null) {
        erreur('unknown project', 404);
    }
    $dos = dossier_montages($pr);
    @mkdir($dos, 0755, true);
    $out = array();
    foreach ((array) @scandir($dos) as $n) {
        if (substr(strtolower($n), -5) !== '.json') {
            continue;
        }
        $c = $dos . '/' . $n;
        $out[] = array(
            'nom' => substr($n, 0, -5),
            'projet' => $pr,
            'maj' => date('Y-m-d H:i', filemtime($c)),
            'octets' => filesize($c),
        );
    }
    usort($out, function ($a, $b) {
        return strcmp($b['maj'], $a['maj']);
    });
    repondre(array('montages' => $out, 'projet' => $pr));
}

// ---- GET /api/montage ------------------------------------------------------
if ($route === 'montage' && !$poste) {
    $pr = nom_projet(isset($_GET['projet']) ? $_GET['projet'] : '');
    $nom = nom_propre(isset($_GET['nom']) ? $_GET['nom'] : '');
    if ($pr === null) {
        erreur('unknown project', 404);
    }
    $f = dossier_montages($pr) . '/' . $nom . '.json';
    if ($nom === null || !is_file($f)) {
        erreur('sequence not found', 404);
    }
    repondre(array('ok' => true, 'nom' => $nom, 'projet' => $pr,
        'montage' => lire_json($f, array())));
}

// ---- POST /api/montage -----------------------------------------------------
if ($route === 'montage' && $poste) {
    $pr = nom_projet(isset($d['projet']) ? $d['projet'] : '');
    $nom = nom_propre(isset($d['nom']) ? $d['nom'] : '');
    if ($pr === null) {
        erreur('unknown project', 404);
    }
    if ($nom === null) {
        erreur('invalid sequence name');
    }
    if (!isset($d['montage']) || !is_array($d['montage'])) {
        erreur('nothing to save');
    }
    $f = dossier_montages($pr) . '/' . $nom . '.json';
    if (!ecrire_json($f, $d['montage'])) {
        erreur('could not write the sequence — check folder permissions', 500);
    }
    repondre(array('ok' => true, 'nom' => $nom, 'projet' => $pr,
        'octets' => filesize($f)));
}

// ---- POST /api/montage/renommer -------------------------------------------
if ($route === 'montage/renommer' && $poste) {
    $pr = nom_projet(isset($d['projet']) ? $d['projet'] : '');
    // Les memes noms de champs que serveur.py, parce que c est pour lui que
    // l application est ecrite : « ancien » est celui qui existe, « nom »
    // celui qu on veut. Lire « neuf » ici faisait echouer TOUT renommage en
    // ligne avec un « invalid name » qui ne designait rien.
    $de = nom_propre(isset($d['ancien']) ? $d['ancien'] : '');
    $vers = nom_propre(isset($d['nom']) ? $d['nom'] : '');
    if ($pr === null) {
        erreur('unknown project', 404);
    }
    if ($de === null || $vers === null) {
        erreur('invalid name');
    }
    $dos = dossier_montages($pr);
    if (!is_file($dos . '/' . $de . '.json')) {
        erreur('sequence not found', 404);
    }
    // Renommer en son propre nom n est pas une erreur : c est ce que fait une
    // boite de saisie que l on valide sans rien changer.
    if ($de === $vers) {
        repondre(array('ok' => true, 'nom' => $vers, 'projet' => $pr));
    }
    if (is_file($dos . '/' . $vers . '.json')) {
        erreur('a sequence already has that name', 409);
    }
    if (!@rename($dos . '/' . $de . '.json', $dos . '/' . $vers . '.json')) {
        erreur('could not rename', 500);
    }
    repondre(array('ok' => true, 'nom' => $vers, 'projet' => $pr));
}

// ---- POST /api/montage/effacer --------------------------------------------
// On ne supprime pas : on deplace dans une corbeille. Un montage represente
// des heures de travail, et il n y a pas d annulation apres coup.
if ($route === 'montage/effacer' && $poste) {
    $pr = nom_projet(isset($d['projet']) ? $d['projet'] : '');
    $nom = nom_propre(isset($d['nom']) ? $d['nom'] : '');
    if ($pr === null) {
        erreur('unknown project', 404);
    }
    $dos = dossier_montages($pr);
    if ($nom === null || !is_file($dos . '/' . $nom . '.json')) {
        erreur('sequence not found', 404);
    }
    $corb = $dos . '/_corbeille';
    @mkdir($corb, 0755, true);
    $cible = $corb . '/' . $nom . '-' . date('Ymd-His') . '.json';
    if (!@rename($dos . '/' . $nom . '.json', $cible)) {
        erreur('could not remove', 500);
    }
    repondre(array('ok' => true, 'nom' => $nom, 'corbeille' => true));
}

// ---- GET /api/usages -------------------------------------------------------
// Ou ce rush a-t-il servi ? On ouvre tous les montages de tous les projets,
// pour cet utilisateur, et on compte les blocs qui portent l identifiant. Les
// identifiants sont stables et independants du chemin.
if ($route === 'usages' && !$poste) {
    $fid = trim(isset($_GET['id']) ? $_GET['id'] : '');
    if (!preg_match('/^[0-9a-f]{6,32}$/', $fid)) {
        erreur('invalid id');
    }
    $out = array();
    $l = projets_publies();
    foreach ($l['projets'] as $pr) {
        $dos = dossier_montages($pr);
        foreach ((array) @scandir($dos) as $n) {
            if (substr(strtolower($n), -5) !== '.json') {
                continue;
            }
            $m = lire_json($dos . '/' . $n, array());
            $k = 0;
            foreach ((isset($m['clips']) ? $m['clips'] : array()) as $x) {
                if (isset($x['film']) && $x['film'] === $fid) {
                    $k++;
                }
            }
            if ($k) {
                $out[] = array('projet' => $pr, 'nom' => substr($n, 0, -5),
                    'blocs' => $k,
                    'maj' => date('Y-m-d H:i', filemtime($dos . '/' . $n)));
            }
        }
    }
    usort($out, function ($a, $b) {
        return strcmp($b['maj'], $a['maj']);
    });
    repondre(array('ok' => true, 'id' => $fid, 'usages' => $out));
}

// ---- GET /api/polices ------------------------------------------------------
if ($route === 'polices' && !$poste) {
    $dos = __DIR__ . '/_polices';
    $out = array();
    foreach ((array) @scandir($dos) as $n) {
        $e = strtolower(pathinfo($n, PATHINFO_EXTENSION));
        if (!in_array($e, array('ttf', 'otf', 'ttc', 'woff', 'woff2'), true)) {
            continue;
        }
        $out[] = array('nom' => $n, 'octets' => filesize($dos . '/' . $n),
            // « rendu » dit si ffmpeg saurait la graver. Sans ffmpeg en ligne
            // la reponse est non, mais le champ reste pour que le meme
            // app.html lise les deux serveurs sans condition.
            'rendu' => false);
    }
    repondre(array('polices' => $out, 'dossier' => ''));
}

// ---- GET et POST /api/presets ---------------------------------------------
if ($route === 'presets') {
    $g = $poste
        ? (isset($d['genre']) ? $d['genre'] : 'secousse')
        : (isset($_GET['genre']) ? $_GET['genre'] : 'secousse');
    $f = fichier_presets($g);
    if ($f === null) {
        erreur('invalid preset kind');
    }
    $l = lire_json($f, array());
    if (!$poste) {
        // Un tableau PHP vide s encoderait en [] : on force l objet, sinon
        // l application recevrait une liste la ou elle attend un
        // dictionnaire nomme.
        repondre(array('ok' => true, 'genre' => $g,
            'presets' => (object) $l));
    }
    if (isset($d['presets']) && is_array($d['presets'])) {
        if ($l) {
            repondre(array('ok' => true, 'genre' => $g,
                'presets' => (object) $l, 'reprise' => false));
        }
        $n = array();
        foreach ($d['presets'] as $k => $v) {
            $k2 = nom_preset($k);
            if ($k2 !== '') {
                $n[$k2] = $v;
            }
        }
        ecrire_json($f, $n);
        repondre(array('ok' => true, 'genre' => $g,
            'presets' => (object) $n, 'reprise' => true));
    }
    $nom = nom_preset(isset($d['nom']) ? $d['nom'] : '');
    if ($nom === '') {
        erreur('name the preset');
    }
    if (!empty($d['effacer'])) {
        if (!array_key_exists($nom, $l)) {
            erreur('no such preset', 404);
        }
        unset($l[$nom]);
    } else {
        if (!array_key_exists($nom, $l) && count($l) >= MAX_PRESETS) {
            erreur('too many presets (' . MAX_PRESETS . ')');
        }
        $l[$nom] = isset($d['valeur']) ? $d['valeur'] : null;
    }
    ecrire_json($f, $l);
    repondre(array('ok' => true, 'genre' => $g,
        'presets' => (object) $l));
}

// ---- ce qui n existe pas en ligne -----------------------------------------
$FFMPEG = 'this hosting has no ffmpeg';
$DISQUE = 'it moves the files themselves, and they live on your computer';
$DOSSIERS = 'the folders here only mirror the ones on your computer, and '
    . 'a folder made here would vanish at the next publish';
$LOCAL = 'there is no desktop server behind this page';

$bureau = array(
    'scan' => array('scanning', 'it reads the video files themselves, and '
        . 'they live on your computer'),
    'rendre' => array('rendering', $FFMPEG),
    'rendu' => array('rendering', $FFMPEG),
    'poster' => array('making thumbnails', $FFMPEG),
    'texte' => array('burning text into the image', $FFMPEG),
    'importer' => array('importing', $DISQUE),
    'deplacer' => array('moving rushes', $DISQUE),
    'renommer' => array('renaming a rush', $DISQUE),
    'annuler' => array('undoing on disk', $DISQUE),
    'parcourir' => array('browsing folders', 'the folder picker opens on '
        . 'your computer'),
    'police' => array('adding a font', 'fonts are installed next to the '
        . 'desktop app'),
    'projet/creer' => array('creating a project', $DOSSIERS),
    'dossier/creer' => array('creating a folder', $DOSSIERS),
    'dossier/renommer' => array('renaming a folder', $DOSSIERS),
    'dossier/effacer' => array('deleting a folder', $DOSSIERS),
    'marquer' => array('marking favourites and colours', 'marks are written '
        . 'into the catalogue, which is rebuilt from your computer at each '
        . 'publish, so a mark made here would be erased'),
    'purger' => array('removing missing clips', 'the catalogue here is '
        . 'rebuilt from your computer at each publish, and missing clips are '
        . 'never published'),
    'maj' => array('updating the program', 'this site is republished from '
        . 'your computer, where the library updates itself'),
    'arret' => array('stopping the server', $LOCAL),
    'vivant' => array('the heartbeat', $LOCAL),
    'adieu' => array('the goodbye', $LOCAL),
    'scan_etat' => array('scan progress', $LOCAL),
    'import_etat' => array('import progress', $LOCAL),
);
if (isset($bureau[$route])) {
    hors_ligne($bureau[$route][0], $bureau[$route][1]);
}

erreur('unknown route: ' . $route, 404);

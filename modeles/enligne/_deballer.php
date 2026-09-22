<?php
// ===========================================================================
//  Deballeur de paquet — Library Editor
// ===========================================================================
// Depose a cote des .zip du paquet, il les decompresse ICI, par tranches de
// quelques secondes (un hebergement coupe un script apres 30 a 60 s), puis
// efface les .zip et s efface lui-meme. Il ne sert qu une fois.
//
// Rejouable : un fichier deja present, de meme taille et meme contenu, est
// saute. Une coupure en route ? On recharge la page, ca reprend.
//
// La cle ci-dessous est tiree au hasard a chaque paquet : sans elle, ce
// script ne fait rien.
define('CLE', '%%CLE%%');

@set_time_limit(0);
@ini_set('memory_limit', '512M');
$ici = __DIR__;
$cle = isset($_GET['cle']) ? (string) $_GET['cle'] : '';
$action = isset($_GET['action']) ? (string) $_GET['action'] : '';

function sortie_json($o)
{
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store');
    echo json_encode($o, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    exit;
}

function les_zips($ici)
{
    $l = array();
    foreach ((array) @scandir($ici) as $n) {
        if (preg_match('/^[0-9]+-[A-Za-z0-9_-]+\.zip$/', $n)) {
            $l[] = $n;
        }
    }
    natsort($l);
    return array_values($l);
}

if (strlen(CLE) < 16 || !hash_equals(CLE, $cle)) {
    http_response_code(403);
    header('Content-Type: text/plain; charset=utf-8');
    echo "Cle absente ou fausse. Utilisez l'adresse complete donnee par Library Editor.";
    exit;
}

if ($action === 'inventaire') {
    if (!class_exists('ZipArchive')) {
        sortie_json(array('ok' => false, 'erreur' => "L'extension PHP zip est "
            . "absente : hPanel > Advanced > PHP Configuration > PHP extensions, "
            . "cochez zip, puis rechargez cette page."));
    }
    $out = array();
    foreach (les_zips($ici) as $n) {
        $z = new ZipArchive();
        if ($z->open($ici . '/' . $n) !== true) {
            $out[] = array('zip' => $n, 'entrees' => -1);
            continue;
        }
        $out[] = array('zip' => $n, 'entrees' => $z->numFiles,
            'octets' => filesize($ici . '/' . $n));
        $z->close();
    }
    sortie_json(array('ok' => true, 'zips' => $out, 'php' => PHP_VERSION));
}

if ($action === 'etape') {
    $n = isset($_GET['zip']) ? basename((string) $_GET['zip']) : '';
    $debut = isset($_GET['offset']) ? max(0, (int) $_GET['offset']) : 0;
    if (!in_array($n, les_zips($ici), true)) {
        sortie_json(array('ok' => false, 'erreur' => 'zip inconnu : ' . $n));
    }
    $z = new ZipArchive();
    if ($z->open($ici . '/' . $n) !== true) {
        sortie_json(array('ok' => false, 'erreur' => 'zip illisible : ' . $n
            . ' (envoi incomplet ? renvoyez-le)'));
    }
    $t0 = microtime(true);
    $ecrits = 0;
    $sautes = 0;
    $erreurs = array();
    $i = $debut;
    for (; $i < $z->numFiles; $i++) {
        if (microtime(true) - $t0 > 12) {
            break;
        }
        $s = $z->statIndex($i);
        $rel = str_replace(chr(92), '/', $s['name']);
        if ($rel === '' || substr($rel, -1) === '/') {
            continue;
        }
        // Traversee de chemin, chemins absolus : jamais hors de ce dossier.
        if (strpos($rel, '../') !== false || $rel[0] === '/'
                || preg_match('/^[A-Za-z]:/', $rel)) {
            $erreurs[] = 'refuse : ' . $rel;
            continue;
        }
        $base = basename($rel);
        if ($base === '.DS_Store' || strpos($base, '._') === 0) {
            continue;
        }
        $cible = $ici . '/' . $rel;
        if (is_file($cible) && filesize($cible) === (int) $s['size']) {
            // Meme taille : les petits fichiers (index, pages) peuvent avoir
            // change sans changer de taille, on compare leur contenu.
            if ($s['size'] > 20 * 1024 * 1024
                    || sprintf('%08x', $s['crc']) === hash_file('crc32b', $cible)) {
                $sautes++;
                continue;
            }
        }
        $dos = dirname($cible);
        if (!is_dir($dos) && !@mkdir($dos, 0755, true)) {
            $erreurs[] = 'dossier impossible : ' . dirname($rel);
            continue;
        }
        $entree = $z->getStream($s['name']);
        $tmp = $cible . '.part-deballage';
        $out = $entree ? @fopen($tmp, 'wb') : false;
        if (!$entree || !$out) {
            $erreurs[] = 'ecriture impossible : ' . $rel;
            if ($entree) {
                fclose($entree);
            }
            continue;
        }
        stream_copy_to_stream($entree, $out);
        fclose($out);
        fclose($entree);
        if (!@rename($tmp, $cible)) {
            @unlink($tmp);
            $erreurs[] = 'remplacement impossible : ' . $rel;
            continue;
        }
        $ecrits++;
    }
    $total = $z->numFiles;
    $z->close();
    sortie_json(array('ok' => true, 'zip' => $n, 'offset' => $i, 'total' => $total,
        'fini' => $i >= $total, 'ecrits' => $ecrits, 'sautes' => $sautes,
        'erreurs' => $erreurs));
}

if ($action === 'nettoyer') {
    $effaces = array();
    foreach (les_zips($ici) as $n) {
        if (@unlink($ici . '/' . $n)) {
            $effaces[] = $n;
        }
    }
    $moi = @unlink(__FILE__);
    sortie_json(array('ok' => true, 'effaces' => $effaces, 'moi' => $moi));
}

header('Content-Type: text/html; charset=utf-8');
header('Cache-Control: no-store');
?><!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Deballage du paquet</title>
<style>
:root{--fond:#111214;--carte:#191a1d;--trait:#2a2c30;--encre:#ecebe8;--doux:#9a9ca3;--accent:#d6a45c;--ok:#6fbf8a;--mal:#e0786b}
*{box-sizing:border-box}body{margin:0;background:var(--fond);color:var(--encre);font:15px/1.55 "Segoe UI",system-ui,sans-serif;display:grid;place-items:center;min-height:100vh;padding:24px 16px}
main{width:min(620px,100%);background:var(--carte);border:1px solid var(--trait);border-radius:14px;padding:28px 28px 24px}
h1{margin:0 0 6px;font-size:21px;font-weight:600}p{margin:6px 0;color:var(--doux)}
.barre{height:8px;background:#232428;border-radius:99px;overflow:hidden;margin:18px 0 8px}.barre i{display:block;height:100%;width:0;background:var(--accent);transition:width .25s}
#etat{font-size:13px;color:var(--doux);min-height:20px}#journal{margin-top:14px;font:12px/1.5 Consolas,monospace;color:var(--doux);max-height:180px;overflow:auto}
button{font:inherit;font-weight:600;background:var(--accent);color:#1a1510;border:0;border-radius:9px;padding:10px 18px;cursor:pointer;margin-top:16px}button:disabled{opacity:.5;cursor:default}
a{color:var(--accent)}.ok{color:var(--ok)}.mal{color:var(--mal)}
</style></head><body><main>
<h1>Déballage du paquet</h1>
<p>Décompresse ici les fichiers .zip envoyés, puis les efface avec ce script. Laissez cette page ouverte jusqu'à « Terminé ».</p>
<div class="barre"><i id="barre"></i></div>
<div id="etat">Prêt.</div>
<button id="go">Déballer</button>
<div id="journal"></div>
</main>
<script>
const CLE = new URLSearchParams(location.search).get('cle') || '';
const $ = id => document.getElementById(id);
function note(t, c) { const d = document.createElement('div'); d.textContent = t; if (c) d.className = c; $('journal').prepend(d); }
async function appel(q) {
  for (let essai = 1; essai <= 4; essai++) {
    try {
      const r = await fetch('?cle=' + encodeURIComponent(CLE) + '&' + q, {cache: 'no-store'});
      return await r.json();
    } catch (e) {
      if (essai === 4) throw e;
      note('Coupure, nouvel essai...');
      await new Promise(ok => setTimeout(ok, 1500 * essai));
    }
  }
}
$('go').onclick = async () => {
  $('go').disabled = true;
  try {
    const inv = await appel('action=inventaire');
    if (!inv.ok) { $('etat').textContent = inv.erreur; $('etat').className = 'mal'; $('go').disabled = false; return; }
    if (!inv.zips.length) { $('etat').textContent = 'Aucun fichier .zip du paquet dans ce dossier.'; $('etat').className = 'mal'; $('go').disabled = false; return; }
    const total = inv.zips.reduce((s, z) => s + Math.max(0, z.entrees), 0);
    let fait = 0, erreurs = 0;
    for (const z of inv.zips) {
      if (z.entrees < 0) { note(z.zip + ' : illisible (envoi incomplet ?)', 'mal'); erreurs++; continue; }
      let offset = 0, r;
      do {
        r = await appel('action=etape&zip=' + encodeURIComponent(z.zip) + '&offset=' + offset);
        if (!r.ok) { note(r.erreur, 'mal'); erreurs++; break; }
        fait += r.offset - offset; offset = r.offset;
        (r.erreurs || []).forEach(e => { note(e, 'mal'); erreurs++; });
        $('barre').style.width = (100 * fait / Math.max(1, total)).toFixed(1) + '%';
        $('etat').textContent = z.zip + ' : ' + offset + ' / ' + r.total + ' fichiers';
      } while (!r.fini);
      note(z.zip + ' : décompressé', 'ok');
    }
    if (erreurs) {
      $('etat').textContent = erreurs + ' problème(s) : les .zip sont gardés. Corrigez puis rechargez cette page.';
      $('etat').className = 'mal'; $('go').disabled = false; return;
    }
    const n = await appel('action=nettoyer');
    $('barre').style.width = '100%';
    $('etat').innerHTML = '';
    const ok = document.createElement('span'); ok.className = 'ok';
    ok.textContent = 'Terminé. ' + n.effaces.length + ' fichier(s) .zip effacé(s)' + (n.moi ? ', et ce script aussi. ' : '. Effacez _deballer.php à la main. ');
    const a = document.createElement('a'); a.href = './'; a.textContent = 'Ouvrir le site';
    $('etat').append(ok, a);
  } catch (e) {
    $('etat').textContent = 'Interrompu : ' + e.message + '. Rechargez la page pour reprendre.';
    $('etat').className = 'mal'; $('go').disabled = false;
  }
};
</script></body></html>

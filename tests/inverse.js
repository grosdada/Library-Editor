// On EXTRAIT le code livre de app.html et on l execute : pas de recopie,
// donc pas de risque d essayer autre chose que ce qui part chez David.
const fs = require('fs');
const src = fs.readFileSync(process.argv[2], 'utf8');

function extraire(debut, fin, quoi) {
  const i = src.indexOf(debut);
  if (i < 0) throw new Error('introuvable : ' + quoi);
  const j = src.indexOf(fin, i);
  return src.slice(i, j + fin.length);
}

const helpers = extraire('const vAbs = c =>', 'const dur = c => Math.max(0.04, (c.o - c.e) / vAbs(c));', 'helpers');
const couperSrc = extraire('function couper(c, t) {', '\n}', 'couper');
const rognage = extraire("          if (cote === 'g') {\n            const no = Math.max(", "            s.c.e = Math.min(Math.max(0, s.e - d), s.c.o - 0.08);\n          }", 'rognage');

let CLIPS = [], uidSuivant = 100, sorties = [];
const memoriser = () => {};
const lienLibre = () => 7;
const clipsSel = {clear(){}};
const rendreTimeline = () => {};
const dire = m => sorties.push(m);
const tc = t => String(t);
let groupeLie = c => [c];
eval(helpers.replace(/^const (\w+) =/gm, 'globalThis.$1 ='));
globalThis.fin = c => c.t0 + dur(c);
const couper = eval('(' + couperSrc + ')');

let ok = 0, ko = 0;
function verif(nom, cond, detail) {
  if (cond) { ok++; console.log('  ok   ' + nom); }
  else { ko++; console.log('  ECHEC ' + nom + (detail ? '  ' + detail : '')); }
}
const proche = (a, b) => Math.abs(a - b) < 1e-9;

console.log('--- srcA / tlA -------------------------------------------------');
const av = {t0: 5, e: 2, o: 8, vitesse: 2, rev: false};
const ar = {t0: 5, e: 2, o: 8, vitesse: 2, rev: true};
verif('meme duree a l endroit et a l envers', proche(dur(av), dur(ar)), dur(av) + ' vs ' + dur(ar));
verif('endroit : commence sur e', proche(srcA(av, av.t0), 2));
verif('endroit : finit sur o', proche(srcA(av, fin(av)), 8));
verif('envers  : commence sur o', proche(srcA(ar, ar.t0), 8));
verif('envers  : finit sur e', proche(srcA(ar, fin(ar)), 2));
let aller = true;
for (let k = 0; k <= 20; k++) {
  const t = ar.t0 + (k / 20) * dur(ar);
  if (!proche(tlA(ar, srcA(ar, t)), t)) aller = false;
}
verif('envers  : aller-retour temps <-> source exact', aller);
verif('envers  : la source reste dans [e, o]',
  [...Array(21).keys()].every(k => {
    const s = srcA(ar, ar.t0 + (k / 20) * dur(ar));
    return s >= ar.e - 1e-9 && s <= ar.o + 1e-9;
  }));
verif('vitesse signee', vSignee(ar) === -2 && vSignee(av) === 2);

console.log('--- decoupe ----------------------------------------------------');
function essaiCoupe(rev) {
  CLIPS = [];
  const c = {uid: 1, t0: 5, e: 2, o: 8, vitesse: 2, rev: rev, fi: 0.5, fo: 0.4};
  CLIPS.push(c);
  const tCoupe = 5 + dur(c) / 3;          // au tiers
  const imAvant = [];
  for (let k = 0; k <= 60; k++) {
    const t = c.t0 + (k / 60) * dur(c);
    imAvant.push([t, srcA(c, t)]);
  }
  couper(c, tCoupe);
  const g = CLIPS[0], d = CLIPS[1];
  const nom = rev ? 'envers' : 'endroit';
  verif(nom + ' : deux morceaux', CLIPS.length === 2);
  verif(nom + ' : les durees se somment',
    proche(dur(g) + dur(d), 3), (dur(g) + dur(d)).toFixed(6));
  verif(nom + ' : pas de trou ni de recouvrement',
    proche(fin(g), d.t0), fin(g) + ' / ' + d.t0);
  verif(nom + ' : la source est couverte entierement, une seule fois',
    proche(Math.min(g.e, d.e), 2) && proche(Math.max(g.o, d.o), 8) &&
    (proche(g.e, d.o) || proche(g.o, d.e)),
    'g[' + g.e + ',' + g.o + '] d[' + d.e + ',' + d.o + ']');
  // L IMAGE MONTREE a chaque instant doit etre la meme qu avant la coupe.
  let memeImage = true, pire = 0;
  for (const [t, s] of imAvant) {
    const x = (t < d.t0 - 1e-9) ? g : d;
    const e = Math.abs(srcA(x, t) - s);
    if (e > pire) pire = e;
    if (e > 1e-9) memeImage = false;
  }
  verif(nom + ' : chaque instant montre la MEME image qu avant la coupe',
    memeImage, 'ecart max ' + pire.toExponential(2));
  verif(nom + ' : fondus, gauche garde fi et perd fo',
    g.fi === 0.5 && g.fo === 0 && d.fi === 0 && d.fo === 0.4);
}
essaiCoupe(false);
essaiCoupe(true);

console.log('--- rognage ----------------------------------------------------');
function essaiRogne(cote, dTl) {
  const c = {uid: 1, t0: 5, e: 2, o: 8, vitesse: 2, rev: true};
  const s = {c: c, t0: c.t0, e: c.e, o: c.o};
  const vit = vAbs(c), d = dTl * vit;
  const PAR_ID = {}, f = null, max = 15;
  eval(rognage);
  return c;
}
let c1 = essaiRogne('g', 0.5);
verif('envers, bord gauche : le bout de queue (e) ne bouge pas', proche(c1.e, 2));
verif('envers, bord gauche : le plan demarre 0,5 s plus tard', proche(c1.t0, 5.5));
verif('envers, bord gauche : la duree perd 0,5 s', proche(dur(c1), 2.5), dur(c1).toFixed(4));
let c2 = essaiRogne('d', 0.5);
verif('envers, bord droit : la tete (o) ne bouge pas', proche(c2.o, 8));
verif('envers, bord droit : le debut ne bouge pas', proche(c2.t0, 5));
verif('envers, bord droit : la duree gagne 0,5 s', proche(dur(c2), 3.5), dur(c2).toFixed(4));

console.log('\n' + ok + ' verifications passees, ' + ko + ' echec(s)');
process.exit(ko ? 1 : 0);

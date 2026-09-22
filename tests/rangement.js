const fs = require('fs');
const src = fs.readFileSync(process.argv[2], 'utf8');
const pren = (a, b, quoi) => {
  const i = src.indexOf(a);
  if (i < 0) throw new Error('introuvable : ' + quoi);
  const j = src.indexOf(b, i);
  if (j < 0) throw new Error('fin introuvable : ' + quoi);
  return src.slice(i, j + b.length);
};

// --- le code livre, pris tel quel ---------------------------------------
const etat = pren("let VUE = 'source';",
  ": f.pj + (f.dossier ? '/' + f.dossier : '');", 'etat');
const creer = pren('function creerDossierVirtuel(pj, parent, nom) {',
  "\n}", 'creer');
const renom = pren('async function renommerDossierVirtuel(pj, ancien, neuf) {',
  "\n}", 'renommer');
const effac = pren('async function effacerDossierVirtuel(pj, rel) {',
  "\n}", 'effacer');
const refon = pren('function refondre() {', '\n}', 'refondre');

globalThis.dire = () => {};
globalThis.dossierActif = null;
globalThis.OUVERTS = [];
globalThis.FILMS = [];
globalThis.DOSSIERS = [];
globalThis.PAR_ID = {};
globalThis.indexer = () => { PAR_ID = {}; FILMS.forEach(f => PAR_ID[f.id] = f); };
globalThis.estBibli = () => false;
globalThis.rendre = () => {};
globalThis.enregistrerRangement = async () => {};
eval(etat.replace(/^let (\w+)/gm, 'globalThis.$1')
        .replace(/^const (\w+)/gm, 'globalThis.$1'));
globalThis.creerDossierVirtuel = eval('(' + creer + ')');
globalThis.renommerDossierVirtuel = eval('(' + renom + ')');
globalThis.effacerDossierVirtuel = eval('(' + effac + ')');
globalThis.refondre = eval('(' + refon + ')');

let ok = 0, ko = 0;
const v = (nom, cond, det) => cond
  ? (ok++, console.log('  ok    ' + nom))
  : (ko++, console.log('  ECHEC ' + nom + (det ? '  ' + det : '')));

// --- un fonds d essai ----------------------------------------------------
const films = [
  {id: 'aaaaaaaaaaaa', nom: 'r1', dossier: 'Gary-Kling'},
  {id: 'bbbbbbbbbbbb', nom: 'r2', dossier: 'Gary-Kling'},
  {id: 'cccccccccccc', nom: 'r3', dossier: 'course desert'},
  {id: 'dddddddddddd', nom: 'r4', dossier: ''},
];
OUVERTS = [{nom: 'GARY-ALL', films: films, dossiers: ['Gary-Kling', 'course desert']}];
refondre();

console.log('--- vue SOURCE : rien ne doit changer ---------------------------');
v('4 rushes', FILMS.length === 4);
v('2 dossiers de tournage', DOSSIERS.length === 2, JSON.stringify(DOSSIERS.map(d => d.d)));
v('un rush est dans son dossier de tournage',
  clefDossier(films[0]) === 'GARY-ALL/Gary-Kling', clefDossier(films[0]));

console.log('--- vue RANGEMENT : tout est non range au depart ----------------');
VUE = 'rangement';
refondre();
v('un seul dossier : « non range »',
  DOSSIERS.length === 1 && DOSSIERS[0].d === NONRANGE,
  JSON.stringify(DOSSIERS.map(d => d.d)));
v('chaque rush y tombe', films.every(f => clefDossier(f).endsWith(NONRANGE)));

console.log('--- creer, ranger ----------------------------------------------');
creerDossierVirtuel('GARY-ALL', '', 'Selection');
creerDossierVirtuel('GARY-ALL', 'Selection', 'Gros plans');
refondre();
v('deux dossiers plus le non range', DOSSIERS.length === 3,
  JSON.stringify(DOSSIERS.map(d => d.d)));
const r = rangementDe('GARY-ALL');
r.ou['aaaaaaaaaaaa'] = 'Selection/Gros plans';
r.ou['bbbbbbbbbbbb'] = 'Selection';
refondre();
v('le rush range est vu dans SON dossier virtuel',
  clefDossier(films[0]) === 'GARY-ALL/Selection/Gros plans', clefDossier(films[0]));
v('le dossier de tournage est intact', films[0].dossier === 'Gary-Kling');
v('l identifiant est intact', films[0].id === 'aaaaaaaaaaaa');

console.log('--- renommer un dossier qui a des enfants -----------------------');
(async () => {
  await renommerDossierVirtuel('GARY-ALL', 'Selection', 'Montage 1');
  v('le dossier est renomme', r.dossiers.includes('Montage 1'));
  v('le sous-dossier a suivi', r.dossiers.includes('Montage 1/Gros plans'),
    JSON.stringify(r.dossiers));
  v('aucune trace de l ancien nom',
    !r.dossiers.some(x => x.startsWith('Selection')));
  v('les rushes ont suivi, en profondeur',
    r.ou['aaaaaaaaaaaa'] === 'Montage 1/Gros plans' &&
    r.ou['bbbbbbbbbbbb'] === 'Montage 1', JSON.stringify(r.ou));

  console.log('--- effacer un dossier ne perd aucun rush -----------------------');
  await effacerDossierVirtuel('GARY-ALL', 'Montage 1');
  v('le dossier et ses enfants sont partis', r.dossiers.length === 0,
    JSON.stringify(r.dossiers));
  v('les rushes redeviennent non ranges', Object.keys(r.ou).length === 0);
  refondre();
  v('les 4 rushes sont toujours la', FILMS.length === 4);
  v('et leur dossier de tournage n a jamais bouge',
    films[0].dossier === 'Gary-Kling' && films[2].dossier === 'course desert');

  console.log('--- retour en vue source ---------------------------------------');
  VUE = 'source';
  refondre();
  v('les dossiers de tournage sont revenus intacts',
    DOSSIERS.length === 2 && DOSSIERS[0].d === 'Gary-Kling');

  console.log('\n' + ok + ' verifications passees, ' + ko + ' echec(s)');
  process.exit(ko ? 1 : 0);
})();

/* Navigation: Ansichten registrieren und ohne gegenseitige Importe wechseln. */
import { R } from './daten.js';

export const ansichten = {};
let aktuelle = 'overview';

export function registriereAnsicht(name, modul){ ansichten[name] = modul; }

const navToggle = document.querySelector('#navToggle');
const querformatAbfrage = window.matchMedia('(orientation: landscape) and (max-width: 950px) and (max-height: 500px)');

function querformatAktiv(){ return querformatAbfrage.matches; }

export function setzeNavEingeklappt(eingeklappt){
  document.body.classList.toggle('nav-eingeklappt', Boolean(eingeklappt) && querformatAktiv());
  if(navToggle) navToggle.setAttribute('aria-expanded', String(!document.body.classList.contains('nav-eingeklappt')));
}

if(navToggle){
  navToggle.onclick = () => setzeNavEingeklappt(!document.body.classList.contains('nav-eingeklappt'));
  const syncNav = () => setzeNavEingeklappt(aktuelle === 'ship' && querformatAktiv());
  if(querformatAbfrage.addEventListener) querformatAbfrage.addEventListener('change', syncNav);
  else if(querformatAbfrage.addListener) querformatAbfrage.addListener(syncNav);
}

document.querySelectorAll('.nav').forEach(b => b.onclick = () => zeige(b.dataset.v));

export function zeige(v){
  if(!ansichten[v]) return;
  if(v !== aktuelle) ansichten[aktuelle]?.deaktiviere?.();
  aktuelle = v;
  if(v === 'ship') setzeNavEingeklappt(true);
  ansichten[v]?.aktiviere?.();
  document.querySelectorAll('.nav').forEach(b=>b.classList.toggle('on',b.dataset.v===v));
  document.querySelectorAll('.view').forEach(s=>s.hidden = s.id !== 'v-'+v);
  zeichne();
}

export function zeichne(){
  if(!R) return;
  ansichten[aktuelle]?.render?.();
}

export function aktuelleAnsicht(){ return aktuelle; }

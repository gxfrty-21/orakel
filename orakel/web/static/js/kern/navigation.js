/* Navigation: Ansichten registrieren, per URL ansteuern und fokussieren. */
import { R } from './daten.js';

export const ansichten = {};
const STANDARD = 'overview';
const SPRUNGMARKE_INHALT = '#inhalt';
const navLinks = [...document.querySelectorAll('.nav[data-v]')];
const sichtbareAnsichten = new Set(navLinks.map(link => link.dataset.v));

let aktuelle = STANDARD;
let initialisiert = false;

export function registriereAnsicht(name, modul){ ansichten[name] = modul; }

const hauptnav = document.querySelector('#hauptnav');
const navToggle = document.querySelector('#navToggle');
const querformatAbfrage = window.matchMedia('(orientation: landscape) and (max-width: 950px) and (max-height: 500px)');

function querformatAktiv(){ return querformatAbfrage.matches; }

export function setzeNavEingeklappt(eingeklappt){
  document.body.classList.toggle('nav-eingeklappt', Boolean(eingeklappt) && querformatAktiv());
  if(navToggle) navToggle.setAttribute('aria-expanded', String(!document.body.classList.contains('nav-eingeklappt')));
  aktualisiereNavRaender();
}

if(navToggle){
  navToggle.onclick = () => setzeNavEingeklappt(!document.body.classList.contains('nav-eingeklappt'));
  const syncNav = () => setzeNavEingeklappt(aktuelle === 'ship' && querformatAktiv());
  if(querformatAbfrage.addEventListener) querformatAbfrage.addEventListener('change', syncNav);
  else if(querformatAbfrage.addListener) querformatAbfrage.addListener(syncNav);
}

function urlFuer(v){ return '#/' + v; }

function routeAusHash(){
  const treffer = /^#\/([a-z0-9-]+)$/.exec(location.hash);
  return treffer && sichtbareAnsichten.has(treffer[1]) ? treffer[1] : null;
}

function halteAktivenLinkSichtbar(link){
  const nav = link.closest('#hauptnav');
  if(!nav) return;

  if(nav.scrollWidth > nav.clientWidth + 1){
    const navKasten = nav.getBoundingClientRect();
    const linkKasten = link.getBoundingClientRect();
    if(linkKasten.left < navKasten.left || linkKasten.right > navKasten.right){
      const ziel = Math.max(0, Math.min(
        nav.scrollLeft + linkKasten.left - navKasten.left - (nav.clientWidth - linkKasten.width) / 2,
        nav.scrollWidth - nav.clientWidth,
      ));
      nav.scrollLeft = ziel;
    }
  }

  const liste = link.closest('.nav-liste');
  if(liste && liste.scrollHeight > liste.clientHeight + 1){
    const listeKasten = liste.getBoundingClientRect();
    const linkKasten = link.getBoundingClientRect();
    if(linkKasten.top < listeKasten.top || linkKasten.bottom > listeKasten.bottom){
      const ziel = Math.max(0, Math.min(
        liste.scrollTop + linkKasten.top - listeKasten.top - (liste.clientHeight - linkKasten.height) / 2,
        liste.scrollHeight - liste.clientHeight,
      ));
      liste.scrollTop = ziel;
    }
  }
}

function aktualisiereNavHoehe(){
  if(!hauptnav) return;
  const liste = hauptnav.querySelector('.nav-liste');
  if(!liste) return;
  const abstand = Math.max(0, liste.offsetTop);
  const verfuegbar = Math.max(0, window.innerHeight - abstand);
  hauptnav.style.setProperty('--nav-sticky-max', `${verfuegbar}px`);
}

function aktualisiereNavRaender(){
  if(!hauptnav) return;
  const ueberlaeuft = hauptnav.scrollWidth > hauptnav.clientWidth + 1;
  const kasten = hauptnav.getBoundingClientRect();
  const erster = navLinks[0];
  const letzter = navLinks[navLinks.length - 1];
  const linksVerdeckt = Boolean(erster) && erster.getBoundingClientRect().left < kasten.left - 1;
  const rechtsVerdeckt = Boolean(letzter) && letzter.getBoundingClientRect().right > kasten.right + 1;
  hauptnav.classList.toggle('fade-links', ueberlaeuft && linksVerdeckt);
  hauptnav.classList.toggle('fade-rechts', ueberlaeuft && rechtsVerdeckt);
}

function setzeAktive(v){
  let aktiverLink = null;
  navLinks.forEach(link => {
    const aktiv = link.dataset.v === v;
    link.classList.toggle('on', aktiv);
    if(aktiv){
      link.setAttribute('aria-current', 'page');
      aktiverLink = link;
    }else{
      link.removeAttribute('aria-current');
    }
  });
  aktualisiereNavHoehe();
  if(aktiverLink) halteAktivenLinkSichtbar(aktiverLink);
  aktualisiereNavRaender();
}

function aktualisiereAktivenLink(){
  aktualisiereNavHoehe();
  const aktiv = navLinks.find(link => link.dataset.v === aktuelle);
  if(aktiv) halteAktivenLinkSichtbar(aktiv);
  aktualisiereNavRaender();
}

let navGroesseRahmen = 0;
window.addEventListener('resize', () => {
  if(navGroesseRahmen) return;
  navGroesseRahmen = requestAnimationFrame(() => {
    navGroesseRahmen = 0;
    aktualisiereAktivenLink();
  });
});
window.addEventListener('load', aktualisiereAktivenLink);
if(hauptnav) hauptnav.addEventListener('scroll', aktualisiereNavRaender, { passive: true });

// Kopfzeile und Banner können ihre Höhe nach dem ersten Rendern ändern (z. B.
// durch nachgeladene Statuschips). Dann muss die verfügbare Listenhöhe neu
// berechnet und der aktive Link erneut ausgerichtet werden.
if(typeof ResizeObserver === 'function'){
  const beobachter = new ResizeObserver(() => aktualisiereAktivenLink());
  [document.querySelector('.top'), document.querySelector('.banner')]
    .filter(Boolean)
    .forEach(element => beobachter.observe(element));
}

function setzeTitel(v){
  const eintrag = navLinks.find(link => link.dataset.v === v);
  const titel = eintrag?.querySelector('b')?.textContent?.trim()
    || document.querySelector(`#v-${v} h1`)?.textContent?.trim()
    || v;
  document.title = `${titel} · Orakel`;
}

function fokussiereAnsicht(v){
  const ansicht = document.querySelector(`#v-${v}`);
  if(!ansicht || ansicht.hidden) return;
  const ziel = ansicht.querySelector('h1') || ansicht;
  if(!ziel.hasAttribute('tabindex')) ziel.setAttribute('tabindex', '-1');
  ziel.focus();
}

function setzeAnsicht(v, { url = null, fokus = false } = {}){
  if(!ansichten[v]) return false;
  const vorher = aktuelle;
  if(v !== aktuelle) ansichten[aktuelle]?.deaktiviere?.();
  aktuelle = v;
  if(v === 'ship') setzeNavEingeklappt(true);
  else if(vorher === 'ship') setzeNavEingeklappt(false);
  ansichten[v]?.aktiviere?.();
  setzeAktive(v);
  setzeTitel(v);
  document.querySelectorAll('.view').forEach(s => { s.hidden = s.id !== 'v-' + v; });

  if(url === 'push' && location.hash !== urlFuer(v)) history.pushState(null, '', urlFuer(v));
  else if(url === 'replace' && location.hash !== urlFuer(v)) history.replaceState(null, '', urlFuer(v));

  zeichne();
  if(fokus) fokussiereAnsicht(v);
  return true;
}

/**
 * Wechselt die Ansicht. Sichtbare Bereiche schreiben ihre URL in den Verlauf;
 * die Prüfbrücke darf auch die nicht in der Sidebar sichtbaren Ansichten öffnen.
 */
export function zeige(v, optionen = {}){
  return setzeAnsicht(v, {
    url: optionen.url ?? (sichtbareAnsichten.has(v) ? 'push' : null),
    fokus: optionen.fokus ?? false,
  });
}

function routeAktualisieren(){
  // Der Skip-Link setzt nur den Fokus und ist keine Bereichsroute.
  if(location.hash === SPRUNGMARKE_INHALT) return;
  const route = routeAusHash();
  const ziel = route || STANDARD;
  if(ziel === aktuelle && location.hash === urlFuer(ziel)) return;
  setzeAnsicht(ziel, { url: route ? null : 'replace', fokus: true });
}

/** Muss nach allen registriereAnsicht()-Aufrufen aus main.js laufen. */
export function initialisiereNavigation(){
  if(initialisiert) return;
  initialisiert = true;
  const start = routeAusHash() || STANDARD;
  setzeAnsicht(start, { url: 'replace' });
}

navLinks.forEach(link => {
  link.addEventListener('click', ev => {
    // Modifizierte Klicks sollen weiter in einem neuen Tab/Fenster öffnen.
    if(ev.button !== 0 || ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey) return;
    ev.preventDefault();
    zeige(link.dataset.v, { fokus: true });
  });
});

window.addEventListener('popstate', routeAktualisieren);
window.addEventListener('hashchange', routeAktualisieren);

export function zeichne(){
  if(!R) return;
  ansichten[aktuelle]?.render?.();
}

export function aktuelleAnsicht(){ return aktuelle; }

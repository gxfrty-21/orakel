/* Datenstand: /api/report laden und R als lebende Bindung exportieren. */
export let R = null;

let nachLaden = () => {};
let beiFehler = () => {};

export function registriereNachLaden(fn){ nachLaden = fn; }
export function registriereFehler(fn){ beiFehler = fn; }

export async function lade(){
  try{
    const r = await fetch('/api/report',{cache:'no-store'});
    const neu = await r.json();
    // Daten und Kopfzeile immer aktualisieren. Nur den Ansichts-Render
    // pausieren, wenn der Fokus im sichtbaren Lab-Detail liegt; das entscheidet
    // main.js im Nachlade-Haken, damit dieses Modul nichts über Ansichten weiss.
    R = neu;
    nachLaden(neu);
  }catch(e){
    beiFehler(e);
  }
}

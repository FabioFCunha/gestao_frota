export function activeLeg(trip) { return trip?.legs.find(l=>l.started_at && !l.ended_at) ?? null; }
export function nextLeg(trip) { return trip?.legs.find(l=>!l.ended_at) ?? null; }
export function parseKM(value) {
  if (!/^\d+$/.test(String(value)) || Number(value)>9999999) throw new Error('Informe o KM inteiro do painel, entre 0 e 9999999.');
  return Number(value);
}
export function destinations(text) {
  const items=text.split('\n').map(v=>v.trim()).filter(Boolean);
  if(!items.length||items.length>30||items.some(v=>v.length>300))throw new Error('Informe de 1 a 30 destinos com até 300 caracteres cada.');
  return items;
}
export function canSend(owner, current) { return String(owner)===String(current); }
function coordinates(latitude,longitude){return typeof latitude==='number'&&typeof longitude==='number'&&Number.isFinite(latitude)&&Number.isFinite(longitude)&&Math.abs(latitude)<=90&&Math.abs(longitude)<=180?latitude+','+longitude:null;}
export function googleURL(destination,latitude,longitude) { return 'https://www.google.com/maps/dir/?api=1&travelmode=driving&dir_action=navigate&destination='+encodeURIComponent(coordinates(latitude,longitude)??destination); }
export function wazeURL(destination,latitude,longitude) { const point=coordinates(latitude,longitude);return 'https://waze.com/ul?'+(point?'ll='+encodeURIComponent(point):'q='+encodeURIComponent(destination))+'&navigate=yes'; }

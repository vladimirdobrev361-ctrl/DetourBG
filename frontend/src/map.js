// Картата: маршрут и обходни маршрути, спирки, обекти, опасности по пътя, текущата позиция.
import { CATEGORY, esc, trip, upcomingStops, dur, hhmm, timeAt } from './trip.js';
import { icon, hazardIcon } from './icons.js';

const L = window.L;

export const map = L.map('map', { zoomControl: true }).setView([42.75, 25.3], 7);
const OSM = '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>';
const BASEMAPS = {
  'OpenStreetMap (DE)': L.tileLayer('https://tile.openstreetmap.de/{z}/{x}/{y}.png', { maxZoom: 18, attribution: OSM }),
  'OpenStreetMap': L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19, attribution: OSM, referrerPolicy: 'strict-origin-when-cross-origin',
  }),
  'Esri': L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}', {
    maxZoom: 19, attribution: 'Tiles © Esri',
  }),
};
BASEMAPS['OpenStreetMap (DE)'].addTo(map);
L.control.layers(BASEMAPS, null, { position: 'topright' }).addTo(map);

const layers = {
  alts: L.layerGroup().addTo(map),
  route: L.layerGroup().addTo(map),
  pois: L.layerGroup().addTo(map),
  hazards: L.layerGroup().addTo(map),
  ends: L.layerGroup().addTo(map),
  me: L.layerGroup().addTo(map),
};
let meMarker = null;

const div = (cls, html, size) => L.divIcon({ className: '', html: `<div class="mk ${cls}" style="width:${size}px;height:${size}px">${html}</div>`, iconSize: [size, size], iconAnchor: [size / 2, size / 2] });

export function drawRoute(fit = true) {
  const coords = trip.plan.route.coords;
  layers.route.clearLayers();
  L.polyline(coords, { color: '#ffffff', weight: 9, opacity: 0.95 }).addTo(layers.route);
  L.polyline(coords, { color: '#2f5a47', weight: 5 }).addTo(layers.route);
  if (fit) map.fitBounds(L.latLngBounds(coords), { padding: [30, 30] });
}

export function drawAlternatives(onPick) {
  layers.alts.clearLayers();
  const { alternatives, route_choice: current, recommended_route: rec } = trip.plan;
  for (const a of alternatives) {
    if (a.index === current) continue;
    const line = L.polyline(a.coords, {
      color: a.index === rec ? '#2b5f9e' : '#8a948d', weight: 5, opacity: 0.8, dashArray: '8 8',
    }).addTo(layers.alts);
    line.bindTooltip(`Обход ${a.index}: ${dur(a.duration_min)} (${a.extra_min >= 0 ? '+' : ''}${a.extra_min} мин)`, { sticky: true });
    line.on('click', () => onPick(a.index));
  }
}

export function drawEnds(origin, destination) {
  layers.ends.clearLayers();
  L.marker(origin, { icon: div('end', icon('pin', 14), 26) }).addTo(layers.ends);
  L.marker(destination, { icon: div('end', '🏁', 26) }).addTo(layers.ends);
}

export function drawHazards() {
  layers.hazards.clearLayers();
  for (const h of trip.plan.conditions.hazards) {
    L.marker([h.lat, h.lon], { icon: div(`hz ${h.severity}`, icon(hazardIcon(h.type), 15), 28), zIndexOffset: 800 })
      .bindPopup(`<b>${esc(h.title)}</b><br>${esc(h.detail)}<br><span class="muted">${esc(h.source)}</span>`)
      .addTo(layers.hazards);
  }
}

export function popupHtml(c, planned) {
  const [emoji, label] = CATEGORY[c.category] || CATEGORY.other;
  return `
    ${c.image ? `<img src="${esc(c.image)}" alt="">` : ''}
    <b>${emoji} ${esc(c.name)}</b><br>
    <span class="muted">${esc(label)}${c.length_km ? ` · ${c.length_km} км` : ''}</span><br>
    +${dur(c.extra_min)} (отбивка ${dur(c.detour_min)} + престой ${dur(c.stay_min)}) · около ${hhmm(timeAt(c))}
    ${c.description ? `<br><i>${esc(c.description)}</i>` : ''}
    ${c.wikipedia ? `<br><a href="${esc(c.wikipedia)}" target="_blank">Уикипедия</a>` : ''}
    <br><button type="button" class="${planned ? 'secondary' : 'primary'}" data-toggle="${esc(c.id)}">${planned ? 'Махни от плана' : 'Добави в плана'}</button>`;
}

export function drawPois(onToggle) {
  layers.pois.clearLayers();
  const planned = upcomingStops();
  const visitedIds = new Set(trip.visited.map(v => v.id));
  for (const c of trip.plan.candidates) {
    if (trip.excluded.has(c.id) && !visitedIds.has(c.id)) continue;
    const n = planned.findIndex(p => p.id === c.id);
    let marker;
    if (visitedIds.has(c.id)) {
      marker = L.marker([c.lat, c.lon], { icon: div('visited', '✓', 26) });
    } else if (n >= 0) {
      marker = L.marker([c.lat, c.lon], { icon: div('stop', String(n + 1), 26), zIndexOffset: 500 });
    } else {
      marker = L.circleMarker([c.lat, c.lon], {
        radius: 6, color: '#2f5a47', weight: 2, fillColor: c.fit < 0.5 ? '#d5d9d2' : '#ffffff', fillOpacity: 1,
      });
    }
    marker.bindPopup(() => popupHtml(c, n >= 0), { maxWidth: 260 });
    marker.on('popupopen', e => {
      e.popup.getElement().querySelector('[data-toggle]')?.addEventListener('click', () => {
        map.closePopup();
        onToggle(c.id);
      });
    });
    marker.addTo(layers.pois);
  }
}

export function setMe(latlng) {
  if (!meMarker) {
    meMarker = L.marker(latlng, { icon: div('me', icon('nav', 13), 26), zIndexOffset: 1000 }).addTo(layers.me);
  } else {
    meMarker.setLatLng(latlng);
  }
}

export function clearMe() {
  layers.me.clearLayers();
  meMarker = null;
}

// Leaflet мери контейнера при създаване; след зареждане на стиловете и при преоразмеряване мерим пак.
window.addEventListener('load', () => map.invalidateSize());
new ResizeObserver(() => map.invalidateSize()).observe(document.getElementById('map'));

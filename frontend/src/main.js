// Свързва формата, картата, условията на пътя, живото следене (GPS) и API-то.
import { post } from './api.js';
import { googleMapsUrl, wazeUrl } from './handoff.js';
import { icon, hazardIcon, hydrateIcons } from './icons.js';
import { init as initInterests, selectedInterests } from './interests.js';
import { LiveTrip } from './live.js';
import { map, drawRoute, drawEnds, drawPois, drawHazards, drawAlternatives, setMe, clearMe } from './map.js';
import { ask, isAsking } from './prompts.js';
import {
  CATEGORY, trip, resetTrip, upcomingStops, plannedExtra, eta, etaDirect, budgetLeft, timeAt, now, candidate,
  nearestOnRoute, addMin, hhmm, dur, localIso, esc,
} from './trip.js';

const $ = id => document.getElementById(id);
hydrateIcons();
initInterests();

const PRESETS = {
  'Велико Търново': [43.0757, 25.6172],
  'Габрово': [42.8742, 25.3187],
  'София': [42.6977, 23.3219],
  'Пловдив': [42.1354, 24.7453],
  'Варна': [43.2141, 27.9147],
  'Бургас': [42.5048, 27.4626],
  'Русе': [43.8356, 25.9657],
  'Стара Загора': [42.4258, 25.6345],
  'Плевен': [43.417, 24.6067],
  'Ловеч': [43.137, 24.7142],
  'Благоевград': [42.0209, 23.0943],
  'Банско': [41.8383, 23.4885],
  'Шумен': [43.2706, 26.9361],
  'Смолян': [41.5774, 24.7011],
};
const custom = {};   // 'origin' | 'destination' → {latlng, label}
let picking = null;
let me = null;       // последната GPS позиция

// ---------- формата ----------

function fillSelect(sel, chosen) {
  sel.innerHTML = Object.keys(PRESETS).map(n => `<option ${n === chosen ? 'selected' : ''}>${n}</option>`).join('')
    + '<option value="__gps">📍 Моята позиция</option><option value="__map">🗺 Избери на картата…</option>';
}
fillSelect($('origin'), 'Велико Търново');
fillSelect($('destination'), 'Габрово');

const start = new Date();
start.setMinutes(Math.ceil(start.getMinutes() / 5) * 5, 0, 0);
$('depart').value = localIso(start);

const showBudget = () => { $('budget-val').textContent = dur(+$('budget').value); };
const showCorridor = () => { $('corridor-val').textContent = `${$('corridor').value} км`; };
$('budget').addEventListener('input', showBudget);
$('corridor').addEventListener('input', showCorridor);
showBudget();
showCorridor();

for (const which of ['origin', 'destination']) {
  $(which).addEventListener('change', e => {
    const v = e.target.value;
    if (v === '__map') {
      picking = which;
      $('pick-hint').hidden = false;
    } else if (v === '__gps') {
      navigator.geolocation?.getCurrentPosition(
        p => setCustom(which, [p.coords.latitude, p.coords.longitude], '📍 Моята позиция'),
        () => alert('Няма достъп до местоположението.'),
      );
    }
  });
}

function setCustom(which, latlng, label) {
  custom[which] = { latlng, label };
  const sel = $(which);
  let opt = sel.querySelector('option[value="__custom"]');
  if (!opt) {
    opt = document.createElement('option');
    opt.value = '__custom';
    sel.prepend(opt);
  }
  opt.textContent = label;
  sel.value = '__custom';
}

map.on('click', e => {
  if (!picking) return;
  setCustom(picking, [e.latlng.lat, e.latlng.lng], `Точка ${e.latlng.lat.toFixed(3)}, ${e.latlng.lng.toFixed(3)}`);
  picking = null;
  $('pick-hint').hidden = true;
});

$('swap').addEventListener('click', () => {
  const o = { value: $('origin').value, custom: custom.origin };
  const d = { value: $('destination').value, custom: custom.destination };
  const apply = (which, src) => {
    if (src.value === '__custom' && src.custom) setCustom(which, src.custom.latlng, src.custom.label);
    else $(which).value = src.value;
  };
  apply('origin', d);
  apply('destination', o);
});

function point(which) {
  const v = $(which).value;
  return v === '__custom' ? custom[which]?.latlng : PRESETS[v];
}

function placeName(which) {
  const v = $(which).value;
  return v === '__custom' ? custom[which]?.label : v;
}

function readForm() {
  const origin = point('origin'), destination = point('destination');
  if (!origin || !destination) throw new Error('Изберете начална точка и дестинация.');
  return {
    origin, destination,
    depart_at: $('depart').value,
    budget_min: +$('budget').value,
    corridor_km: +$('corridor').value,
    stay_override_min: $('stay').value ? +$('stay').value : null,
    interests: selectedInterests(),
    meal_min: +$('meal').value,
    names: [placeName('origin'), placeName('destination')],
  };
}

// ---------- планиране ----------

$('plan-form').addEventListener('submit', e => {
  e.preventDefault();
  planTrip(0);
});

async function planTrip(routeChoice) {
  let req;
  try { req = readForm(); } catch (err) { alert(err.message); return; }
  if (live.watchId !== null) stopLive();
  const btn = $('plan-btn');
  btn.disabled = true;
  btn.lastElementChild.textContent = 'Изчислявам…';
  try {
    const plan = await post('/api/plan', { ...req, route_choice: routeChoice });
    resetTrip(req, plan);
    clearMe();
    drawEnds(req.origin, req.destination);
    drawRoute(true);
    render();
    if (window.innerWidth <= 1000) $('summary').scrollIntoView({ behavior: 'smooth' });
  } catch (err) {
    alert('Грешка при изчисляването: ' + err.message);
  } finally {
    btn.disabled = false;
    btn.lastElementChild.textContent = 'Изчисли маршрута';
  }
}

function toggleStop(id) {
  if (trip.stops.has(id)) {
    trip.stops.delete(id);
  } else {
    trip.stops.add(id);
    trip.excluded.delete(id);
    trip.asked.delete(id);
  }
  render();
}

async function switchRoute(k) {
  if (trip.live) await reevaluate('route', k);
  else await planTrip(k);
}

// ---------- рисуване ----------

function render() {
  if (!trip.plan) return;
  renderMapHead();
  renderSummary();
  renderConditions();
  renderStops();
  renderFood();
  drawPois(toggleStop);
  drawHazards();
  drawAlternatives(switchRoute);
  renderAlternatives();
}

function renderMapHead() {
  const r = trip.plan.route;
  $('map-title').textContent = `${trip.req.names[0]} – ${trip.req.names[1]}`;
  $('map-badge').hidden = false;
  $('map-badge').textContent = `${r.source === 'osrm' ? 'OSRM' : 'приблизително'} · ${dur(r.duration_min)} · ${r.distance_km} км`;
}

function renderAlternatives() {
  const { alternatives, route_choice: current, recommended_route: rec } = trip.plan;
  $('alternatives').hidden = alternatives.length < 2;
  $('alternatives').innerHTML = alternatives.map(a => {
    const label = a.index === 0 ? 'Най-бърз' : `Обход ${a.index}`;
    const diff = a.index === 0 ? '' : ` · ${a.extra_min >= 0 ? '+' : ''}${a.extra_min} мин`;
    const risk = a.danger ? `${a.danger} опасни` : a.warnings ? `${a.warnings} предупр.` : 'без опасности';
    return `<button type="button" class="alt ${a.index === current ? 'active' : ''} ${a.index === rec ? 'rec' : ''}" data-alt="${a.index}">
      <b>${label}${a.index === rec ? ' · препоръчан' : ''}</b>${dur(a.duration_min)}${diff} · ${risk}</button>`;
  }).join('');
}
$('alternatives').addEventListener('click', e => {
  const b = e.target.closest('[data-alt]');
  if (b && +b.dataset.alt !== trip.plan.route_choice) switchRoute(+b.dataset.alt);
});

function renderSummary() {
  const stops = upcomingStops();
  const from = trip.live && me ? me : trip.req.origin;
  const heading = trip.heading
    ? `<div class="callout">Отбивка към <b>${esc(trip.heading.name)}</b>
         <div class="btn-row">
           <a class="btn" href="${esc(googleMapsUrl(me || from, [trip.heading.lat, trip.heading.lon], []))}" target="_blank">Google Maps ${icon('external', 16)}</a>
           <a class="btn" href="${esc(wazeUrl([trip.heading.lat, trip.heading.lon], []))}" target="_blank">Waze ${icon('external', 16)}</a>
         </div></div>`
    : '';
  const liveBox = trip.live
    ? `<div class="live"><span class="dot"></span><span>На път · ${esc(nextStopText())}</span></div>
       <button type="button" class="secondary" id="live-btn">${icon('stop', 18)} Спри следенето</button>`
    : `<button type="button" class="primary" id="live-btn">${icon('nav', 18)} Тръгни с GPS</button>`;
  $('summary').hidden = false;
  $('summary').innerHTML = `
    <div class="stats">
      <div class="stat"><span>Директно</span><b>${hhmm(etaDirect())}</b><small>${dur(trip.plan.route.duration_min)}</small></div>
      <div class="stat"><span>Със спирките</span><b>${hhmm(eta())}</b><small>+${dur(plannedExtra())} · ${stops.length} спирки</small></div>
      <div class="stat"><span>Разстояние</span><b>${trip.plan.route.distance_km} км</b><small>бюджет ${dur(Math.max(0, budgetLeft() - plannedExtra()))}</small></div>
    </div>
    ${heading}
    <div class="btn-row">
      <a class="btn" href="${esc(googleMapsUrl(from, trip.req.destination, stops))}" target="_blank">Google Maps ${icon('external', 16)}</a>
      <a class="btn" href="${esc(wazeUrl(trip.req.destination, stops))}" target="_blank">Waze ${icon('external', 16)}</a>
      <div class="wide">${liveBox}</div>
    </div>`;
  const btn = $('live-btn');
  btn.style.width = '100%';
  btn.addEventListener('click', () => (trip.live ? stopLive() : startLive()));
}

function nextStopText() {
  const next = upcomingStops().find(c => c.t_along_min >= trip.legMin);
  if (!next) return `пристигане около ${hhmm(eta())}`;
  return `следваща спирка: ${next.name}, около ${hhmm(timeAt(next))}`;
}

const LEVEL = { ok: 'Чисто', info: 'Информация', warning: 'Внимание', danger: 'Опасно' };

function renderConditions() {
  const c = trip.plan.conditions;
  const rec = trip.plan.recommended_route;
  const alt = rec !== null ? trip.plan.alternatives[rec] : null;
  const ahead = h => Math.max(0, h.at_min - trip.legMin);
  const items = c.hazards.map((h, i) => `
    <li class="hazard ${h.severity}" data-hz="${i}">
      <span class="ic">${icon(hazardIcon(h.type))}</span>
      <div>
        <b>${esc(h.title)}</b>
        <div>${esc(h.detail)}</div>
        <div class="meta">${ahead(h) < 5 ? 'в началото' : `след ~${dur(ahead(h))}`}${h.to_min ? `, участък ~${dur(h.to_min - h.at_min)}` : ''} · ${esc(h.source)}</div>
      </div>
    </li>`).join('');
  const s = c.sources;
  $('conditions-card').hidden = false;
  $('conditions-card').innerHTML = `
    <div class="cond-head">
      <h2 id="conditions">Условия на пътя</h2>
      <span class="level ${c.level}">${icon(c.level === 'ok' ? 'shield' : 'alert', 16)} ${LEVEL[c.level]}</span>
    </div>
    ${alt ? `<div class="callout">По пътя има опасност. Препоръчваме обход ${alt.index}: ${dur(alt.duration_min)}
        (${alt.extra_min >= 0 ? '+' : ''}${alt.extra_min} мин), ${alt.danger ? `${alt.danger} опасни участъка` : 'без опасни участъци'}.
        <button type="button" class="primary" id="use-alt">${icon('route', 18)} Смени маршрута</button></div>` : ''}
    ${items ? `<ul class="hazards">${items}</ul>`
      : `<div class="callout ok">${icon('shield')} Няма ПТП, силни валежи, сняг, риск от свлачища или предупреждения по маршрута.</div>`}
    <ul class="sources">
      <li>ПТП и задръствания: ${esc(s.traffic)}${s.traffic.startsWith('няма') ? ' (добавете TOMTOM_API_KEY в .env)' : ''}</li>
      <li>Валежи, сняг, вятър: ${esc(s.weather)} · Предупреждения: ${esc(s.warnings)}</li>
      <li>Свлачища: ${esc(s.landslides)}</li>
    </ul>
    <button type="button" class="secondary" id="recheck">${icon('refresh', 18)} Провери отново · ${esc(c.checked_at)}</button>`;
  $('use-alt')?.addEventListener('click', () => switchRoute(rec));
  $('recheck').addEventListener('click', () => (trip.live ? reevaluate('manual') : planTrip(trip.routeChoice)));
  for (const li of $('conditions-card').querySelectorAll('[data-hz]')) {
    li.addEventListener('click', () => {
      const h = c.hazards[+li.dataset.hz];
      map.setView([h.lat, h.lon], 11);
    });
  }
}

function poiCard(c, state) {
  const [emoji, label] = CATEGORY[c.category] || CATEGORY.other;
  const img = c.image ? `<img src="${esc(c.image)}" alt="" loading="lazy">` : `<div class="ph">${emoji}</div>`;
  const tags = [
    ...c.reasons.map(r => `<span class="tag ok">${esc(r)}</span>`),
    ...c.warnings.map(w => `<span class="tag warn">${esc(w)}</span>`),
  ].join('');
  const control = state === 'visited' ? `<span class="tag ok">посетено</span>` :
    `<label class="switch" title="В плана"><input type="checkbox" ${state === 'planned' ? 'checked' : ''} data-id="${esc(c.id)}"><span></span></label>`;
  return `
    <div class="poi ${state}">
      ${img}
      <div>
        <h4 data-focus="${esc(c.id)}">${esc(c.name)}</h4>
        <div class="meta">${emoji} ${esc(label)}${c.length_km ? ` · ${c.length_km} км` : ''} · <span class="extra">+${dur(c.extra_min)}</span>
          (${dur(c.detour_min)} отбивка + ${dur(c.stay_min)} престой) · около ${hhmm(timeAt(c))}</div>
        <div class="tags">${tags}</div>
      </div>
      ${control}
    </div>`;
}

function renderStops() {
  const planned = upcomingStops();
  const visited = trip.visited.map(v => v.c);
  const plannedIds = new Set(planned.map(c => c.id));
  const others = trip.plan.candidates.filter(c => !plannedIds.has(c.id) && !trip.excluded.has(c.id)).slice(0, 25);
  $('stops-card').hidden = false;
  $('stops-card').innerHTML = `
    <h2 id="stops">Спирки по пътя (${planned.length})</h2>
    <p class="muted" style="margin:0">В коридора около пътя: ${trip.plan.corridor_count} обекта, оценени ${trip.plan.candidates.length}.</p>
    <div class="list">
      ${planned.length ? planned.map(c => poiCard(c, 'planned')).join('') : '<p class="empty">Няма спирки в бюджета. Увеличете времето за спирки или коридора.</p>'}
      ${visited.map(c => poiCard(c, 'visited')).join('')}
    </div>
    ${others.length ? `<details class="more"><summary>Още обекти по пътя (${others.length})</summary>
      <div class="list">${others.map(c => poiCard(c, 'other')).join('')}</div></details>` : ''}`;
}

// ---------- храна и нощувка ----------

function amenityRow(o, kind, sectionMode) {
  const added = trip.stops.has(o.id) && !trip.excluded.has(o.id);
  const stars = o.stars ? `<span class="stars">${'★'.repeat(o.stars)}</span> ` : '';
  const tags = [...o.reasons.map(r => `<span class="tag ok">${esc(r)}</span>`), ...o.warnings.map(w => `<span class="tag warn">${esc(w)}</span>`)].join('');
  const time = kind === 'food'
    ? (sectionMode === 'route' ? `+${dur(o.extra_min)} (${dur(o.detour_min)} отбивка + ${dur(o.stay_min)}) · около ${o.arrive}` : `около ${o.arrive}`)
    : (sectionMode === 'route' ? `+${dur(o.detour_min)} от пътя · пристигане около ${o.arrive}` : `${o.dist_km} км от целта`);
  const action = kind === 'food' && sectionMode === 'route'
    ? `<button type="button" class="${added ? 'secondary' : 'primary'}" data-amen="${esc(o.id)}">${added ? 'Махни' : 'Добави'}</button>`
    : kind === 'lodging' && sectionMode === 'route'
      ? `<button type="button" class="primary" data-sleep="${esc(o.id)}">Нощувай тук</button>`
      : '';
  const links = [
    `<a href="${esc(googleMapsUrl(trip.live && me ? me : trip.req.origin, [o.lat, o.lon], []))}" target="_blank">Карта ↗</a>`,
    o.website ? `<a href="${esc(o.website)}" target="_blank" rel="noopener">Сайт ↗</a>` : '',
    o.phone ? `<a href="tel:${esc(o.phone.replace(/\s/g, ''))}">${esc(o.phone)}</a>` : '',
  ].join('');
  return `
    <div class="amen ${added ? 'added' : ''}">
      <div class="ph">${kind === 'food' ? '🍽' : '🛏'}</div>
      <div>
        <b>${esc(o.name)}</b>
        <div class="meta">${stars}${esc(o.kind_bg || '')}${o.beds ? ` · ${esc(o.beds)} легла` : ''} · ${time}</div>
        <div class="tags">${tags}</div>
        <div class="links">${links}</div>
      </div>
      ${action}
    </div>`;
}

function renderFood() {
  const { food, lodging } = trip.plan;
  const sections = food.map(m => `
    <div class="amen-section">
      <h3>${esc(m.title)} <small>${esc(m.where || '')}</small></h3>
      ${m.options.length ? m.options.map(o => amenityRow(o, 'food', m.mode)).join('') : '<p class="empty">Няма заведения край пътя в този час.</p>'}
    </div>`);
  if (lodging) {
    sections.push(`
      <div class="amen-section">
        <h3>${esc(lodging.title)} <small>${esc(lodging.where || '')}</small></h3>
        ${lodging.reason ? `<div class="callout">Препоръчваме нощувка по пътя: ${esc(lodging.reason)}.</div>` : ''}
        ${lodging.options.length ? lodging.options.map(o => amenityRow(o, 'lodging', lodging.mode)).join('') : '<p class="empty">Няма места за настаняване наблизо.</p>'}
      </div>`);
  }
  $('food-card').hidden = false;
  $('food-card').innerHTML = `
    <h2 id="food">Храна и нощувка</h2>
    ${sections.length ? sections.join('') : '<p class="empty">Пътуването не минава през обяд или вечеря.</p>'}
    <p class="muted small" style="margin:0">Заведения и хотели от OpenStreetMap и регистрите на Министерството на туризма (категория, звезди, легла).</p>`;
}

function findAmenity(id) {
  const all = [...trip.plan.food.flatMap(m => m.options), ...(trip.plan.lodging?.options || [])];
  return all.find(o => o.id === id);
}

$('food-card').addEventListener('click', e => {
  const add = e.target.closest('[data-amen]');
  if (add) {
    const o = findAmenity(add.dataset.amen);
    if (!o) return;
    if (trip.stops.has(o.id)) {
      trip.stops.delete(o.id);
      trip.extra.delete(o.id);
    } else {
      if (!candidate(o.id)) trip.plan.candidates.push(o);
      trip.extra.set(o.id, o);
      trip.stops.add(o.id);
      trip.excluded.delete(o.id);
      trip.asked.delete(o.id);
    }
    render();
    return;
  }
  const sleep = e.target.closest('[data-sleep]');
  if (sleep) {
    const o = findAmenity(sleep.dataset.sleep);
    if (!o) return;
    setCustom('destination', [o.lat, o.lon], `🛏 ${o.name}`);
    planTrip(trip.routeChoice);
  }
});

$('stops-card').addEventListener('change', e => {
  const box = e.target.closest('input[data-id]');
  if (box) toggleStop(box.dataset.id);
});
$('stops-card').addEventListener('click', e => {
  const h = e.target.closest('[data-focus]');
  const c = h && candidate(h.dataset.focus);
  if (c) map.setView([c.lat, c.lon], 13);
});

// ---------- живо следене (GPS) ----------

const live = new LiveTrip({
  onMove: pos => { me = pos; setMe(pos); renderSummary(); },
  onPrompt: promptStop,
  onArriveStop: c => { render(); },
  onReplan: reason => reevaluate(reason),
  onArrive: () => { render(); ask({ title: 'Пристигнахте!', html: visitedText(), yes: 'Готово', no: 'Затвори' }); },
  onError: err => { alert('GPS: ' + err.message); stopLive(); },
});

function startLive() {
  try {
    live.start();
  } catch (err) {
    alert(err.message);
    return;
  }
  render();
}

function stopLive() {
  live.stop();
  render();
}

function visitedText() {
  if (!trip.visited.length) return 'Без спирки по пътя.';
  return `Спирки: ${trip.visited.map(v => esc(v.name)).join(', ')} (+${dur(trip.visited.reduce((s, v) => s + v.extra, 0))}).`;
}

async function promptStop(c, planned) {
  const back = addMin(timeAt(c), c.extra_min);
  const newEta = addMin(eta(), planned ? 0 : c.extra_min);
  const tags = [...c.reasons.map(r => `<span class="tag ok">${esc(r)}</span>`), ...c.warnings.map(r => `<span class="tag warn">${esc(r)}</span>`)].join('');
  const yes = await ask({
    title: planned ? `Наближава: ${c.name}` : `По пътя: ${c.name}`,
    image: c.image,
    html: `${planned ? 'В плана ви е.' : 'Не е в плана, но се събира във времето.'} Да спрем ли?<br>
      <b>+${dur(c.extra_min)}</b> (отбивка ${dur(c.detour_min)} + престой ${dur(c.stay_min)}) ·
      обратно на пътя около ${hhmm(back)} · пристигане <b>${hhmm(newEta)}</b><div class="tags">${tags}</div>`,
    yes: 'Да, спираме',
    no: planned ? 'Пропусни' : 'Не, продължаваме',
  });
  setTimeout(render, 0);
  return yes;
}

// ---------- преизчисляване по пътя ----------

let reevalBusy = false;

async function reevaluate(reason, routeChoice = trip.routeChoice) {
  if (reevalBusy || isAsking()) return;
  reevalBusy = true;
  const body = {
    ...trip.req,
    origin: me || trip.req.origin,
    depart_at: localIso(now()),
    budget_min: Math.max(0, budgetLeft()),
    exclude: [...trip.excluded],
    stops: upcomingStops().map(c => c.id),
    route_choice: routeChoice,
  };
  try {
    const res = await post('/api/reevaluate', body);
    const oldStops = new Set(trip.stops);
    trip.plan = res;
    trip.routeChoice = res.route_choice;
    trip.legStart = new Date(res.depart);
    trip.legMin = 0;
    trip.stops = new Set([...oldStops].filter(id => res.candidates.some(c => c.id === id)));
    for (const [id, o] of trip.extra) {
      if (trip.excluded.has(id)) continue;
      const { idx } = nearestOnRoute([o.lat, o.lon]);
      res.candidates.push({ ...o, t_along_min: res.route.cum_min[idx] });
      if (oldStops.has(id)) trip.stops.add(id);
    }
    drawRoute(false);
    render();
    const changes = reason === 'route' ? [] : res.changes;
    if (changes.length) {
      const items = changes.map(ch => ch.action === 'reroute'
        ? `<li>↪ <b>обходен маршрут</b> (${ch.extra_min >= 0 ? '+' : ''}${ch.extra_min} мин) — ${esc(ch.why)}</li>`
        : ch.action === 'drop'
          ? `<li>✗ махаме <b>${esc(ch.name)}</b> — ${esc(ch.why)}</li>`
          : `<li>✓ добавяме <b>${esc(ch.name)}</b> (+${dur(ch.extra_min)}) — ${esc(ch.why)}</li>`).join('');
      const yes = await ask({ title: 'Промени по пътя', html: `Условията се промениха. Предлагаме:<ul>${items}</ul>`, yes: 'Приеми', no: 'Остави както е' });
      if (yes) {
        trip.stops = new Set(res.stops);
        for (const ch of changes) if (ch.action === 'add') trip.asked.delete(ch.id);
        const reroute = changes.find(ch => ch.action === 'reroute');
        reevalBusy = false;
        if (reroute) await reevaluate('route', reroute.route);
      }
      render();
    }
  } catch (err) {
    console.warn('Преизчисляването не успя:', err);
  } finally {
    reevalBusy = false;
  }
}

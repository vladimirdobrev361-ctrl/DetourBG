// Състоянието на пътуването и сметките за време.

export const CATEGORY = {
  history: ['🏛', 'История'],
  nature: ['🌲', 'Природа'],
  museum: ['🖼', 'Музей'],
  religion: ['⛪', 'Храм'],
  fitness: ['🏋', 'Фитнес'],
  hiking: ['🥾', 'Хайкинг'],
  cycling: ['🚴', 'Колоездене'],
  sport_other: ['🏅', 'Спорт'],
  food: ['🍽', 'Храна'],
  lodging: ['🛏', 'Нощувка'],
  other: ['📍', 'Друго'],
};

export const trip = {
  req: null,            // параметрите от формата
  plan: null,           // отговорът на /api/plan за текущия участък
  stops: new Set(),     // спирки в плана (id)
  asked: new Set(),     // за кои обекти вече питахме по пътя
  excluded: new Set(),  // отказани или посетени
  visited: [],          // [{id, name, extra, c}]
  heading: null,        // приета спирка, към която сме се отбили
  routeChoice: 0,       // 0 = най-бързият маршрут
  legStart: null,       // кога започва текущият участък (за времената)
  legMin: 0,            // докъде сме стигнали по текущия маршрут (мин. път)
  live: false,          // следим ли GPS
  extra: new Map(),     // добавени от „Храна и нощувка“ (id → обект), пазим ги при преизчисляване
};

export function resetTrip(req, plan) {
  Object.assign(trip, {
    req, plan, stops: new Set(plan.stops), asked: new Set(), excluded: new Set(), visited: [],
    heading: null, routeChoice: plan.route_choice, legStart: new Date(plan.depart), legMin: 0, extra: new Map(),
  });
}

export const addMin = (d, m) => new Date(d.getTime() + m * 60000);
export const hhmm = d => d.toLocaleTimeString('bg-BG', { hour: '2-digit', minute: '2-digit' });

export function dur(min) {
  min = Math.max(0, Math.round(min));
  const h = Math.floor(min / 60), m = min % 60;
  return h ? `${h} ч${m ? ` ${m} мин` : ''}` : `${m} мин`;
}

export function localIso(d) {
  const p = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}

export const esc = s => String(s ?? '').replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));

export const candidate = id => trip.plan.candidates.find(c => c.id === id);
export const routeTotal = () => trip.plan.route.cum_min.at(-1);
export const usedMin = () => trip.visited.reduce((s, v) => s + v.extra, 0);
export const budgetLeft = () => trip.req.budget_min - usedMin();

// „Сега“ по маршрута: при живо следене — истинският час, иначе часът на тръгване.
export const now = () => (trip.live ? new Date() : addMin(trip.legStart, trip.legMin));

export function upcomingStops() {
  return trip.plan.candidates
    .filter(c => trip.stops.has(c.id) && !trip.excluded.has(c.id))
    .sort((a, b) => a.t_along_min - b.t_along_min);
}

export const plannedExtra = () => upcomingStops().reduce((s, c) => s + c.extra_min, 0);

function trafficLeft() {
  const total = routeTotal();
  return total ? trip.plan.traffic.delay_min * (1 - trip.legMin / total) : 0;
}

export const etaDirect = () => addMin(now(), routeTotal() - trip.legMin + trafficLeft());
export const eta = () => addMin(etaDirect(), plannedExtra());

// Кога ще сме при отбивката към обекта (с приетите спирки преди нея).
export function timeAt(c) {
  const before = upcomingStops().filter(s => s.t_along_min < c.t_along_min).reduce((s, x) => s + x.extra_min, 0);
  return addMin(now(), Math.max(0, c.t_along_min - trip.legMin) + before);
}

// Най-близката точка от маршрута до позицията: {idx, km}
export function nearestOnRoute([lat, lon]) {
  const { coords } = trip.plan.route;
  const kx = 111.32 * Math.cos(lat * Math.PI / 180), ky = 110.57;
  let best = 0, bestD = Infinity;
  for (let i = 0; i < coords.length; i++) {
    const d = ((coords[i][0] - lat) * ky) ** 2 + ((coords[i][1] - lon) * kx) ** 2;
    if (d < bestD) { bestD = d; best = i; }
  }
  return { idx: best, km: Math.sqrt(bestD) };
}

export function distKm([lat1, lon1], [lat2, lon2]) {
  const kx = 111.32 * Math.cos(lat1 * Math.PI / 180), ky = 110.57;
  return Math.hypot((lat2 - lat1) * ky, (lon2 - lon1) * kx);
}

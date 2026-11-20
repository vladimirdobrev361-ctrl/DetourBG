// Живо следене с GPS: къде сме по маршрута, въпрос „Да спрем ли?“ малко преди отбивка,
// пристигане при спирка, отклонение от маршрута и периодична проверка на условията.
import { trip, routeTotal, nearestOnRoute, distKm, budgetLeft, plannedExtra } from './trip.js';

const LEAD_MIN = 3;          // питаме ~3 мин преди отбивката (≈ 2–5 км)
const RECHECK_MIN = 5;       // проверка на трафик, време и предупреждения
const OFF_ROUTE_KM = 1;      // по-далеч от маршрута → преизчисляваме оттук
const ARRIVE_KM = 0.3;       // толкова близо до спирката = пристигнахме
const OFFER_TOP = 12;        // предлагаме само от най-добрите непланирани

export class LiveTrip {
  constructor(hooks) {
    this.hooks = hooks;      // onMove, onPrompt(c, planned), onArriveStop(c), onReplan(reason), onArrive, onError
    this.watchId = null;
    this.lastCheck = 0;
    this.busy = false;
  }

  start() {
    if (!navigator.geolocation) throw new Error('Браузърът няма достъп до местоположение.');
    trip.live = true;
    this.lastCheck = Date.now();
    this.watchId = navigator.geolocation.watchPosition(
      p => this.update([p.coords.latitude, p.coords.longitude]),
      e => this.hooks.onError(e),
      { enableHighAccuracy: true, maximumAge: 5000, timeout: 30000 },
    );
  }

  stop() {
    if (this.watchId !== null) navigator.geolocation.clearWatch(this.watchId);
    this.watchId = null;
    trip.live = false;
  }

  async update(pos) {
    if (!trip.plan || !trip.live || this.busy) return;
    this.hooks.onMove(pos);

    // към приета спирка ли сме се отбили?
    if (trip.heading) {
      if (distKm(pos, [trip.heading.lat, trip.heading.lon]) <= ARRIVE_KM) {
        const c = trip.heading;
        trip.heading = null;
        trip.excluded.add(c.id);
        trip.visited.push({ id: c.id, name: c.name, extra: c.extra_min, c });
        this.hooks.onArriveStop(c);
      }
      return;  // докато сме в отбивка, не следим маршрута
    }

    const { idx, km } = nearestOnRoute(pos);
    trip.legMin = trip.plan.route.cum_min[idx];
    const dest = trip.plan.route.coords.at(-1);
    if (distKm(pos, dest) <= ARRIVE_KM * 2) {
      this.stop();
      this.hooks.onArrive();
      return;
    }
    if (km > OFF_ROUTE_KM) return this.replan('off_route');
    if (Date.now() - this.lastCheck > RECHECK_MIN * 60000) return this.replan('periodic');
    await this.checkPrompts();
  }

  async replan(reason) {
    this.lastCheck = Date.now();
    this.busy = true;
    try { await this.hooks.onReplan(reason); } finally { this.busy = false; }
  }

  async checkPrompts() {
    const planned = new Set(trip.stops);
    const ranked = trip.plan.candidates.filter(c => !planned.has(c.id)).slice(0, OFFER_TOP).map(c => c.id);
    for (const c of trip.plan.candidates) {
      if (trip.asked.has(c.id) || trip.excluded.has(c.id)) continue;
      if (trip.legMin < c.t_along_min - LEAD_MIN) continue;
      trip.asked.add(c.id);
      if (trip.legMin > c.t_along_min + 1) continue;  // вече сме подминали
      const isPlanned = planned.has(c.id);
      if (!isPlanned) {
        const fits = c.extra_min <= budgetLeft() - plannedExtra();
        if (!fits || c.fit < 0.5 || !ranked.includes(c.id)) continue;
      }
      this.busy = true;
      try {
        const yes = await this.hooks.onPrompt(c, isPlanned);
        if (yes) {
          trip.stops.add(c.id);
          trip.heading = c;
        } else {
          trip.excluded.add(c.id);
          trip.stops.delete(c.id);
        }
      } finally {
        this.busy = false;
      }
      return;
    }
  }
}

export const progress = () => (trip.plan ? trip.legMin / routeTotal() : 0);

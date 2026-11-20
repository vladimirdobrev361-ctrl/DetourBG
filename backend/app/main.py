"""FastAPI приложение. Стартиране (от корена на проекта):

    .venv/bin/uvicorn app.main:app --app-dir backend --reload

После: http://localhost:8000 (приложението) и http://localhost:8000/docs (API).
"""
from collections import Counter
from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import config
from app.corridor import PoiStore
from app.meals import Amenities
from app.planner import PlanRequest, plan

app = FastAPI(title="DetourBG", description="Спирки по пътя и условия на пътя с данни от data.egov.bg, OSM, Wikidata, Open-Meteo и Meteoalarm")

if not config.POIS_PATH.exists():
    raise SystemExit(f"Липсва {config.POIS_PATH}. Пуснете pipeline-а (виж README).")
store = PoiStore()
amenities = Amenities()


class PlanIn(BaseModel):
    origin: tuple[float, float] = Field(description="[lat, lon]", examples=[[43.0757, 25.6172]])
    destination: tuple[float, float] = Field(examples=[[42.8742, 25.3187]])
    depart_at: datetime | None = Field(None, description="местно време, напр. 2026-11-20T11:00")
    budget_min: float = Field(120, ge=0, description="колко минути сте готови да добавите за спирки")
    interests: list[str] = Field(default_factory=list, examples=[["history", "nature", "hiking"]],
                                 description="подредени по важност — първият е най-важен")
    corridor_km: float = Field(8, gt=0, le=30)
    stay_override_min: int | None = None
    exclude: list[str] = Field(default_factory=list, description="id на отказани или посетени обекти")
    route_choice: int = Field(0, ge=0, le=2, description="0 = най-бързият маршрут, 1–2 = обходни")
    meal_min: int = Field(45, ge=15, le=120, description="време за обяд/вечеря")


class ReevaluateIn(PlanIn):
    stops: list[str] = Field(default_factory=list, description="предстоящите приети спирки")


def to_request(body: PlanIn, sticky=(), from_start=True) -> PlanRequest:
    depart = (body.depart_at or datetime.now()).replace(tzinfo=None, second=0, microsecond=0)
    return PlanRequest(
        origin=body.origin, destination=body.destination, depart=depart, budget_min=body.budget_min,
        interests=body.interests, corridor_km=body.corridor_km, stay_override_min=body.stay_override_min,
        exclude=tuple(body.exclude), sticky=tuple(sticky), from_start=from_start, route_choice=body.route_choice,
        meal_min=body.meal_min,
    )


@app.post("/api/plan")
def api_plan(body: PlanIn):
    """Маршрут, условия по пътя (ПТП, валежи, сняг, свлачища, предупреждения), обходни маршрути
    и препоръчани спирки в бюджета."""
    return plan(store, to_request(body), amenities)


@app.post("/api/reevaluate")
def api_reevaluate(body: ReevaluateIn):
    """Преизчислява от текущата позиция (`origin`): нови условия, обход при опасност,
    кои спирки да отпаднат или да се добавят."""
    new = plan(store, to_request(body, sticky=body.stops, from_start=False), amenities)
    by_id = {c["id"]: c for c in new["candidates"]}
    changes = []
    if new["recommended_route"] is not None:
        alt = new["alternatives"][new["recommended_route"]]
        danger = [h["title"] for h in new["conditions"]["hazards"] if h["severity"] == "danger"]
        changes.append({"action": "reroute", "route": alt["index"], "name": "обходен маршрут",
                        "why": ", ".join(danger[:3]) or "опасност по пътя", "extra_min": alt["extra_min"]})
    for s in [s for s in body.stops if s not in new["stops"]]:
        c = by_id.get(s)
        if c and c["fit"] < 0.5:
            why = ", ".join(c["warnings"])
        elif new["traffic"]["delay_min"] > 0:
            why = f"не се събира заради трафика (+{new['traffic']['delay_min']} мин)"
        else:
            why = "не се събира в оставащото време"
        changes.append({"action": "drop", "id": s, "name": c["name"] if c else s, "why": why})
    for s in [s for s in new["stops"] if s not in body.stops]:
        c = by_id[s]
        changes.append({"action": "add", "id": s, "name": c["name"], "why": ", ".join(c["reasons"][:3]),
                        "extra_min": c["extra_min"]})
    return {**new, "changes": changes}


@app.get("/api/stats")
def api_stats():
    """Числа за слайдовете: колко обекта, от кои източници, с какви координати."""
    props = [f["properties"] for f in store.features]
    return {
        "total": len(props),
        "by_category": Counter(p["category"] for p in props),
        "by_coord_quality": Counter(p["coord_quality"] for p in props),
        "by_sources": Counter("+".join(p["sources"]) for p in props),
        "with_image": sum(1 for p in props if p.get("image")),
        "unesco": sum(1 for p in props if p.get("unesco")),
    }


@app.get("/api/poi/{poi_id:path}")
def api_poi(poi_id: str):
    f = store.by_id.get(poi_id)
    if not f:
        raise HTTPException(404, "Няма такъв обект")
    return f


app.mount("/", StaticFiles(directory=config.FRONTEND_DIR, html=True), name="frontend")

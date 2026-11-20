"""Оценка на всяка отбивка:

    оценка = интерес × популярност × годност(време, сезон, час, работно време) / (отбивка + престой в часове + 0.3)

Всеки множител оставя кратко обяснение в `reasons` / `warnings`, което приложението показва.
"""
import re
from datetime import datetime, timedelta

from app.corridor import Candidate
from app.weather import is_rainy

WINTER_MONTHS = {11, 12, 1, 2, 3}
DAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
CATEGORY_BG = {"museum": "музей", "religion": "храм/манастир", "history": "история", "nature": "природа", "other": "друго",
               "fitness": "фитнес", "hiking": "хайкинг", "cycling": "колоездене", "sport_other": "спорт"}


def _days(spec: str) -> set[int] | None:
    out = set()
    for part in spec.split(","):
        if "-" in part:
            a, b = part.split("-")
            if a not in DAYS or b not in DAYS:
                return None
            i, j = DAYS.index(a), DAYS.index(b)
            out |= set(range(i, j + 1)) if i <= j else set(range(i, 7)) | set(range(0, j + 1))
        elif part in DAYS:
            out.add(DAYS.index(part))
        else:
            return None
    return out


def is_open(hours: str | None, when: datetime) -> bool | None:
    """Опростен парсер на OSM opening_hours. None = не знаем."""
    if not hours:
        return None
    hours = hours.strip()
    if hours == "24/7":
        return True
    state: dict[int, list[tuple[int, int]] | None] = {}
    for rule in [r.strip() for r in hours.split(";") if r.strip()]:
        m = re.fullmatch(r"(?:([A-Za-z,\-]+)\s+)?(off|closed|(?:\d{1,2}:\d{2}-\d{1,2}:\d{2},?\s*)+)", rule)
        if not m:
            return None
        days = _days(m.group(1)) if m.group(1) else set(range(7))
        if days is None:
            return None
        if m.group(2) in ("off", "closed"):
            ranges = []
        else:
            ranges = []
            for a, b in re.findall(r"(\d{1,2}:\d{2})-(\d{1,2}:\d{2})", m.group(2)):
                ha, ma = map(int, a.split(":"))
                hb, mb = map(int, b.split(":"))
                ranges.append((ha * 60 + ma, hb * 60 + mb))
        for d in days:
            state[d] = ranges
    today = state.get(when.weekday(), [])
    minute = when.hour * 60 + when.minute
    return any(a <= minute < b for a, b in today or [])


def interest_weight(category: str, interests: list[str]) -> float:
    """Интересите са подредени по важност: първият тежи 1.0, всеки следващ с 0.15 по-малко (до 0.55).
    Категория извън интересите — 0.3."""
    if not interests:
        return 1.0
    if category not in interests:
        return 0.3
    return max(0.55, 1.0 - 0.15 * interests.index(category))


def score(c: Candidate, interests: list[str], depart: datetime, sticky: bool = False) -> None:
    p = c.poi
    reasons, warnings = [], []
    fit = 1.0
    w = c.weather
    rainy = is_rainy(w)
    arrive = depart + timedelta(seconds=c.t_along_s + c.detour_s / 2)

    interest = interest_weight(p["category"], interests)
    if interests and p["category"] in interests:
        rank = interests.index(p["category"]) + 1
        label = CATEGORY_BG.get(p["category"], p["category"])
        reasons.append(f"{label} (приоритет {rank})" if len(interests) > 1 else label)

    if p["outdoor"]:
        if rainy:
            fit *= 0.25
            warnings.append(f"на открито, дъжд {w['precipitation_probability']}% около {arrive:%H:%M}")
        if w and w.get("wind", 0) >= 50:
            fit *= 0.5
            warnings.append(f"силен вятър {round(w['wind'])} км/ч")
        if w and not w.get("is_day", True):
            fit *= 0.2
            warnings.append("ще е тъмно")
        if w and not rainy and w.get("precipitation_probability", 0) < 30:
            reasons.append(f"сухо, {round(w['temp'])}°C около {arrive:%H:%M}")
    elif rainy:
        fit *= 1.2
        interest = max(interest, 0.8)  # при дъжд музеят е добра замяна, дори да не е в интересите
        reasons.append("на закрито — подходящо при дъжд")

    if p.get("road") == "unpaved":
        if rainy:
            fit = 0.0
            warnings.append("черен път при дъжд")
        else:
            warnings.append("черен път")
    elif p.get("road") == "paved":
        reasons.append("асфалтов път")

    if p.get("seasonal") and arrive.month in WINTER_MONTHS:
        fit *= 0.3
        warnings.append("сезонен обект")

    open_now = is_open(p.get("opening_hours"), arrive)
    if open_now is False:
        fit = 0.0
        warnings.append(f"затворено в {arrive:%H:%M}")
    elif open_now:
        reasons.append(f"отворено в {arrive:%H:%M}")

    if p.get("free"):
        reasons.append("безплатно")
    if p.get("unesco"):
        reasons.append("ЮНЕСКО")
    elif p.get("national"):
        reasons.append("национално значение")
    if p.get("coord_quality") == "settlement":
        fit *= 0.8
        warnings.append("приблизително местоположение")

    value = interest * p.get("popularity", 1.0) * fit * (1.3 if sticky else 1.0)
    c.fit = round(fit, 2)
    c.reasons, c.warnings = reasons, warnings
    c.score = round(value / (c.extra_min / 60 + 0.3), 3)

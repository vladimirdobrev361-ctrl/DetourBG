"""Извлича GPS координати от свободния текст в регистъра на забележителностите.

В регистъра координатите са в колоната „Местоположение“, написани по различен начин:
    "GPS Координати: 41.49790,23.48228"
    "42.4833° с. ш. 23.1833° и. д."
    "GPS 43°54'17.0\"N 27°18'16.0\"E"
    "42о50'20\" ..."          (кирилско „о“ вместо °)
    "GPS координати 41 53 10.0 25 15 31.0"

Проверка: python -m pipeline.parse_coords
"""
import re

from pipeline.common import in_bulgaria

_NUM = r"\d{1,2}(?:[.,]\d+)?"
_DEG = r"[°ºо˚?]"  # „?“ остава след счупено кодиране на °, ′ и ″
_SEP = r"[\s,;/–-]*(?:N|С|с\.?\s*ш\.?|сев\.?\s*ш\.?)?[\s,;/–-]*"

# 41.49790, 23.48228  /  41,49790 23,48228  /  42.4833° с. ш. 23.1833° и. д.  /  41°.52118 23°.39943
_LAT_DEC = r"(4[1-4]°?[.,]\d{3,})"
_LON_DEC = r"(0?2[2-8]°?[.,]\d{3,})"
DECIMAL = re.compile(rf"{_LAT_DEC}\s*{_DEG}?\s*(?:N|с\.?\s*ш\.?)?[\s,;/]*\D{{0,25}}?{_LON_DEC}")
# Някои записи са с разменени места: 23.989055, 42.694178
DECIMAL_SWAPPED = re.compile(rf"{_LON_DEC}\s*{_DEG}?[\s,;/]+{_LAT_DEC}")

# 43°54'17.0"N 27°18'16.0"E  /  41 53 10.0 25 15 31.0  /  42°50.333' 25°15.5'
DMS = re.compile(
    rf"(4[1-4])\s*(?:{_DEG}|\s)\s*({_NUM})\s*(?:['’′`?]|\s)\s*(?:({_NUM})\s*(?:\"|”|″|''|’’|\?)?)?"
    rf"{_SEP}\D{{0,25}}?"
    rf"0?(2[2-8])\s*(?:{_DEG}|\s)\s*({_NUM})\s*(?:['’′`?]|\s)?\s*(?:({_NUM}))?"
)


def _f(s: str | None) -> float:
    return float(s.replace(",", ".").replace("°", "")) if s else 0.0


def parse_coords(text: str) -> tuple[float, float] | None:
    """Връща (lat, lon) или None, ако в текста няма валидни координати в България."""
    if not text:
        return None
    text = text.replace("\xa0", " ")
    for pattern, swapped in ((DECIMAL, False), (DECIMAL_SWAPPED, True)):
        m = pattern.search(text)
        if m:
            lat, lon = _f(m.group(1)), _f(m.group(2))
            if swapped:
                lat, lon = lon, lat
            if in_bulgaria(lat, lon):
                return round(lat, 6), round(lon, 6)
    m = DMS.search(text)
    if m:
        d1, m1, s1, d2, m2, s2 = m.groups()
        lat = _f(d1) + _f(m1) / 60 + _f(s1) / 3600
        lon = _f(d2) + _f(m2) / 60 + _f(s2) / 3600
        if in_bulgaria(lat, lon):
            return round(lat, 6), round(lon, 6)
    return None


EXAMPLES = {
    "GPS Координати: 41.49790,23.48228": (41.4979, 23.48228),
    "с. Капатово, Координати: 41.46310,23.35720": (41.4631, 23.3572),
    "GPS координати:42.915645, 27.822744": (42.915645, 27.822744),
    "с. Боснек (в края на ул.Игличе) , 42.4833° с. ш. 23.1833° и. д.": (42.4833, 23.1833),
    "гр. Алфатар, на 3 км. Югозападно, GPS 43°54'17.0\"N 27°18'16.0\"E": (43.904722, 27.304444),
    "гр. Ямбол, 42°28'57\"N \xa0 26°30'21\"E": (42.4825, 26.505833),
    "Землището на с.Сърница, 3,5 км, СЗ от селото, GPS координати 41 53 10.0 25 15 31.0": (41.886111, 25.258611),
    "GPS координати: геогр. ширина 42о50'20\" геогр. дължина 25о10'05\"": (42.838889, 25.168056),
    "гр. Правец, GPS координати: N 42?53?38.4? Е 023?54?57.2?": (42.894, 23.915889),
    "Координати: 41°.52118 23°.39943": (41.52118, 23.39943),
    "с. Мирково, площад Хармана GPS: 23.989055, 42.694178": (42.694178, 23.989055),
    "гр. Аврен": None,
    "Писмо № 633 от 12.03.1985 г.": None,
}

if __name__ == "__main__":
    ok = True
    for text, expected in EXAMPLES.items():
        got = parse_coords(text)
        good = got == expected or (got and expected and abs(got[0] - expected[0]) < 1e-4 and abs(got[1] - expected[1]) < 1e-4)
        ok &= bool(good)
        print(("✓" if good else "✗"), repr(text[:60]), "→", got, "" if good else f"(очаквано {expected})")
    raise SystemExit(0 if ok else 1)

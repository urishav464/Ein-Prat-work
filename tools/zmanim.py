# -*- coding: utf-8 -*-
"""חישוב זמני כניסת/צאת שבת לירושלים והפקת data/zmanim.csv.

הזמנים כאן הם *קירוב נוח* (דיוק של דקה-שתיים) שנועד למלא מראש את גיליון
"זמנים" בחוברת. הזמן הקובע הוא תמיד הלוח שאורי עובד לפיו — כל שורה בגיליון
ניתנת לדריסה ידנית.

הרצה:  python3 tools/zmanim.py            # שנה קדימה מהיום
       python3 tools/zmanim.py 2026-09-04 2027-08-27
"""
import csv
import math
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

# --- פרמטרים שניתן לכוונן ---------------------------------------------------
LAT, LON = 31.7683, 35.2137          # ירושלים
CANDLE_MINUTES_BEFORE_SUNSET = 40    # מנהג ירושלים
HAVDALAH_MINUTES_AFTER_SUNSET = 40   # צאת שבת
SUNSET_ZENITH = 90.833               # שקיעה (כולל רפרקציה וקוטר השמש)
# ---------------------------------------------------------------------------

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _israel_utc_offset(d: date) -> int:
    """שעון קיץ בישראל: מיום שישי שלפני יום ראשון האחרון במרץ ועד יום ראשון האחרון באוקטובר."""
    def last_sunday(year, month):
        day = 31 if month in (3, 10) else 30
        d0 = date(year, month, day)
        return d0 - timedelta(days=(d0.weekday() + 1) % 7)

    dst_start = last_sunday(d.year, 3) - timedelta(days=2)   # שישי שלפני
    dst_end = last_sunday(d.year, 10)
    return 3 if dst_start <= d < dst_end else 2


def _solar_event(d: date, zenith: float, sunset: bool = True):
    """אלגוריתם השקיעה/זריחה הסטנדרטי (Almanac / NOAA). מחזיר שעה מקומית עשרונית."""
    n = d.timetuple().tm_yday
    lng_hour = LON / 15.0
    t = n + (((18 if sunset else 6) - lng_hour) / 24.0)

    m = (0.9856 * t) - 3.289
    l = m + (1.916 * math.sin(math.radians(m))) + (0.020 * math.sin(math.radians(2 * m))) + 282.634
    l %= 360

    ra = math.degrees(math.atan(0.91764 * math.tan(math.radians(l)))) % 360
    ra += (math.floor(l / 90) * 90) - (math.floor(ra / 90) * 90)
    ra /= 15.0

    sin_dec = 0.39782 * math.sin(math.radians(l))
    cos_dec = math.cos(math.asin(sin_dec))

    cos_h = (math.cos(math.radians(zenith)) - (sin_dec * math.sin(math.radians(LAT)))) / (
        cos_dec * math.cos(math.radians(LAT))
    )
    if abs(cos_h) > 1:
        raise ValueError("אין אירוע שמש בתאריך זה בקו רוחב זה")

    h = math.degrees(math.acos(cos_h))
    h = h / 15.0 if sunset else (360 - h) / 15.0

    ut = (h + ra - (0.06571 * t) - 6.622 - lng_hour) % 24
    return (ut + _israel_utc_offset(d)) % 24


def _fmt(hours: float, shift_minutes: int = 0) -> str:
    total = round(hours * 60) + shift_minutes
    return "{:02d}:{:02d}".format((total // 60) % 24, total % 60)


def sunset(d: date) -> float:
    return _solar_event(d, SUNSET_ZENITH, sunset=True)


def candle_lighting(friday: date) -> str:
    return _fmt(sunset(friday), -CANDLE_MINUTES_BEFORE_SUNSET)


def havdalah(saturday: date) -> str:
    return _fmt(sunset(saturday), HAVDALAH_MINUTES_AFTER_SUNSET)


def _parasha(saturday: date) -> str:
    """שם הפרשה/החג בעברית. דורש pyluach; בלעדיו מוחזר טקסט ריק."""
    try:
        from pyluach import dates as pdates, parshios
    except ImportError:
        return ""
    hd = pdates.HebrewDate.from_pydate(saturday)
    holiday = hd.holiday(hebrew=True, israel=True)
    parasha = parshios.getparsha_string(hd, israel=True, hebrew=True)
    if parasha and holiday:
        return "{} ({})".format(parasha, holiday)
    return parasha or holiday or ""


def fridays_between(start: date, end: date):
    d = start + timedelta(days=(4 - start.weekday()) % 7)
    while d <= end:
        yield d
        d += timedelta(days=7)


def build_rows(start: date, end: date):
    rows = []
    for friday in fridays_between(start, end):
        saturday = friday + timedelta(days=1)
        rows.append(
            {
                "תאריך": friday.strftime("%d/%m/%Y"),
                "פרשה": _parasha(saturday),
                "כניסת שבת": candle_lighting(friday),
                "צאת שבת": havdalah(saturday),
            }
        )
    return rows


def main(argv):
    if len(argv) >= 3:
        start = datetime.strptime(argv[1], "%Y-%m-%d").date()
        end = datetime.strptime(argv[2], "%Y-%m-%d").date()
    else:
        start = date.today()
        end = start + timedelta(days=371)

    rows = build_rows(start, end)
    DATA_DIR.mkdir(exist_ok=True)
    out = DATA_DIR / "zmanim.csv"
    with out.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["תאריך", "פרשה", "כניסת שבת", "צאת שבת"])
        writer.writeheader()
        writer.writerows(rows)
    print("נכתבו {} שבתות אל {}".format(len(rows), out))


if __name__ == "__main__":
    main(sys.argv)

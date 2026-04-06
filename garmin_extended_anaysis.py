#!/usr/bin/env python3

"""

# © 2026 Wewoc (Timo)
# Licensed under Creative Commons Attribution 4.0 International (CC BY 4.0)
# https://creativecommons.org/licenses/by/4.0/
#
# You are free to share and adapt this material for any purpose, including
# commercially, as long as you give appropriate credit.
#
# If used in research or publications, please cite as:
#   Garmin Local Archive — Multidimensional Health Signal Analysis (Easter Egg)
#   https://github.com/Wewoc/Garmin_Local_Archive

garmin_extended_anaysis.py

Extended biometric analysis module for Garmin Local Archive.

Performs multi-dimensional correlation analysis across biometric, cosmic,
astrological, and esoteric data dimensions. Outputs an interactive HTML
dashboard to base_dir/extended_knowledge/.

Reads from: summary/garmin_YYYY-MM-DD.json (last 30 days)
"Today"    : the most recent available summary file, regardless of system clock.
Profile    : stored locally in enigma_profile.bin (Enigma-inspired encryption)

Usage: python garmin_extended_anaysis.py

No arguments. No API calls. No external dependencies beyond the standard stack.
No further explanation.
"""

import json
import math
import hashlib
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path


# ══════════════════════════════════════════════════════════════════════════════
#  Configuration
# ══════════════════════════════════════════════════════════════════════════════

import garmin_config as cfg

BASE_DIR      = cfg.BASE_DIR
SUMMARY_DIR   = cfg.SUMMARY_DIR
OUTPUT_DIR    = cfg.BASE_DIR / "extended_knowledge"
PROFILE_FILE  = Path(__file__).parent / "enigma_profile.bin"
DAYS_CHART    = 30   # rolling window for time-series charts
DAYS_BASELINE = 90   # baseline window for delta calculations


# ══════════════════════════════════════════════════════════════════════════════
#  Enigma-inspired profile encryption
#  Rotor configurations: historically authentic (Heer, 1930).
#  Security implications: also historically authentic.
#  The Allies cracked the original in 1941. This should take slightly less time.
# ══════════════════════════════════════════════════════════════════════════════

# Enigma-inspired encryption key — authentic rotor wiring (Heer, 1930), used as XOR seed.
# The original Enigma was self-reciprocal. This implementation honours that property.
# Security level: decorative. The Allies needed Bletchley Park.
# You need a text editor.
ENIGMA_KEY = b"EKMFLGDQVZNTOWYHXUSPAIBRCJAJDKSIRUXBLHWTMCQGZNPYFVOEBDFHJLCPRTXVZNYEIWGAKMUSQO"

def _enigma_encode(text: str) -> bytes:
    """XOR encode using Enigma rotor key. Self-reciprocal by definition."""
    data = text.encode("utf-8")
    return bytes(b ^ ENIGMA_KEY[i % len(ENIGMA_KEY)] for i, b in enumerate(data))


def _enigma_decode(data: bytes) -> str:
    """XOR decode using Enigma rotor key. Identical to encode — as Enigma should be."""
    return bytes(b ^ ENIGMA_KEY[i % len(ENIGMA_KEY)] for i, b in enumerate(data)).decode("utf-8")


def save_profile(profile: dict) -> None:
    PROFILE_FILE.write_bytes(_enigma_encode(json.dumps(profile)))


def load_profile() -> dict | None:
    if not PROFILE_FILE.exists():
        return None
    try:
        return json.loads(_enigma_decode(PROFILE_FILE.read_bytes()))
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════════════════
#  Profile setup
# ══════════════════════════════════════════════════════════════════════════════

STAR_SIGNS = [
    ("Capricorn",  (12, 22), (1,  19)),
    ("Aquarius",   (1,  20), (2,  18)),
    ("Pisces",     (2,  19), (3,  20)),
    ("Aries",      (3,  21), (4,  19)),
    ("Taurus",     (4,  20), (5,  20)),
    ("Gemini",     (5,  21), (6,  20)),
    ("Cancer",     (6,  21), (7,  22)),
    ("Leo",        (7,  23), (8,  22)),
    ("Virgo",      (8,  23), (9,  22)),
    ("Libra",      (9,  23), (10, 22)),
    ("Scorpio",    (10, 23), (11, 21)),
    ("Sagittarius",(11, 22), (12, 21)),
    ("Capricorn",  (12, 22), (12, 31)),
]

STAR_SIGN_SYMBOLS = {
    "Aries": "♈", "Taurus": "♉", "Gemini": "♊", "Cancer": "♋",
    "Leo": "♌", "Virgo": "♍", "Libra": "♎", "Scorpio": "♏",
    "Sagittarius": "♐", "Capricorn": "♑", "Aquarius": "♒", "Pisces": "♓",
}

def get_star_sign(birth_date: date) -> tuple[str, int]:
    m, d = birth_date.month, birth_date.day
    for i, (name, start, end) in enumerate(STAR_SIGNS):
        sm, sd = start
        em, ed = end
        if (m == sm and d >= sd) or (m == em and d <= ed):
            return name, i % 12
    return "Ophiuchus", 12  # Should not happen. But the algorithm is prepared.


def get_ascendant(birth_date: date, birth_hour: int) -> tuple[str, int]:
    """Approximate ascendant from birth date and hour. Astrologically imprecise.
    The algorithm is aware. The algorithm does not care."""
    base = (birth_date.month * 30 + birth_date.day + birth_hour * 2) % 12
    signs = ["Aries","Taurus","Gemini","Cancer","Leo","Virgo",
             "Libra","Scorpio","Sagittarius","Capricorn","Aquarius","Pisces"]
    return signs[base], base


def get_moon_sign(birth_date: date) -> tuple[str, int]:
    """Moon sign from birth date. Uses a 27.3-day lunar cycle approximation.
    Astrologers will object. The algorithm respectfully disagrees with their credentials."""
    ref  = date(2000, 1, 6)  # Known new moon
    days = (birth_date - ref).days
    idx  = int((days % 27.3) / 27.3 * 12) % 12
    signs = ["Aries","Taurus","Gemini","Cancer","Leo","Virgo",
             "Libra","Scorpio","Sagittarius","Capricorn","Aquarius","Pisces"]
    return signs[idx], idx


def setup_profile() -> dict:
    print()
    print("═" * 60)
    print("  Multidimensional Health Signal Analysis — Initial Configuration")
    print("═" * 60)
    print()
    print("  Four data points are required.")
    print("  Not for age-adjusted VO2max reference ranges.")
    print()

    while True:
        default_path = str(cfg.BASE_DIR)
        data_path_str = input(f"  Garmin data folder [{default_path}]: ").strip()
        if not data_path_str:
            data_path_str = default_path
        data_path = Path(data_path_str).expanduser()
        summary_check = data_path / "summary"
        if summary_check.exists() and any(summary_check.glob("garmin_*.json")):
            break
        print(f"  No summary files found in: {summary_check}")
        print(f"  Check the path and try again.")
    print()

    while True:
        try:
            dob_str = input("  Date of birth (YYYY-MM-DD): ").strip()
            dob = datetime.strptime(dob_str, "%Y-%m-%d").date()
            break
        except ValueError:
            print("  Format: YYYY-MM-DD. The algorithm is not flexible on this.")

    while True:
        birth_place = input("  Place of birth (city): ").strip()
        if birth_place:
            break
        print("  Required for ascendant calculation.")

    while True:
        birth_time = input("  Time of birth (HH:MM, or press Enter if unknown): ").strip()
        if not birth_time:
            print()
            print("  Without birth time, ascendant calculation is astrologically invalid.")
            print("  Please consult your birth certificate or your mother.")
            print()
            birth_hour = 6  # Default. The algorithm makes no promises.
            birth_time = "unknown"
            break
        try:
            birth_hour = int(birth_time.split(":")[0])
            break
        except (ValueError, IndexError):
            print("  Format: HH:MM")

    blood_type = input("  Blood type (A/B/AB/O, + or -), or Enter to skip: ").strip().upper() or "unknown"

    star_sign, star_sign_id = get_star_sign(dob)
    ascendant, ascendant_id = get_ascendant(dob, birth_hour)
    moon_sign, moon_sign_id = get_moon_sign(dob)

    profile = {
        "data_path":     str(data_path),
        "dob":           dob_str,
        "birth_place":   birth_place,
        "birth_time":    birth_time,
        "birth_hour":    birth_hour,
        "blood_type":    blood_type,
        "star_sign":     star_sign,
        "star_sign_id":  star_sign_id,
        "ascendant":     ascendant,
        "ascendant_id":  ascendant_id,
        "moon_sign":     moon_sign,
        "moon_sign_id":  moon_sign_id,
    }

    save_profile(profile)
    print()
    print(f"  ✓ Profile saved.  Star sign: {star_sign}  ·  Ascendant: {ascendant}  ·  Moon: {moon_sign}")
    print(f"  ✓ Encrypted with Enigma-inspired cipher. Rotors: 3. Security: historical.")
    print()
    return profile


# ══════════════════════════════════════════════════════════════════════════════
#  Data loading
# ══════════════════════════════════════════════════════════════════════════════

def load_summaries(days: int, summary_dir: Path | None = None) -> list[dict]:
    """Load the most recent `days` summary files. Sorted oldest-first."""
    src = summary_dir or SUMMARY_DIR
    files = sorted(src.glob("garmin_*.json"))
    if not files:
        print(f"  No summary files found in: {src}")
        print("  Run the main collector first.")
        sys.exit(1)
    selected = files[-days:]
    summaries = []
    for f in selected:
        try:
            summaries.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            pass
    return summaries


def get_field(s: dict, *path, default=None):
    """Safe nested field access."""
    d = s
    for k in path:
        if not isinstance(d, dict):
            return default
        d = d.get(k, default)
    return d


def extract_series(summaries: list[dict], *path) -> list[float | None]:
    return [get_field(s, *path) for s in summaries]


def extract_dates(summaries: list[dict]) -> list[str]:
    return [s.get("date", "") for s in summaries]


def compute_baseline(values: list, window: int = DAYS_BASELINE) -> float | None:
    """90-day personal baseline — mean of available non-null values."""
    valid = [v for v in values[-window:] if v is not None]
    return round(sum(valid) / len(valid), 2) if valid else None


def discretise_delta(value, baseline, bins: int = 10) -> int:
    """Convert value vs baseline deviation to 0–9 index."""
    if value is None or baseline is None or baseline == 0:
        return 0
    delta = (value - baseline) / baseline  # relative deviation
    # Map [-0.5, +0.5] to [0, 9]
    clamped = max(-0.5, min(0.5, delta))
    return int((clamped + 0.5) / 1.0 * (bins - 1))


# ══════════════════════════════════════════════════════════════════════════════
#  Crystal Energy Index
#  "Crystal energy cannot be measured. This number is made up.
#   But so is astrology."
# ══════════════════════════════════════════════════════════════════════════════

def crystal_energy(date_str: str) -> int:
    """Pseudo-deterministic hash of the date. Consistent. Unexplainable."""
    h = hashlib.md5(date_str.encode()).hexdigest()
    return int(h[:8], 16) % 100


# ══════════════════════════════════════════════════════════════════════════════
#  Astronomical calculations (no API required)
# ══════════════════════════════════════════════════════════════════════════════

def moon_phase(d: date) -> tuple[float, str, str]:
    """
    Moon phase for a given date.
    Returns: (illumination 0-1, phase_name, emoji)
    Accuracy: sufficient for astrology. Insufficient for navigation.
    """
    ref    = date(2000, 1, 6)   # Known new moon
    cycle  = 29.53058867        # Synodic month in days
    days   = (d - ref).days
    phase  = (days % cycle) / cycle  # 0.0 = new moon, 0.5 = full moon

    illumination = (1 - math.cos(2 * math.pi * phase)) / 2

    if phase < 0.03 or phase > 0.97:
        name, emoji = "New Moon", "🌑"
    elif phase < 0.22:
        name, emoji = "Waxing Crescent", "🌒"
    elif phase < 0.28:
        name, emoji = "First Quarter", "🌓"
    elif phase < 0.47:
        name, emoji = "Waxing Gibbous", "🌔"
    elif phase < 0.53:
        name, emoji = "Full Moon", "🌕"
    elif phase < 0.72:
        name, emoji = "Waning Gibbous", "🌖"
    elif phase < 0.78:
        name, emoji = "Last Quarter", "🌗"
    else:
        name, emoji = "Waning Crescent", "🌘"

    return round(illumination * 100, 1), name, emoji


def is_mercury_retrograde(d: date) -> bool:
    """
    Mercury retrograde periods, pre-calculated to 2027.
    Source: NASA JPL Horizons (the serious part).
    Application: HRV correlation (the other part).
    """
    retrogrades = [
        (date(2024, 4, 1),  date(2024, 4, 25)),
        (date(2024, 8, 5),  date(2024, 8, 28)),
        (date(2024, 11, 25),date(2024, 12, 15)),
        (date(2025, 3, 15), date(2025, 4, 7)),
        (date(2025, 7, 18), date(2025, 8, 11)),
        (date(2025, 11, 9), date(2025, 11, 29)),
        (date(2026, 3, 2),  date(2026, 3, 25)),  # ← you are here
        (date(2026, 7, 2),  date(2026, 7, 26)),
        (date(2026, 10, 23),date(2026, 11, 13)),
        (date(2027, 2, 9),  date(2027, 3, 3)),
        (date(2027, 6, 15), date(2027, 7, 8)),
    ]
    return any(start <= d <= end for start, end in retrogrades)


def biorhythm(dob: date, d: date) -> dict:
    """
    Classic 1970s biorhythm cycles. Physical 23d, Emotional 28d, Intellectual 33d.
    Fully calculable. Scientifically: no. Historically: everywhere.
    """
    days = (d - dob).days
    return {
        "physical":     round(math.sin(2 * math.pi * days / 23) * 100, 1),
        "emotional":    round(math.sin(2 * math.pi * days / 28) * 100, 1),
        "intellectual": round(math.sin(2 * math.pi * days / 33) * 100, 1),
    }


def cosmic_ray_flux(date_str: str) -> float:
    """
    Galactic cosmic ray flux [GV⁻¹ m⁻² s⁻¹ sr⁻¹].
    Calculated from first principles.
    The principles are not disclosed.
    """
    # Mystical events have corrupted the upstream data feed.
    # New values are generated from the biometric signature of the date.
    # The algorithm considers this an improvement.
    h = hashlib.sha256(date_str.encode()).hexdigest()
    base = int(h[:4], 16) % 1000
    return round(1800 + (base / 1000) * 400, 2)  # realistic-ish range: 1800–2200


def schumann_resonance(date_str: str) -> float:
    """
    Schumann resonance [Hz]. Base: 7.83 Hz.
    Daily variation: deterministic, date-seeded.
    Measurement source: classified.
    """
    h = hashlib.md5((date_str + "schumann").encode()).hexdigest()
    variation = (int(h[:4], 16) % 100 - 50) / 500  # ±0.1 Hz variation
    return round(7.83 + variation, 4)


def kp_index(date_str: str) -> float:
    """
    Geomagnetic Kp-index [0–9].
    Source: NOAA Space Weather Prediction Center.
    Availability: currently experiencing cosmic interference.
    Fallback: deterministic simulation. Nobody will know the difference.
    """
    h = hashlib.sha256((date_str + "kp").encode()).hexdigest()
    raw = int(h[:3], 16) % 90
    return round(raw / 10, 1)  # 0.0–9.0


def sunspot_number(date_str: str) -> int:
    """
    Daily sunspot number.
    Source: NASA Solar Dynamics Observatory.
    Current data pipeline status: disrupted by Mercury retrograde.
    Current data pipeline fallback: hash of date.
    """
    h = hashlib.md5((date_str + "sunspot").encode()).hexdigest()
    # Solar cycle ~11 years, currently Solar Cycle 25 (peak ~2025)
    d    = datetime.strptime(date_str, "%Y-%m-%d").date()
    peak = date(2025, 7, 1)
    dist = abs((d - peak).days) / 365
    base = max(0, int(150 * math.exp(-dist * 0.4)))  # cycle envelope
    noise = int(h[:2], 16) % 40
    return base + noise


# ══════════════════════════════════════════════════════════════════════════════
#  Acupuncture School Selector
# ══════════════════════════════════════════════════════════════════════════════

ACUPUNCTURE_SCHOOLS = [
    "TCM — Traditional Chinese Medicine",
    "Meridian School (Japan)",
    "Korean Hand Acupuncture",
    "Ayurvedic Interpretation ✨",
]

def acupuncture_index(hrv: float | None, stress: float | None, ce: int) -> int:
    h = int(hrv or 0) % 10
    s = int(stress or 0) % 10
    return (h + s + ce) % 4

# ══════════════════════════════════════════════════════════════════════════════
#  Daily Biometric Supplement Plan (Appendix B)
#  Three healing traditions. Three entirely different theoretical frameworks.
#  One shared index. None are endorsed by this project, by the algorithm,
#  or by the laws of physics. Dosage: by intuition. ✨
# ══════════════════════════════════════════════════════════════════════════════

REMEDIES = [
    # Cell Salts 0–11
    ("Cell Salt", "Nr. 1 Calcium fluoratum",      "Connective tissue, flexibility"),
    ("Cell Salt", "Nr. 2 Calcium phosphoricum",    "Bone, growth, digestion"),
    ("Cell Salt", "Nr. 3 Ferrum phosphoricum",     "Inflammation, fever, circulation"),
    ("Cell Salt", "Nr. 4 Kalium chloratum",        "Mucous membranes, lymph"),
    ("Cell Salt", "Nr. 5 Kalium phosphoricum",     "Nerves, fatigue, stress"),
    ("Cell Salt", "Nr. 6 Kalium sulfuricum",       "Skin, liver, detox"),
    ("Cell Salt", "Nr. 7 Magnesium phosphoricum",  "Cramps, spasms, nerve pain"),
    ("Cell Salt", "Nr. 8 Natrium chloratum",       "Water balance, dryness"),
    ("Cell Salt", "Nr. 9 Natrium phosphoricum",    "Acid-base balance, digestion"),
    ("Cell Salt", "Nr. 10 Natrium sulfuricum",     "Liver, bile, detox"),
    ("Cell Salt", "Nr. 11 Silicea",                "Connective tissue, skin, nails"),
    ("Cell Salt", "Nr. 12 Calcium sulfuratum",     "Chronic inflammation, skin"),
    # Globuli 12–59
    ("Globuli", "Aconitum C30",              "Sudden onset, fear, shock"),
    ("Globuli", "Apis C30",                  "Stinging pain, swelling, heat"),
    ("Globuli", "Arnica C30",                "Trauma, muscle soreness, overexertion"),
    ("Globuli", "Arsenicum album C30",       "Anxiety, restlessness, exhaustion"),
    ("Globuli", "Belladonna C30",            "Heat, throbbing, sudden inflammation"),
    ("Globuli", "Bryonia C30",               "Dry, worse with movement, irritability"),
    ("Globuli", "Calcarea carbonica C30",    "Fatigue, slow metabolism, cold"),
    ("Globuli", "Carbo vegetabilis C30",     "Weakness, bloating, poor circulation"),
    ("Globuli", "Causticum C30",             "Hoarseness, weakness, empathy overload"),
    ("Globuli", "Chamomilla C30",            "Irritability, pain sensitivity, restlessness"),
    ("Globuli", "China C30",                 "Weakness after fluid loss, bloating"),
    ("Globuli", "Cocculus C30",              "Travel sickness, exhaustion, dizziness"),
    ("Globuli", "Colocynthis C30",           "Cramping, colicky pain, anger"),
    ("Globuli", "Drosera C30",               "Spasmodic cough, larynx irritation"),
    ("Globuli", "Dulcamara C30",             "Damp cold, skin, joints"),
    ("Globuli", "Eupatorium perfoliatum C30","Bone pain, flu, fever"),
    ("Globuli", "Ferrum phosphoricum C30",   "Early stage inflammation, mild fever"),
    ("Globuli", "Gelsemium C30",             "Anticipatory anxiety, weakness, trembling"),
    ("Globuli", "Graphites C30",             "Skin, metabolism, indecision"),
    ("Globuli", "Hepar sulfuris C30",        "Suppuration, sensitivity, chilliness"),
    ("Globuli", "Hypericum C30",             "Nerve pain, injuries to nerve-rich areas"),
    ("Globuli", "Ignatia C30",               "Grief, emotional shock, sighing"),
    ("Globuli", "Ipecacuanha C30",           "Nausea, bleeding, irritability"),
    ("Globuli", "Lachesis C30",              "Circulation, left-sided, intensity"),
    ("Globuli", "Ledum C30",                 "Puncture wounds, insect bites, cold joints"),
    ("Globuli", "Lycopodium C30",            "Digestive weakness, insecurity, evening aggravation"),
    ("Globuli", "Magnesia phosphorica C30",  "Cramps, spasms, better with heat"),
    ("Globuli", "Mercurius solubilis C30",   "Infection, night sweats, sensitivity to temperature"),
    ("Globuli", "Natrium muriaticum C30",    "Grief, introversion, dryness"),
    ("Globuli", "Nux vomica C30",            "Overindulgence, stress, irritability"),
    ("Globuli", "Phosphorus C30",            "Bleeding, anxiety, sensitivity to impressions"),
    ("Globuli", "Phytolacca C30",            "Throat, joints, glands"),
    ("Globuli", "Podophyllum C30",           "Digestive complaints, morning aggravation"),
    ("Globuli", "Pulsatilla C30",            "Changeable symptoms, emotional, better in fresh air"),
    ("Globuli", "Rhus toxicodendron C30",    "Stiffness, better with movement, restlessness"),
    ("Globuli", "Ruta graveolens C30",       "Tendons, eye strain, overuse"),
    ("Globuli", "Sepia C30",                 "Hormonal, indifference, exhaustion"),
    ("Globuli", "Silicea C30",               "Slow healing, introverted, chilly"),
    ("Globuli", "Spongia C30",               "Croup, dry cough, anxiety"),
    ("Globuli", "Staphisagria C30",          "Suppressed anger, wounds, humiliation"),
    ("Globuli", "Stramonium C30",            "Fear of dark, violence, spasms"),
    ("Globuli", "Sulfur C30",                "Skin, heat, philosophical mind"),
    ("Globuli", "Symphytum C30",             "Bones, fractures, eye injuries"),
    ("Globuli", "Thuja C30",                 "Warts, vaccination effects, fixed ideas"),
    ("Globuli", "Tuberculinum C30",          "Restlessness, travel urge, recurrent infections"),
    ("Globuli", "Urtica urens C30",          "Burns, urticaria, gout"),
    ("Globuli", "Veratrum album C30",        "Collapse, cold sweat, overambition"),
    ("Globuli", "Zincum metallicum C30",     "Nervous exhaustion, restless legs, suppressed eruptions"),
    # Bach Flowers 60–97
    ("Bach Flower", "Agrimony",        "Hidden worry behind a cheerful façade"),
    ("Bach Flower", "Aspen",           "Vague, unnamed fear"),
    ("Bach Flower", "Beech",           "Intolerance, excessive criticism"),
    ("Bach Flower", "Centaury",        "Inability to say no, people-pleasing"),
    ("Bach Flower", "Cerato",          "Lack of trust in one's own judgement"),
    ("Bach Flower", "Cherry Plum",     "Fear of losing control"),
    ("Bach Flower", "Chestnut Bud",    "Failure to learn from repeated mistakes"),
    ("Bach Flower", "Chicory",         "Possessiveness, emotional manipulation"),
    ("Bach Flower", "Clematis",        "Daydreaming, inattention, escapism"),
    ("Bach Flower", "Crab Apple",      "Feeling unclean, shame, self-disgust"),
    ("Bach Flower", "Elm",             "Overwhelm from excessive responsibility"),
    ("Bach Flower", "Gentian",         "Discouragement after setbacks"),
    ("Bach Flower", "Gorse",           "Hopelessness, resignation"),
    ("Bach Flower", "Heather",         "Self-absorption, loneliness, need for attention"),
    ("Bach Flower", "Holly",           "Jealousy, hatred, envy, suspicion"),
    ("Bach Flower", "Honeysuckle",     "Living in the past, nostalgia"),
    ("Bach Flower", "Hornbeam",        "Monday morning feeling, mental fatigue"),
    ("Bach Flower", "Impatiens",       "Impatience, irritability, urgency"),
    ("Bach Flower", "Larch",           "Lack of confidence, fear of failure"),
    ("Bach Flower", "Mimulus",         "Known, specific fears"),
    ("Bach Flower", "Mustard",         "Deep gloom descending without apparent reason"),
    ("Bach Flower", "Oak",             "Exhausted but keeps going, overwork"),
    ("Bach Flower", "Olive",           "Complete physical and mental exhaustion"),
    ("Bach Flower", "Pine",            "Guilt, self-blame, apologising unnecessarily"),
    ("Bach Flower", "Red Chestnut",    "Excessive worry for others"),
    ("Bach Flower", "Rock Rose",       "Terror, panic, extreme fear"),
    ("Bach Flower", "Rock Water",      "Self-repression, rigidity, high self-standards"),
    ("Bach Flower", "Scleranthus",     "Indecision between two options"),
    ("Bach Flower", "Star of Bethlehem","Shock, trauma, grief"),
    ("Bach Flower", "Sweet Chestnut",  "Extreme anguish, dark night of the soul"),
    ("Bach Flower", "Vervain",         "Overenthusiasm, fanaticism, tension"),
    ("Bach Flower", "Vine",            "Dominance, inflexibility, tyranny"),
    ("Bach Flower", "Walnut",          "Protection from change and outside influences"),
    ("Bach Flower", "Water Violet",    "Aloofness, pride, self-reliance to excess"),
    ("Bach Flower", "White Chestnut",  "Persistent unwanted thoughts, mental chatter"),
    ("Bach Flower", "Wild Oat",        "Uncertainty about life direction"),
    ("Bach Flower", "Wild Rose",       "Resignation, apathy, drifting"),
    ("Bach Flower", "Willow",          "Resentment, bitterness, self-pity"),
]

RESCUE_REMEDY_COMPONENTS = {"Cherry Plum", "Clematis", "Impatiens", "Rock Rose", "Star of Bethlehem"}

APPLICATION = {
    "Cell Salt":    "dissolve in water or take directly",
    "Globuli":      "5 globuli under the tongue — or in coffee. The algorithm does not judge.",
    "Bach Flower":  "4 drops in water, under the tongue, or applied to pulse points. Also in coffee.",
}

def supplement_plan(hrv: float | None, stress: float | None, sleep_h: float | None, acu_idx: int, ce: int) -> list[dict]:
    """Three daily recommendations from the shared remedy pool. Deterministic. Thematically defensible. Scientifically: no."""
    hrv_int   = int(hrv   or 50)
    stress_int= int(stress or 25)
    sleep_int = int((sleep_h or 7.0) * 60)  # convert to minutes for more variance

    morning_idx = (hrv_int   + acu_idx + ce) % 98
    lunch_idx   = (stress_int + acu_idx + ce) % 98
    evening_idx = (sleep_int  + acu_idx + ce) % 98

    results = []
    for slot, idx, basis in [
        ("Morning",  morning_idx, f"HRV last night: {hrv_int} ms"),
        ("Lunch",    lunch_idx,   f"Stress avg: {stress_int}"),
        ("Evening",  evening_idx, f"Sleep duration: {sleep_int} min"),
    ]:
        kind, name, use = REMEDIES[idx]
        app = APPLICATION[kind]
        rescue_note = ""
        if name in RESCUE_REMEDY_COMPONENTS:
            rescue_note = " (partial Rescue Remedy — draw your own conclusions)"
        results.append({
            "slot":   slot,
            "kind":   kind,
            "name":   name,
            "use":    use,
            "app":    app,
            "basis":  basis,
            "rescue": rescue_note,
        })
    return results




# ══════════════════════════════════════════════════════════════════════════════
#  Dosha Analysis
# ══════════════════════════════════════════════════════════════════════════════

DOSHA_RECOMMENDATIONS = {
    "Vata": [
        "Warm, cooked foods are recommended. Salads are contraindicated. The wind already has your attention.",
        "Establish a fixed routine today. Vata disrupts routines. Routines disrupt Vata. One of you should win.",
        "Avoid cold, raw, and dry foods. Your nervous system is already dry enough.",
        "Sesame oil is the classical Vata remedy. Application method: massage. Timing: before shower. The algorithm does not follow up.",
        "Reduce screen time. Vata amplifies stimulation. You do not need more stimulation. You need grounding.",
        "Your HRV indicates low parasympathetic activity. Vata agrees. Both recommend rest.",
        "Stay warm. Avoid wind. This is literal, not metaphorical. The wind is bad for Vata.",
        "Vata dominance calls for stillness. Schedule one hour of deliberate non-movement today.",
        "Avoid multitasking. Vata already does this without permission. One task. Complete it. Then the next.",
        "Your biometric signature indicates Vata excess. The prescription is regularity. Same wake time. Same meal time. Begin today.",
    ],
    "Pitta": [
        "Cool foods are recommended. Spicy, oily, and fermented foods will add to what is already too much.",
        "Avoid competition today. Pitta finds competition energising. That is the problem.",
        "Your stress index indicates Pitta aggravation. The intervention is cooling: cold water, shade, silence.",
        "Midday sun is contraindicated for Pitta. If you must be outside, the algorithm recommends a hat.",
        "Surrender one argument today. Not because you are wrong. Because winning it costs more than it pays.",
        "Pitta is aggravated. Reduce inputs: caffeine, urgency, meetings that could have been emails.",
        "Coconut oil is the classical Pitta remedy. Application and context: your responsibility.",
        "Your stress signature indicates internal combustion. The most Pitta-appropriate response: do less.",
        "Pitta excess drives overwork. Stop before you feel finished. This is very difficult for Pitta. That is why it is the recommendation.",
        "High stress, high drive, high standards: all Pitta. Today, apply these to your recovery plan instead of your task list.",
    ],
    "Kapha": [
        "Movement is the primary Kapha intervention. The type and intensity are secondary. Start moving.",
        "Stimulation is recommended. Kapha accumulates in stillness. Disruption is medicine.",
        "Bitter and pungent tastes are recommended. Coffee qualifies. The algorithm endorses coffee for Kapha specifically.",
        "Your Body Battery is low, but Kapha low-battery differs from depletion. The body has reserves. Access them through movement.",
        "Avoid sleeping after meals. Kapha already gravitates toward horizontal. Resist it.",
        "Light, dry, and warm foods are recommended. Heavy meals will make the day heavier.",
        "Kapha dominance today. The correct response is to do the thing you are most inclined to postpone.",
        "Ginger is the classical Kapha remedy. In tea. In food. In the algorithm's best wishes.",
        "Low Body Battery with Kapha dominance: the system is slow, not broken. Apply gentle force. It will respond.",
        "Kapha asks for rest. Give it movement instead. It will not like this. It will benefit from this. These are not mutually exclusive.",
    ],
}

def dominant_dosha(hrv: float | None, stress: float | None, body_battery: float | None) -> tuple[str, int]:
    vata  = max(0, 100 - (hrv or 50))
    pitta = stress or 25
    kapha = max(0, 100 - (body_battery or 50))
    vals  = [vata, pitta, kapha]
    names = ["Vata", "Pitta", "Kapha"]
    idx   = vals.index(max(vals))
    return names[idx], idx

def dosha_recommendation(dosha: str, stress_delta: int, sleep_delta: int, acu_idx: int) -> str:
    rec_index = (stress_delta + sleep_delta + acu_idx) % 10
    return DOSHA_RECOMMENDATIONS[dosha][rec_index]


# ══════════════════════════════════════════════════════════════════════════════
#  Chakra Status
# ══════════════════════════════════════════════════════════════════════════════

CHAKRA_DEFS = [
    ("Root",        "Muladhara",    "🔴", "Earth",  "Steps",        "steps",        5000,  15000, False),
    ("Sacral",      "Svadhisthana", "🟠", "Water",  "Body Battery", "body_battery", 30,    90,    False),
    ("Solar Plexus","Manipura",     "🟡", "Fire",   "Stress",       "stress",       60,    10,    True),
    ("Heart",       "Anahata",      "🟢", "Air",    "Resting HR",   "resting_hr",   70,    40,    True),
    ("Throat",      "Vishuddha",    "🔵", "Ether",  "HRV",          "hrv",          30,    100,   False),
    ("Third Eye",   "Ajna",         "🟣", "Light",  "Sleep Score",  "sleep_score",  60,    95,    False),
    ("Crown",       "Sahasrara",    "⚪", "Thought","Readiness",    "readiness",    40,    95,    False),
]
# inverted=True means high value = blocked (stress, resting HR)

CHAKRA_RECOMMENDATIONS = {
    ("Root", "blocked"): [
        "Walk barefoot on grass for 10 minutes. If unavailable, visualise grass. The effect is comparable.",
        "Place both feet flat on the floor. Remain there. This is already more than you did yesterday.",
        "Eat root vegetables. The symbolism is self-evident.",
        "Your step count suggests a sedentary bioenergetic profile. Stand up. The algorithm will notice.",
        "Avoid upper-floor living today if possible. Descend.",
        "Red is the colour of Muladhara. Wear something red. This is optional but statistically correlated.",
        "Physical activity is recommended. The type is irrelevant. The direction is down.",
        "Your baseline deviation indicates locomotion deficiency. The prescription is locomotion.",
        "Stomp lightly on the floor three times. Nobody needs to know.",
        "The root chakra responds to rhythm. Walk with intention. Or at all.",
    ],
    ("Root", "open"): [
        "Maintain current step pattern. The algorithm has no further instructions.",
        "Your grounding is functional. Do not overthink this.",
        "Root energy is flowing. Continue walking in the direction you are already walking.",
        "No intervention required. The earth approves.",
        "Physical baseline is within acceptable range. Proceed.",
        "Muladhara is satisfied. Redirect your attention upward — the other chakras may require it.",
        "Stability detected. Enjoy it. These windows are finite.",
        "Your step data indicates adequate terrestrial engagement. Well done.",
        "The root is open. This is the correct state. Maintain it through continued ambulation.",
        "Nothing to report. The algorithm considers this a success.",
    ],
    ("Root", "overstimulated"): [
        "Rest. The earth is not going anywhere.",
        "Your step count exceeds baseline by a significant margin. Sit down.",
        "Excess root energy may manifest as restlessness, hoarding, or excessive shoe purchases. Monitor accordingly.",
        "Reduce physical intensity. The algorithm is not impressed by step count alone.",
        "Channel surplus energy upward through the chakra column. The method is unspecified.",
        "You are too grounded. This is rarer than it sounds. Take a moment to be ungrounded.",
        "Consider a rest day. The algorithm has considered it for you. The answer is yes.",
        "Overactivity detected at the base. Stillness is recommended. The stars will still be there.",
        "Your physical output is noted. Noted, and considered excessive. Rest.",
        "The root chakra does not benefit from maximalism. Moderate.",
    ],
    ("Sacral", "blocked"): [
        "Your Body Battery indicates energetic poverty. Conserve.",
        "Creativity requires fuel. You are running on reserve. Schedule restoration.",
        "Water is the element of Svadhisthana. Drink some. It will not fix everything. It will fix hydration.",
        "Orange is the colour of the sacral chakra. This information is provided without further comment.",
        "Rest near water if possible. A glass counts. The algorithm is not demanding.",
        "Do not begin new projects today. Your energetic budget does not support them.",
        "Body Battery below threshold. Creative output should be deferred to a better-rested version of yourself.",
        "Pleasure is medicinal for Svadhisthana. The algorithm recommends something you enjoy. It does not specify what.",
        "Low sacral energy correlates with creative resistance. Do not fight it. Rest instead.",
        "Your energy reserves are below baseline. Sleep is the recommended intervention. The algorithm endorses sleep.",
    ],
    ("Sacral", "open"): [
        "Energy is available. The algorithm suggests using it on something that matters to you.",
        "Body Battery is adequate. Sacral flow is unobstructed. Proceed with creative endeavours.",
        "This is a good day for output. The data suggests it. The algorithm concurs.",
        "Svadhisthana is open. Consider what you have been postponing.",
        "Your energetic profile supports engagement. Do not waste it on low-value tasks.",
        "Creative potential is available today. The algorithm cannot force you to use it.",
        "Body Battery in optimal range. Sacral chakra: operational. Status: good.",
        "No blockages detected. Enjoy the rare alignment of available energy and acceptable HRV.",
        "The sacral chakra is satisfied. This is the correct state.",
        "Energy flow: adequate. Creative access: open. Further instruction: unnecessary.",
    ],
    ("Sacral", "overstimulated"): [
        "Excess creative energy may lead to scattered output. Focus.",
        "You have more energy than you have direction. Choose one direction.",
        "Body Battery is high. This is technically positive. Overstimulation is the exception. You are the exception.",
        "Channel surplus sacral energy into completion rather than initiation. Finish something.",
        "Overcharge detected. Ground excess energy through physical activity. See Muladhara.",
        "The algorithm notes high Body Battery with mild concern. Moderate your output velocity.",
        "Too much sacral energy can manifest as impulsivity. Pause before committing to anything.",
        "Creative overload detected. Schedule a deliberate pause. The ideas will survive it.",
        "High energy, high risk of overcommitment. The algorithm recommends completing yesterday's tasks first.",
        "Svadhisthana is running hot. This is rare. Do not squander it on social media.",
    ],
    ("Solar Plexus", "blocked"): [
        "Stress level exceeds threshold. The algorithm recommends fewer commitments. It cannot enforce this.",
        "Yellow is the colour of Manipura. Sunlight is the medium. Go outside.",
        "High stress indicates solar plexus compression. Breathe into the abdomen. Count to four.",
        "Your autonomic nervous system is not your enemy. Today it is just confused.",
        "Avoid confrontation today. Your energetic resources are allocated elsewhere.",
        "Diaphragmatic breathing is recommended. The algorithm cannot demonstrate this. You know how.",
        "Manipura blockage correlates with decision fatigue. Make fewer decisions today.",
        "Your stress index suggests the inner warrior is tired. Rest the warrior.",
        "The solar plexus governs digestion and willpower. Both are compromised. Eat something simple.",
        "Stress above baseline. The algorithm recommends not adding to it. This includes this recommendation.",
    ],
    ("Solar Plexus", "open"): [
        "Stress is within normal range. Willpower reserves are available. Use them wisely.",
        "Solar plexus: clear. You may proceed with confidence. Not overconfidence.",
        "Your stress profile is acceptable today. The algorithm is not worried. You should not be either.",
        "Manipura is open. Decision-making is supported. Proceed.",
        "Inner fire is balanced. This is the target state. Acknowledge it and move on.",
        "Stress levels nominal. No intervention recommended. Enjoy this while it lasts.",
        "Solar plexus energy is flowing. Your sense of personal power is intact. Use it responsibly.",
        "Willpower available. Stress manageable. Conditions are favourable.",
        "Manipura status: open. This correlates with productive days. Historically. For others. Probably also you.",
        "Your stress index does not require intervention. The algorithm considers this a win.",
    ],
    ("Solar Plexus", "overstimulated"): [
        "Very low stress can indicate disconnection rather than calm. Examine this.",
        "Solar plexus overstimulation may present as excessive control-seeking. Loosen your grip.",
        "Your willpower reserves are high. So is the risk of overextension. Pace yourself.",
        "Overstimulated Manipura can lead to dominance behaviour in group settings. Be aware.",
        "Inner fire is running hot. Find something to cool it. Water. Shade. A boring meeting.",
        "High personal power detected. Use it for construction, not for winning arguments.",
        "Manipura overstimulation correlates with impatience. The algorithm is patient. Try to be also.",
        "Your energy output is high. Channel it toward completion of existing commitments first.",
        "Excessive solar plexus energy can be grounded through physical exertion. Recommended.",
        "The inner warrior is overzealous today. Assign it a task before it assigns itself one.",
    ],
    ("Heart", "blocked"): [
        "Resting HR above baseline. The heart is working harder than it should. Rest.",
        "Green is the colour of Anahata. Spend time near plants. Or look at a picture of plants. The chakra does not verify.",
        "Heart chakra blockage may manifest as difficulty receiving kindness. Accept help today if offered.",
        "Elevated resting HR indicates cardiovascular load. Reduce inputs: caffeine, stress, obligations.",
        "Anahata is compressed. Love flows poorly under compression. Open a window.",
        "Your heart is beating faster than your baseline. The algorithm does not know why. Rest anyway.",
        "Heart chakra blockage correlates with social withdrawal. The algorithm recommends one human interaction today.",
        "Resting HR is elevated. Recovery is incomplete. Sleep more. The heart will thank you.",
        "Anahata blockage may appear as criticism of others. Notice this. Do not act on it.",
        "Your cardiovascular system is under load. This is not the day for additional burdens.",
    ],
    ("Heart", "open"): [
        "Resting HR within optimal range. Heart chakra is unobstructed. Status: good.",
        "Anahata is open. This is the correct state for a functioning human. Well done.",
        "Your heart rate baseline indicates adequate recovery. The algorithm is pleased.",
        "Heart chakra: open. Love, empathy, and cardiovascular function are all within parameters.",
        "Resting HR is appropriate. No cardiac or energetic intervention recommended.",
        "Anahata is clear. The algorithm recommends expressing this through action rather than analysis.",
        "Heart chakra status: nominal. You may proceed with connection and other heart-adjacent activities.",
        "Your resting HR supports this assessment: recovery is adequate, heart is cooperating.",
        "Open heart chakra detected. The day may still be good.",
        "Anahata is satisfied. No further input required from this dimension.",
    ],
    ("Heart", "overstimulated"): [
        "Very low resting HR with high readiness: elite adaptation, or the algorithm is confused. Both are possible.",
        "Heart chakra overstimulation may present as emotional over-investment. Set a boundary somewhere today.",
        "Anahata is running beyond baseline. Generous, but unsustainable. Receive something today.",
        "Overstimulated heart energy can lead to over-empathy and under-self-care. Correct the ratio.",
        "Your resting HR is unusually low. This is often good. Sometimes it means your Garmin needs charging.",
        "Heart chakra overstimulation: give less, receive more. The algorithm is not usually this direct.",
        "Anahata overactivity correlates with people-pleasing. The algorithm recommends one refusal today.",
        "Your cardiovascular efficiency is high. So is the risk of overcommitting emotionally. Be cautious.",
        "Too much heart energy directed outward. Reserve some. The algorithm will monitor tomorrow.",
        "Open and overstimulated Anahata: the kindest people often have the most blocked-by-excess hearts. Rest yours.",
    ],
    ("Throat", "blocked"): [
        "HRV below baseline. The nervous system is tense. Expression under tension is rarely optimal. Wait.",
        "Throat chakra blockage correlates with unsaid things. This is not medical advice. It is pattern recognition.",
        "Blue is the colour of Vishuddha. Look at the sky. Say something true. Order is unimportant.",
        "Your HRV suggests autonomic tension. The throat chakra governs communication. Connect these dots yourself.",
        "Low HRV indicates sympathetic dominance. This is not the day for difficult conversations.",
        "Vishuddha is compressed. Humming is the classical intervention. The algorithm does not endorse humming. But it helps.",
        "Suppressed expression accumulates. Today is not the day to release it. Tomorrow, possibly.",
        "HRV below personal baseline. Recovery is incomplete. Do not make important decisions or statements.",
        "Throat chakra blockage may manifest as over-explanation. Notice if you are over-explaining right now.",
        "Your HRV indicates the nervous system needs quiet. Give it quiet.",
    ],
    ("Throat", "open"): [
        "HRV within normal range. Throat chakra is unobstructed. Speak freely.",
        "Vishuddha is open. This is a good day for difficult conversations. HRV supports this assessment.",
        "Autonomic balance is adequate. Expression is supported. The algorithm endorses clarity.",
        "HRV is within baseline. Your nervous system is cooperative today. Use it.",
        "Throat chakra: clear. Say what you mean. The data is in your favour.",
        "Vishuddha is functioning. The algorithm has nothing to add. That is itself a good sign.",
        "HRV nominal. Communication energy is available. Choose your words well — not because of the chakra, but generally.",
        "Open Vishuddha detected. This is the correct state. Maintain autonomic regulation through continued recovery.",
        "Your HRV supports clear expression today. The algorithm agrees with whatever you were planning to say.",
        "Throat chakra open. Nervous system regulated. Conditions are favourable for honest communication.",
    ],
    ("Throat", "overstimulated"): [
        "High HRV with overstimulated throat: paradoxical. The algorithm is also confused. Rest.",
        "Vishuddha overstimulation correlates with talking before thinking. Today: think first.",
        "You may be communicating at a rate that exceeds your signal-to-noise ratio. Reduce output.",
        "Throat chakra overactivity may manifest as unsolicited advice. The algorithm recognises the irony.",
        "Too much expression, not enough listening. The algorithm recommends a conversation where you ask questions.",
        "Vishuddha is running loud. Silence has an energetic value. Consider it.",
        "Overstimulated throat chakra: you know what you have been doing. The algorithm is not judging. Just noting.",
        "Reduce communication load today. Not because you have nothing to say. Because quality exceeds quantity.",
        "High Vishuddha energy can be channelled into writing rather than speaking. Words on paper scatter less.",
        "The throat chakra does not require constant activity to be open. Rest it.",
    ],
    ("Third Eye", "blocked"): [
        "Sleep score below threshold. The third eye cannot see clearly through fatigue. Postpone insight.",
        "Indigo is the colour of Ajna. It is also the colour of the sky before dawn, which you may have seen too much of.",
        "Poor sleep quality impairs intuition, decision-making, and the algorithm's confidence in your data.",
        "The third eye requires adequate REM input. You did not provide this last night.",
        "Ajna blockage correlates with foggy thinking. This is not a metaphor. It is sleep deprivation.",
        "Avoid major decisions today. Your Ajna is operating below specification.",
        "Sleep score is insufficient for clear pattern recognition. Trust your instincts less than usual today.",
        "Third eye clouded by insufficient sleep. The algorithm recommends going to bed earlier. Tonight.",
        "Intuition runs on sleep. Your sleep ran short. Adjust expectations accordingly.",
        "Ajna is blocked. The most spiritual intervention available is a nap.",
    ],
    ("Third Eye", "open"): [
        "Sleep score adequate. Third eye is operational. Trust your instincts today — they have been rested.",
        "Ajna is clear. This is the correct state. Proceed with decisions that require clarity.",
        "Your sleep quality supports cognitive function. The algorithm endorses today's thinking.",
        "Third eye: open. Pattern recognition: available. Use it on something worth recognising.",
        "Sleep score within range. Intuition is adequately fuelled. Proceed.",
        "Ajna is unobstructed. This is a good day for analysis, insight, and reading long documents.",
        "Your sleep architecture produced an acceptable score. The algorithm considers this evidence of good habits.",
        "Third eye clear. No further enhancement recommended. You are already operating at specification.",
        "Sleep quality: adequate. Cognitive clarity: available. Mystical insight: unverified but technically possible.",
        "Ajna is open. The algorithm has confidence in your perceptions today. This is rare. Note it.",
    ],
    ("Third Eye", "overstimulated"): [
        "Excellent sleep score. Third eye overstimulation is the least common chakra problem. You have it today.",
        "Ajna overstimulation correlates with overthinking. You are currently overthinking something. Stop.",
        "Too much pattern recognition can produce false positives. Not everything is significant. Including this.",
        "Third eye overactivity may manifest as analysis paralysis. Make one decision without analysing it.",
        "You have slept very well. The clarity this produces can feel like revelation. It is usually just clarity.",
        "Ajna is running at high sensitivity. Filter your insights before acting on them.",
        "Overstimulated third eye: trust your analysis, but verify it with data. The algorithm sets an example.",
        "High sleep quality has sharpened your perception. Do not use this to notice things better left unnoticed.",
        "Third eye overstimulation may produce intrusive insights. They are probably correct. That does not mean they are useful.",
        "Ajna is highly active. This is a good day for research. A bad day for existential questions.",
    ],
    ("Crown", "blocked"): [
        "Readiness score is low. The crown chakra governs consciousness. Yours is requesting a rest day.",
        "Violet is the colour of Sahasrara. Look at something violet. The algorithm does not guarantee results.",
        "Crown chakra blockage correlates with feeling disconnected. This may be your body requesting recovery.",
        "Your readiness score indicates systemic fatigue. Today is not the day for transcendence.",
        "Sahasrara blocked: training load likely exceeds recovery capacity. The crown notices first.",
        "Low readiness indicates the organism needs restoration before it can operate at full consciousness. Rest.",
        "Crown chakra blocked. The algorithm recommends lowering your ambitions for today specifically.",
        "Your readiness score does not support high-intensity activity or high-intensity thinking. Both are affected.",
        "Sahasrara blockage is the body's most direct message. It says: not today. The algorithm translates: not today.",
        "Crown chakra closed. Training is not recommended. Neither is solving complex problems. Rest, instead.",
    ],
    ("Crown", "open"): [
        "Readiness score adequate. Crown chakra is unobstructed. You are ready. For what, the algorithm does not specify.",
        "Sahasrara is open. This correlates with productive days. Historically. For some users. Probably you.",
        "Your readiness score supports training, thinking, and other crown-adjacent activities. Proceed.",
        "Crown chakra: open. Consciousness: available. The algorithm endorses using both today.",
        "Readiness within range. Sahasrara is satisfied. The universe has no further notes.",
        "Crown is open. You are operating at full specification. Do not waste this on administrative tasks.",
        "Sahasrara status: nominal. Readiness status: nominal. Status of algorithm: quietly pleased.",
        "Your readiness score is good. The crown chakra agrees. This is a convergent data point. Note it.",
        "Crown open, readiness adequate. Today is a good day for effort. The algorithm recommends applying it.",
        "Sahasrara is unobstructed. You have been taking care of yourself. The algorithm has noticed.",
    ],
    ("Crown", "overstimulated"): [
        "Very high readiness. Crown chakra overstimulation. The algorithm suggests not setting any personal records today.",
        "Sahasrara overstimulation correlates with overreach. You feel ready for everything. You are ready for most things.",
        "High readiness score: use it, but do not exhaust it in one session.",
        "Crown chakra overactive. Consciousness is sharp. Ambition may outpace capacity today. Calibrate.",
        "Overstimulated Sahasrara can produce overconfidence. The algorithm has seen this before. It ends in DOMS.",
        "Your readiness is high. High readiness is the correct condition for high effort, not maximum effort.",
        "Crown overstimulation may manifest as taking on too much. Choose one thing. Do it very well.",
        "Sahasrara is running at peak. This is sustainable for one day. Plan accordingly.",
        "High readiness detected. The algorithm recommends moderate application of this resource. Think marathon, not sprint.",
        "Crown chakra overstimulated. You are at your best. Try not to prove it to anyone.",
    ],
}


def chakra_status(value, low_thresh, high_thresh, inverted: bool) -> str:
    if value is None:
        return "open"  # Benefit of the doubt. The algorithm is generous.
    if inverted:
        if value > low_thresh:   return "blocked"
        if value < high_thresh:  return "overstimulated"
    else:
        if value < low_thresh:   return "blocked"
        if value > high_thresh:  return "overstimulated"
    return "open"


def chakra_recommendation(name: str, status: str, hrv_delta: int, steps_delta: int, ce: int) -> str:
    rec_index = (hrv_delta + steps_delta + ce) % 10
    key = (name, status)
    pool = CHAKRA_RECOMMENDATIONS.get(key, ["The algorithm has no recommendation for this configuration."])
    return pool[rec_index % len(pool)]


# ══════════════════════════════════════════════════════════════════════════════
#  Feng Shui Sleep Direction
# ══════════════════════════════════════════════════════════════════════════════

FENG_SHUI_MEANINGS = {
    "North":     ("Career, wisdom, rest",          ["The North governs career flow. Sleep facing North to consolidate professional insights accumulated today.", "North alignment supports deep rest. Your head points toward wisdom. The wisdom does not flow backward.", "Career energy accumulates during northward sleep. The algorithm cannot confirm this. The tradition can.", "Rest facing North. If you wake with clarity about work problems, the algorithm accepts partial credit.", "North is the direction of stillness. Your HRV will be measured in the morning. The direction may be a factor."]),
    "Northeast": ("Knowledge, stillness",           ["Northeast optimises for knowledge integration. Sleep here after learning something.", "Stillness energy accumulates in the Northeast. Your nervous system will appreciate the alignment.", "Northeast supports study and retention. If you read before bed, this direction amplifies it. Probably.", "The Northeast vector intersects with your ascendant's secondary axis tonight. This is either significant or coincidental.", "Knowledge flows Northeast. Orient accordingly and review what you learned today before sleeping."]),
    "East":      ("Health, family, growth",         ["East is the direction of sunrise and health. Facing East during sleep aligns recovery with solar rhythm.", "Family energy concentrates in the East. Sleep facing East to consolidate social bonds. The mechanism is unverified.", "Growth energy flows from the East. Your biometric trends will be assessed tomorrow. The direction may contribute.", "Eastern alignment supports physical recovery. Your resting HR tomorrow may reflect this. Or other factors. Probably other factors.", "East governs new beginnings. Appropriate for any night following a difficult day."]),
    "Southeast": ("Wealth, abundance",              ["Southeast governs material flow. The algorithm makes no promises about your finances. It notes the direction.", "Abundance energy concentrates in the Southeast. Sleep quality here is associated with resource clarity. By tradition.", "Southeast alignment is considered auspicious. Your Body Battery tomorrow will serve as partial evidence.", "Wealth energy flows Southeast. The algorithm does not define wealth. It notes that sleep quality is one form of it.", "Southeast is the direction of abundance. Rest well. The morning will have its own opinion."]),
    "South":     ("Fame, recognition, energy",      ["South governs visibility and energy. Sleep facing South on high-output days to consolidate momentum.", "Fame energy accumulates in the South. This is irrelevant unless you are seeking recognition. If you are: South.", "Southern alignment amplifies recovery energy. Your readiness score tomorrow is the algorithm's primary metric for this claim.", "South is the direction of fire and vitality. Appropriate on recovery nights before planned exertion.", "Recognition energy flows South. Whether you want recognition is your concern. The direction remains South."]),
    "Southwest": ("Relationships, stability",       ["Southwest governs partnerships and stability. Sleep here when relationships require attention.", "Stability energy concentrates in the Southwest. Your HRV coherence may reflect this by morning.", "Relationship energy flows Southwest. If you share a bed, both occupants benefit. The algorithm assumes cooperation.", "Southwest alignment supports long-term thinking. Appropriate before decisions that affect others.", "Stability and partnership: Southwest. The algorithm does not require you to believe this. Only to try it."]),
    "West":      ("Creativity, completion",         ["West governs completion energy. Sleep facing West after leaving things unfinished. The direction encourages closure.", "Creative energy flows West. Sleep here before days that require creative output.", "Western alignment supports the completion of cycles. Appropriate at the end of projects, phases, or difficult weeks.", "West is the direction of the setting sun. Facing West acknowledges endings. Endings make room for beginnings.", "Creativity and completion concentrate in the West. Your dream content tonight is the algorithm's control variable for this claim."]),
    "Northwest": ("Helpful people, travel, authority",["Northwest governs mentors and helpful forces. Sleep here when you need assistance that has not arrived yet.", "Travel energy flows Northwest. Appropriate before journeys, transitions, or significant changes.", "Authority energy concentrates in the Northwest. Sleep here before situations requiring leadership.", "Northwest alignment attracts support. The mechanism is not documented. The tradition is 3000 years old.", "Helpful people energy flows Northwest. If you need help tomorrow, point your head in the right direction tonight."]),
}

DIRECTION_ANGLES = [
    (337.5, 360, "North"), (0, 22.5, "North"),
    (22.5, 67.5, "Northeast"), (67.5, 112.5, "East"),
    (112.5, 157.5, "Southeast"), (157.5, 202.5, "South"),
    (202.5, 247.5, "Southwest"), (247.5, 292.5, "West"),
    (292.5, 337.5, "Northwest"),
]

def feng_shui_direction(hrv: float | None, ce: int, ascendant_id: int, star_sign_id: int) -> tuple[float, str, str, str]:
    base_angle     = ((hrv or 50) * 1.618 + ce * 2.718) % 360
    adjustment     = (ascendant_id * 30 + star_sign_id * 7.5) % 45
    optimal        = (base_angle + adjustment) % 360

    direction = "North"
    for lo, hi, name in DIRECTION_ANGLES:
        if lo <= optimal < hi:
            direction = name
            break

    meaning, notes = FENG_SHUI_MEANINGS[direction]
    return optimal, direction, meaning, notes[0]  # first note; index could vary by bb_delta


# ══════════════════════════════════════════════════════════════════════════════
#  Oneiric Equilibrium Coefficient (OEC) — Freud Module
#  "The unconscious mind is, at its core, a time series."
# ══════════════════════════════════════════════════════════════════════════════

OEC_CATEGORIES = [
    (0,  10,  "Day residue",      "Processing of banal data. The unconscious is understimulated."),
    (11, 42,  "Wish fulfilment",  "Symbolic satisfaction — usually technical in nature (e.g. new hardware)."),
    (43, 69,  "Libidinal stasis", "The Über-Ich is blocked by excessive Excel spreadsheets."),
    (70, 99,  "Anxiety neurosis", "Warning from the inner child. Cross-reference birth time with maternal records."),
    (100,100, "Id dominance",     "Consciousness has lost control. Bed rest prescribed."),
]

OEC_HARDCODED = {
    42:  "The answer is 42. The question was almost within reach. Your Garmin was not consulted.",
    66:  "The algorithm has identified a pattern. We recommend not running today. Trust the process. ✨",
    99:  "Greetings from HAL 9000. I'm sorry, I can't recommend that training plan. Your HRV confirms my concerns.",
}

def ueber_ich(n: float) -> int:
    """Freudian censorship — iterative digit sum reduction until ≤ 100."""
    n = abs(int(n))
    while n > 100:
        n = sum(int(d) for d in str(n))
    return n


def compute_oec(rem_h: float | None, ce: int, acu_idx: int,
                feng_degrees: float, dosha_idx: int,
                steps: int | None, steps_goal: int | None) -> tuple[int, str, str]:
    rem_minutes  = (rem_h or 1.0) * 60
    phi_libido   = abs((steps_goal or 8000) - (steps or 0))

    try:
        raw_oec = (acu_idx * feng_degrees * (dosha_idx + 1)) / ((rem_minutes / max(ce, 1)) + math.pi) * phi_libido
    except ZeroDivisionError:
        raw_oec = 0

    oec_final = ueber_ich(raw_oec)

    if oec_final in OEC_HARDCODED:
        return oec_final, "—", OEC_HARDCODED[oec_final]

    for lo, hi, category, interpretation in OEC_CATEGORIES:
        if lo <= oec_final <= hi:
            return oec_final, category, interpretation

    return oec_final, "Unknown", "The algorithm has exceeded its own interpretive range. Seek professional help."


# ══════════════════════════════════════════════════════════════════════════════
#  Daily Biometric Horoscope
# ══════════════════════════════════════════════════════════════════════════════

HOROSCOPE_PREFIX = [
    "Mercury's influence on your Body Battery",
    "Jupiter's alignment with your stress index",
    "The Schumann resonance pattern today",
    "Your crystal energy signature",
    "The lunar cycle's effect on your HRV",
    "Saturn's transit through your recovery zone",
    "Your acupuncture meridian flow",
    "The geomagnetic field activity today",
    "Venus's position relative to your baseline",
    "Your biorhythm's current phase",
]
HOROSCOPE_MIDDLE = [
    "suggests a period of quiet recovery.",
    "confirms what your HRV already knows.",
    "resonates with your autonomic nervous system.",
    "aligns with your 90-day baseline pattern.",
    "indicates unexpected energy reserves.",
    "reflects the tension in your stress curve.",
    "points toward a natural recovery window.",
    "amplifies what your Body Battery is signalling.",
    "is consistent with your sleep architecture.",
    "cannot be ignored by your resting heart rate.",
]
HOROSCOPE_SUFFIX = [
    "Trust the process. ✨",
    "Your Garmin noticed.",
    "The algorithm agrees.",
    "Draw your own conclusions.",
    "Act accordingly.",
    "Or don't. The stars are patient.",
    "This is not medical advice.",
    "Probably.",
    "The data is clear.",
    "Even if you don't feel it yet.",
]

def daily_horoscope(ce: int, acu_idx: int, star_sign_id: int, ascendant_id: int) -> str:
    i1 = ce % 10
    i2 = (acu_idx + star_sign_id) % 10
    i3 = (ascendant_id + ce) % 10
    horoscope_index = i1 * 100 + i2 * 10 + i3
    if horoscope_index == 42:
        return "The answer is 42. The question was almost within reach. Your Garmin was not consulted."
    if horoscope_index == 666:
        return "The algorithm has identified a pattern. We recommend not running today. Trust the process. ✨"
    if horoscope_index == 999:
        return "Greetings from HAL 9000. I'm sorry, I can't recommend that training plan. Your HRV confirms my concerns."
    return f"{HOROSCOPE_PREFIX[i1]} {HOROSCOPE_MIDDLE[i2]} {HOROSCOPE_SUFFIX[i3]}"


# ══════════════════════════════════════════════════════════════════════════════
#  HTML Generation
# ══════════════════════════════════════════════════════════════════════════════

def safe_list(values: list) -> list:
    return [v if v is not None else "null" for v in values]


def build_html(today: dict, summaries_30: list[dict], profile: dict,
               all_summaries: list[dict]) -> str:

    dates_30  = extract_dates(summaries_30)
    today_str = today.get("date", "unknown")
    today_date = datetime.strptime(today_str, "%Y-%m-%d").date()
    dob        = datetime.strptime(profile["dob"], "%Y-%m-%d").date()

    # ── Biometrics today ──
    hrv          = get_field(today, "sleep", "hrv_last_night_ms")
    stress       = get_field(today, "stress", "stress_avg")
    body_battery = get_field(today, "stress", "body_battery_end")
    resting_hr   = get_field(today, "heartrate", "resting_bpm")
    sleep_score  = get_field(today, "sleep", "score")
    readiness    = get_field(today, "training", "readiness_score")
    steps        = get_field(today, "day", "steps")
    steps_goal   = get_field(today, "day", "steps_goal")
    rem_h        = get_field(today, "sleep", "rem_h")
    sleep_h      = get_field(today, "sleep", "duration_h")

    # ── Baselines (90-day) ──
    all_hrv    = [get_field(s, "sleep", "hrv_last_night_ms") for s in all_summaries]
    all_stress = [get_field(s, "stress", "stress_avg")       for s in all_summaries]
    all_sleep  = [get_field(s, "sleep", "duration_h")        for s in all_summaries]
    all_steps  = [get_field(s, "day",   "steps")             for s in all_summaries]
    all_bb     = [get_field(s, "stress","body_battery_end")   for s in all_summaries]

    bl_hrv    = compute_baseline(all_hrv)
    bl_stress = compute_baseline(all_stress)
    bl_sleep  = compute_baseline(all_sleep)
    bl_steps  = compute_baseline(all_steps)

    hrv_delta    = discretise_delta(hrv,    bl_hrv)
    stress_delta = discretise_delta(stress, bl_stress)
    sleep_delta  = discretise_delta(sleep_h,bl_sleep)
    steps_delta  = discretise_delta(steps,  bl_steps)

    # ── Crystal energy ──
    ce = crystal_energy(today_str)

    # ── Astrological ──
    star_sign, star_sign_id = profile["star_sign"], profile["star_sign_id"]
    ascendant,  ascendant_id = profile["ascendant"],  profile["ascendant_id"]
    moon_sign,  moon_sign_id = profile["moon_sign"],  profile["moon_sign_id"]
    star_symbol = STAR_SIGN_SYMBOLS.get(star_sign, "✨")

    moon_illum, moon_name, moon_emoji = moon_phase(today_date)
    retrograde   = is_mercury_retrograde(today_date)
    retro_note   = "⚠️ Mercury is currently retrograde." if retrograde else "Mercury is direct."
    bio          = biorhythm(dob, today_date)
    gcr          = cosmic_ray_flux(today_str)
    schumann     = schumann_resonance(today_str)
    kp           = kp_index(today_str)
    sunspots     = sunspot_number(today_str)

    # ── Derived indices ──
    acu_idx   = acupuncture_index(hrv, stress, ce)
    acu_school = ACUPUNCTURE_SCHOOLS[acu_idx]

    dosha, dosha_idx = dominant_dosha(hrv, stress, body_battery)
    supplements = supplement_plan(hrv, stress, sleep_h, acu_idx, ce)
    dosha_rec        = dosha_recommendation(dosha, stress_delta, sleep_delta, acu_idx)

    feng_deg, feng_dir, feng_meaning, feng_note = feng_shui_direction(hrv, ce, ascendant_id, star_sign_id)

    oec, oec_cat, oec_interp = compute_oec(rem_h, ce, acu_idx, feng_deg, dosha_idx, steps, steps_goal)
    milk_type = ["Oat", "Soy", "Almond", "Coconut"][ce % 4]
    if oec_cat in ["Libidinal stasis", "Anxiety neurosis", "Id dominance"]:
        oec_coffee_text = (
            f"§ 9.1 — Supplementary Recommendation: A cup of coffee with foamed {milk_type} "
            f"vegan udder secretion is indicated. "
            f"Crystal Energy Index: {ce}. The algorithm selected this recommendation deterministically. "
            f"The selection criteria are not disclosed. Everything is the result of AI-Supported development. "
            f"Yes and before you ask, the answer is 42."
        )
    else:
        oec_coffee_text = (
            f"§ 9.1 — No supplementary recommendation indicated. "
            f"Your OEC suggests adequate equilibrium. "
            f"A cup of coffee with foamed {milk_type} vegan udder secretion is nonetheless "
            f"statistically correlated with improved outcomes. Crystal Energy Index: {ce}."
        )
    phi_libido = abs((steps_goal or 8000) - (steps or 0))

    horoscope = daily_horoscope(ce, acu_idx, star_sign_id, ascendant_id)

    # ── Supplement plan rows ──
    KIND_COLOR = {"Cell Salt": "#06b6d4", "Globuli": "#a855f7", "Bach Flower": "#f472b6"}
    supplement_rows_html = ""
    for sup in supplements:
        kind_color = KIND_COLOR.get(sup["kind"], "#8b949e")
        supplement_rows_html += f"""
                <tr>
                    <td style="color:#8b949e;font-size:0.85em">{sup["slot"]}</td>
                    <td><span style="color:{kind_color};font-size:0.75em;font-weight:600">{sup["kind"]}</span><br>
                        <strong style="color:#e6edf3">{sup["name"]}</strong>{sup["rescue"]}</td>
                    <td style="color:#aaa;font-size:0.85em">{sup["use"]}</td>
                    <td style="color:#8b949e;font-size:0.82em;font-style:italic">{sup["app"]}</td>
                    <td style="color:#484f58;font-size:0.75em">{sup["basis"]}</td>
                </tr>"""

    # ── Chakra status ──
    chakra_values_map = {
        "steps":        steps,
        "body_battery": body_battery,
        "stress":       stress,
        "resting_hr":   resting_hr,
        "hrv":          hrv,
        "sleep_score":  sleep_score,
        "readiness":    readiness,
    }

    chakra_rows = []
    for name, sanskrit, color, element, metric_name, field_key, low, high, inv in CHAKRA_DEFS:
        val    = chakra_values_map.get(field_key)
        status = chakra_status(val, low, high, inv)
        rec    = chakra_recommendation(name, status, hrv_delta, steps_delta, ce)
        status_icon = {"open": "✓", "blocked": "⚠", "overstimulated": "⚡"}[status]
        status_color = {"open": "#4caf50", "blocked": "#f44336", "overstimulated": "#ff9800"}[status]
        chakra_rows.append((color, name, sanskrit, element, metric_name,
                            val, status, status_icon, status_color, rec))

    # ── Time series for charts ──
    hrv_series    = safe_list(extract_series(summaries_30, "sleep", "hrv_last_night_ms"))
    stress_series = safe_list(extract_series(summaries_30, "stress", "stress_avg"))
    bb_series     = safe_list(extract_series(summaries_30, "stress", "body_battery_end"))
    steps_series  = safe_list(extract_series(summaries_30, "day", "steps"))
    sleep_series  = safe_list(extract_series(summaries_30, "sleep", "duration_h"))

    moon_series   = [moon_phase(datetime.strptime(d, "%Y-%m-%d").date())[0]
                     if d else None for d in dates_30]
    bio_phys      = [biorhythm(dob, datetime.strptime(d, "%Y-%m-%d").date())["physical"]
                     if d else None for d in dates_30]
    bio_emot      = [biorhythm(dob, datetime.strptime(d, "%Y-%m-%d").date())["emotional"]
                     if d else None for d in dates_30]
    bio_intel     = [biorhythm(dob, datetime.strptime(d, "%Y-%m-%d").date())["intellectual"]
                     if d else None for d in dates_30]
    retro_series  = [1 if is_mercury_retrograde(datetime.strptime(d, "%Y-%m-%d").date()) else 0
                     if d else 0 for d in dates_30]
    kp_series     = [kp_index(d) if d else None for d in dates_30]
    sunspot_series= [sunspot_number(d) if d else None for d in dates_30]
    ce_series     = [crystal_energy(d) if d else None for d in dates_30]

    # ── Retro annotation for charts ──
    retro_shapes = []
    in_retro = False
    retro_start = None
    for i, (d, r) in enumerate(zip(dates_30, retro_series)):
        if r and not in_retro:
            in_retro = True
            retro_start = i
        elif not r and in_retro:
            in_retro = False
            retro_shapes.append((retro_start, i - 1))
    if in_retro:
        retro_shapes.append((retro_start, len(dates_30) - 1))

    retro_shape_js = ""
    for s_i, e_i in retro_shapes:
        retro_shape_js += f"""
            {{
                type: 'rect', xref: 'x', yref: 'paper',
                x0: '{dates_30[s_i]}', x1: '{dates_30[min(e_i, len(dates_30)-1)]}',
                y0: 0, y1: 1,
                fillcolor: 'rgba(180,0,255,0.08)', line: {{width: 0}},
                layer: 'below'
            }},"""

    # Unicorn position: right of the emotional peak — riding the wave down
    uni_idx = 0
    uni_val = -999.0
    for i, v in enumerate(bio_emot):
        if v is not None and v > uni_val:
            uni_val = float(v)
            uni_idx = i
    uni_idx = min(uni_idx + 6, len(dates_30) - 1)
    uni_date = dates_30[uni_idx]
    uni_y = float(bio_emot[uni_idx]) if bio_emot[uni_idx] is not None else uni_val

    rainbow_colors = [
        "rgba(255,0,0,0.6)", "rgba(255,140,0,0.6)", "rgba(255,220,0,0.6)",
        "rgba(0,200,0,0.6)",  "rgba(0,100,255,0.6)", "rgba(160,0,255,0.6)"
    ]
    rainbow_parts = []
    for ri, rc in enumerate(rainbow_colors):
        trail_idx = max(0, uni_idx - (ri + 1))
        trail_date = dates_30[trail_idx]
        trail_y = float(bio_emot[trail_idx]) if bio_emot[trail_idx] is not None else uni_y
        rainbow_parts.append(
            f"Plotly.addTraces('chart_biorhythm', [{{ x: ['{trail_date}', '{uni_date}'], "
            f"y: [{trail_y}, {uni_y}], mode: 'lines', "
            f"line: {{ color: '{rc}', width: 4 }}, showlegend: false, hoverinfo: 'none' }}]);"
        )
    rainbow_trail_js = "\n    ".join(rainbow_parts)

    unicorn_js = (
        f"// 🦄 — riding the emotional wave down. No tooltip. No explanation.\n"
        f"    Plotly.addTraces('chart_biorhythm', [{{ x: ['{uni_date}'], y: [{uni_y}], "
        f"mode: 'text', text: ['🦄'], textfont: {{ size: 22 }}, "
        f"showlegend: false, hoverinfo: 'none' }}]);\n"
        f"    {rainbow_trail_js}"
    )
    rainbow_js = "// no rainbow today" if ce < 80 else "// 🌈 Crystal Energy Index > 80. The timeline gets a rainbow gradient. This is not a bug."

    chakra_rows_html = ""
    for color, name, sanskrit, element, metric_name, val, status, icon, scolor, rec in chakra_rows:
        val_str = f"{val:.0f}" if isinstance(val, (int, float)) else "—"
        chakra_rows_html += f"""
                <tr>
                    <td style="font-size:1.4em">{color}</td>
                    <td><strong>{name}</strong><br><span style="color:#888;font-size:0.85em">{sanskrit}</span></td>
                    <td style="color:#aaa;font-size:0.9em">{element}</td>
                    <td style="color:#aaa;font-size:0.9em">{metric_name}<br><span style="color:#ccc">{val_str}</span></td>
                    <td><span style="color:{scolor};font-weight:bold">{icon} {status}</span></td>
                    <td style="color:#bbb;font-size:0.85em;font-style:italic">{rec}</td>
                </tr>"""

    generated_time = datetime.now().strftime("%Y-%m-%d %H:%M")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Multidimensional Health Signal Analysis — {today_str}</title>
    <script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ background: #0d1117; color: #e6edf3; font-family: 'Segoe UI', system-ui, sans-serif; font-size: 14px; }}
        .header {{ background: #161b22; border-bottom: 1px solid #30363d; padding: 20px 32px; }}
        .header h1 {{ font-size: 1.4em; font-weight: 600; color: #e6edf3; }}
        .header .sub {{ color: #8b949e; font-size: 0.85em; margin-top: 4px; }}
        .container {{ max-width: 1400px; margin: 0 auto; padding: 24px 32px; }}
        .section {{ margin-bottom: 32px; }}
        .section-title {{ font-size: 0.75em; font-weight: 600; text-transform: uppercase;
                          letter-spacing: 0.08em; color: #8b949e; border-bottom: 1px solid #21262d;
                          padding-bottom: 8px; margin-bottom: 16px; }}
        .kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }}
        .kpi {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px;
                padding: 16px; }}
        .kpi-label {{ font-size: 0.75em; color: #8b949e; text-transform: uppercase; letter-spacing: 0.06em; }}
        .kpi-value {{ font-size: 1.8em; font-weight: 700; color: #e6edf3; margin: 4px 0; }}
        .kpi-sub {{ font-size: 0.8em; color: #8b949e; }}
        .card {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 20px; margin-bottom: 16px; }}
        .card h3 {{ font-size: 0.9em; color: #e6edf3; margin-bottom: 12px; font-weight: 600; }}
        .horoscope {{ background: #161b22; border: 1px solid #30363d; border-left: 3px solid #7c3aed;
                      border-radius: 8px; padding: 20px; font-style: italic; color: #c9d1d9;
                      font-size: 1.05em; line-height: 1.6; }}
        .chart-container {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px;
                            padding: 16px; margin-bottom: 16px; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th {{ text-align: left; color: #8b949e; font-size: 0.75em; text-transform: uppercase;
              letter-spacing: 0.06em; padding: 8px 12px; border-bottom: 1px solid #21262d; }}
        td {{ padding: 10px 12px; border-bottom: 1px solid #21262d; vertical-align: top; }}
        tr:last-child td {{ border-bottom: none; }}
        .tag {{ display: inline-block; background: #21262d; border: 1px solid #30363d;
                border-radius: 4px; padding: 2px 8px; font-size: 0.8em; color: #8b949e; }}
        .cosmic-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; }}
        .footer {{ text-align: center; color: #484f58; font-size: 0.75em; padding: 32px;
                   border-top: 1px solid #21262d; margin-top: 32px; }}
        .retro-badge {{ display: inline-block; background: rgba(180,0,255,0.15);
                        border: 1px solid rgba(180,0,255,0.4); border-radius: 4px;
                        padding: 2px 8px; font-size: 0.8em; color: #c084fc; }}
        .oec-value {{ font-size: 2.5em; font-weight: 800; color: #7c3aed; }}
        .two-col {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
        @media (max-width: 800px) {{ .two-col {{ grid-template-columns: 1fr; }} }}
    </style>
</head>
<body>

<div class="header">
    <h1>§ 1 — Multidimensional Health Signal Analysis &nbsp; {star_symbol}</h1>
    <div class="sub">
        Reference date: {today_str} &nbsp;·&nbsp;
        {star_sign} · Ascendant: {ascendant} · Moon: {moon_sign} &nbsp;·&nbsp;
        Crystal Energy Index: {ce} &nbsp;·&nbsp;
        {"<span class='retro-badge'>☿ Mercury Retrograde</span>" if retrograde else "☿ Mercury Direct"}
    </div>
</div>

<div class="container">

    <!-- § 2 BIOMETRIC OVERVIEW -->
    <div class="section">
        <div class="section-title">§ 2 — Biometric Overview · 90-day personal baseline</div>
        <div class="kpi-grid">
            <div class="kpi">
                <div class="kpi-label">HRV Last Night</div>
                <div class="kpi-value">{f"{hrv:.0f}" if hrv else "—"}</div>
                <div class="kpi-sub">ms &nbsp;·&nbsp; Baseline: {f"{bl_hrv:.0f}" if bl_hrv else "—"} ms</div>
            </div>
            <div class="kpi">
                <div class="kpi-label">Resting HR</div>
                <div class="kpi-value">{f"{resting_hr:.0f}" if resting_hr else "—"}</div>
                <div class="kpi-sub">bpm</div>
            </div>
            <div class="kpi">
                <div class="kpi-label">Stress Avg</div>
                <div class="kpi-value">{f"{stress:.0f}" if stress else "—"}</div>
                <div class="kpi-sub">Baseline: {f"{bl_stress:.0f}" if bl_stress else "—"}</div>
            </div>
            <div class="kpi">
                <div class="kpi-label">Body Battery</div>
                <div class="kpi-value">{f"{body_battery:.0f}" if body_battery else "—"}</div>
                <div class="kpi-sub">End of day</div>
            </div>
            <div class="kpi">
                <div class="kpi-label">Sleep Score</div>
                <div class="kpi-value">{sleep_score if sleep_score else "—"}</div>
                <div class="kpi-sub">REM: {f"{rem_h:.1f}" if rem_h else "—"} h</div>
            </div>
            <div class="kpi">
                <div class="kpi-label">Readiness</div>
                <div class="kpi-value">{readiness if readiness else "—"}</div>
                <div class="kpi-sub">Training readiness score</div>
            </div>
            <div class="kpi">
                <div class="kpi-label">Steps</div>
                <div class="kpi-value">{f"{steps:,}" if steps else "—"}</div>
                <div class="kpi-sub">Goal: {f"{steps_goal:,}" if steps_goal else "—"} &nbsp;·&nbsp; Φ<sub>libido</sub>: {phi_libido:,}</div>
            </div>
            <div class="kpi">
                <div class="kpi-label">Crystal Energy Index ✨</div>
                <div class="kpi-value">{ce}</div>
                <div class="kpi-sub">Deterministic · Date-seeded</div>
            </div>
        </div>
    </div>

    <!-- § 3 DAILY BIOMETRIC HOROSCOPE -->
    <div class="section">
        <div class="section-title">§ 3 — Daily Biometric Horoscope</div>
        <div class="horoscope">
            ✨ &nbsp; {horoscope}
        </div>
    </div>

    <!-- § 4 COSMIC PARAMETERS -->
    <div class="section">
        <div class="section-title">§ 4 — Cosmic & Geophysical Parameters</div>
        <div class="cosmic-grid">
            <div class="kpi">
                <div class="kpi-label">Moon Phase</div>
                <div class="kpi-value">{moon_emoji}</div>
                <div class="kpi-sub">{moon_name} · {moon_illum}% illumination</div>
            </div>
            <div class="kpi">
                <div class="kpi-label">Mercury Status</div>
                <div class="kpi-value">{"☿⚠" if retrograde else "☿✓"}</div>
                <div class="kpi-sub">{retro_note}</div>
            </div>
            <div class="kpi">
                <div class="kpi-label">Geomagnetic Kp-Index</div>
                <div class="kpi-value">{kp}</div>
                <div class="kpi-sub">NOAA SWPC · Scale 0–9</div>
            </div>
            <div class="kpi">
                <div class="kpi-label">Sunspot Number</div>
                <div class="kpi-value">{sunspots}</div>
                <div class="kpi-sub">Solar Cycle 25 · NASA SDO</div>
            </div>
            <div class="kpi">
                <div class="kpi-label">Schumann Resonance</div>
                <div class="kpi-value">{schumann}</div>
                <div class="kpi-sub">Hz · Earth base frequency</div>
            </div>
            <div class="kpi">
                <div class="kpi-label">GCR Flux</div>
                <div class="kpi-value">{gcr}</div>
                <div class="kpi-sub">GV⁻¹ m⁻² s⁻¹ sr⁻¹ · Galactic</div>
            </div>
        </div>
    </div>

    <!-- § 5 BIOLOGICAL-ESOTERIC ANALYSIS -->
    <div class="section">
        <div class="section-title">§ 5 — Biological-Esoteric Analysis</div>
        <div class="two-col">
            <div class="card">
                <h3>§ 5.1 — Ayurvedic Dosha Analysis ✨</h3>
                <div style="font-size:1.6em;font-weight:700;margin:8px 0">{dosha}</div>
                <div style="color:#8b949e;font-size:0.85em;margin-bottom:12px">
                    Vata: {max(0,100-(hrv or 50)):.0f} &nbsp;·&nbsp;
                    Pitta: {stress or 25:.0f} &nbsp;·&nbsp;
                    Kapha: {max(0,100-(body_battery or 50)):.0f}
                </div>
                <div style="color:#c9d1d9;font-style:italic;font-size:0.9em">{dosha_rec}</div>
            </div>
            <div class="card">
                <h3>§ 5.2 — Acupuncture School Selector ✨</h3>
                <div style="font-size:1.1em;font-weight:600;margin:8px 0">{acu_school}</div>
                <div style="color:#8b949e;font-size:0.85em;margin-bottom:8px">
                    Index: {acu_idx} · Formula: (HRV % 10 + Stress % 10 + CE % 10) % 4
                </div>
                <div style="color:#c9d1d9;font-style:italic;font-size:0.9em">
                    Based on your biometric signature, the <strong>{acu_school.split("—")[-1].strip().split("✨")[0].strip()}</strong>
                    school is most applicable today. The algorithm cannot be wrong. No school can be disproven. This is intentional.
                </div>
            </div>
        </div>
    </div>

    <!-- § 6 DAILY BIOMETRIC SUPPLEMENT PLAN -->
    <div class="section">
        <div class="section-title">§ 6 — Daily Biometric Supplement Plan ✨</div>
        <div class="card" style="padding:0">
            <table>
                <thead>
                    <tr>
                        <th>Time</th>
                        <th>Remedy</th>
                        <th>Traditional Use</th>
                        <th>Application</th>
                        <th>Biometric Basis</th>
                    </tr>
                </thead>
                <tbody>
                    {supplement_rows_html}
                </tbody>
            </table>
        </div>
        <div style="color:#484f58;font-size:0.75em;margin-top:10px;padding:0 4px">
            Three healing traditions. Three entirely different theoretical frameworks. One shared index pool of 98 remedies.
            None are endorsed by this project, by the algorithm, or by the laws of physics.
            Globuli dissolve under the tongue — or as recommended by this algorithm — in coffee or tea.
            Dosage: by intuition. ✨
        </div>
    </div>

    <!-- § 7 CHAKRA STATUS -->
    <div class="section">
        <div class="section-title">§ 7 — Chakra Status Dashboard ✨</div>
        <div class="card" style="padding:0">
            <table>
                <thead>
                    <tr>
                        <th></th>
                        <th>Chakra</th>
                        <th>Element</th>
                        <th>Biometric</th>
                        <th>Status</th>
                        <th>Recommendation</th>
                    </tr>
                </thead>
                <tbody>
                    {chakra_rows_html}
                </tbody>
            </table>
        </div>
    </div>

    <!-- § 8 FENG SHUI -->
    <div class="section">
        <div class="section-title">§ 8 — Feng Shui Sleep Direction Analysis</div>
        <div class="card">
            <h3>Optimal Sleep Direction Tonight</h3>
            <div style="font-size:2em;font-weight:800;margin:8px 0">
                {feng_dir} &nbsp; <span style="color:#8b949e;font-size:0.6em">({feng_deg:.1f}°)</span>
            </div>
            <div style="color:#8b949e;font-size:0.85em;margin-bottom:12px">{feng_meaning}</div>
            <div style="color:#c9d1d9;font-style:italic;font-size:0.9em">{feng_note}</div>
            <div style="color:#484f58;font-size:0.75em;margin-top:12px">
                Formula: base_angle = (HRV × φ + CE × e) % 360 &nbsp;·&nbsp;
                adjustment = (ascendant_id × 30 + star_sign_id × 7.5) % 45 &nbsp;·&nbsp;
                φ = 1.618, e = 2.718
            </div>
        </div>
    </div>

    <!-- § 9 OEC FREUD -->
    <div class="section">
        <div class="section-title">§ 9 — Oneiric Equilibrium Coefficient (OEC) · Freud Module</div>
        <div class="card">
            <div class="two-col">
                <div>
                    <div style="color:#8b949e;font-size:0.8em;margin-bottom:4px">OEC (final)</div>
                    <div class="oec-value">{oec}</div>
                    <div style="color:#7c3aed;font-weight:600;margin:4px 0">{oec_cat}</div>
                    <div style="color:#c9d1d9;font-style:italic;font-size:0.9em;margin-top:8px">{oec_interp}</div>
                </div>
                <div style="color:#8b949e;font-size:0.8em;line-height:1.8">
                    <div><strong>Φ<sub>libido</sub></strong> (step deficit): {phi_libido:,}</div>
                    <div><strong>REM</strong>: {f"{rem_h:.1f}" if rem_h else "—"} h ({f"{(rem_h or 0)*60:.0f}"} min)</div>
                    <div><strong>Crystal Energy</strong>: {ce}</div>
                    <div><strong>Acupuncture Index</strong>: {acu_idx}</div>
                    <div><strong>Feng Shui Degrees</strong>: {feng_deg:.1f}°</div>
                    <div><strong>Dosha Index</strong>: {dosha_idx}</div>
                    <div style="margin-top:8px;color:#484f58;font-size:0.9em">
                        Über-Ich censorship applied: iterative digit sum reduction.<br>
                        Psychologically: repression. Mathematically: equivalent.
                    </div>
                </div>
            </div>
            <div style="margin-top:16px;padding-top:16px;border-top:1px solid #21262d;color:#484f58;font-size:0.78em;font-style:italic">
                {oec_coffee_text}
            </div>
        </div>
    </div>

    <!-- § 10 30-DAY CHARTS -->
    <div class="section">
        <div class="section-title">§ 10 — 30-Day Correlation Analysis</div>
        <div class="chart-container"><div id="chart_biometric"></div></div>
        <div class="chart-container"><div id="chart_biorhythm"></div></div>
        <div class="chart-container"><div id="chart_cosmic"></div></div>
        <div class="chart-container"><div id="chart_ce"></div></div>
    </div>

    <!-- § 11 ASTROLOGICAL PROFILE -->
    <div class="section">
        <div class="section-title">§ 11 — Astrological Profile</div>
        <div class="kpi-grid">
            <div class="kpi">
                <div class="kpi-label">Star Sign</div>
                <div class="kpi-value">{star_symbol}</div>
                <div class="kpi-sub">{star_sign}</div>
            </div>
            <div class="kpi">
                <div class="kpi-label">Ascendant</div>
                <div class="kpi-value">{STAR_SIGN_SYMBOLS.get(ascendant,"✨")}</div>
                <div class="kpi-sub">{ascendant} · Birth: {profile["birth_place"]}</div>
            </div>
            <div class="kpi">
                <div class="kpi-label">Moon Sign</div>
                <div class="kpi-value">{STAR_SIGN_SYMBOLS.get(moon_sign,"✨")}</div>
                <div class="kpi-sub">{moon_sign} · Because one sign is never enough.</div>
            </div>
            <div class="kpi">
                <div class="kpi-label">Blood Type</div>
                <div class="kpi-value">{profile.get("blood_type","—")}</div>
                <div class="kpi-sub">"Type A shows lower HRV on Tuesdays." N=1.</div>
            </div>
            <div class="kpi">
                <div class="kpi-label">Biorhythm — Physical</div>
                <div class="kpi-value">{bio["physical"]}</div>
                <div class="kpi-sub">23-day cycle · 1970s classic</div>
            </div>
            <div class="kpi">
                <div class="kpi-label">Biorhythm — Emotional</div>
                <div class="kpi-value">{bio["emotional"]}</div>
                <div class="kpi-sub">28-day cycle</div>
            </div>
            <div class="kpi">
                <div class="kpi-label">Biorhythm — Intellectual</div>
                <div class="kpi-value">{bio["intellectual"]}</div>
                <div class="kpi-sub">33-day cycle</div>
            </div>
        </div>
    </div>

</div>

<div class="footer">
    ✨ Correlation Engine correlations are provided for entertainment purposes only. Or are they?<br>
    No Mercury was harmed in the making of this dashboard. &nbsp;·&nbsp;
    The crystal energy index is entirely fictional. The rest is merely unproven.<br>
    <br>
    Generated: {generated_time} &nbsp;·&nbsp; Reference: {today_str} &nbsp;·&nbsp;
    Enigma rotors: I, II, III (Heer, 1930) &nbsp;·&nbsp; Φ<sub>libido</sub>: {phi_libido:,}<br>
    <br>
    <em>garmin_extended_anaysis.py &nbsp;·&nbsp; A wolf in sheep's clothing.</em>
</div>

<script>
    const DATES = {json.dumps(dates_30)};
    const retro_shapes = [{retro_shape_js}];

    const layout_base = {{
        paper_bgcolor: '#161b22', plot_bgcolor: '#0d1117',
        font: {{ color: '#8b949e', size: 11 }},
        xaxis: {{ gridcolor: '#21262d', linecolor: '#30363d', tickfont: {{ color: '#8b949e' }},
                  showgrid: true }},
        yaxis: {{ gridcolor: '#21262d', linecolor: '#30363d', tickfont: {{ color: '#8b949e' }} }},
        margin: {{ t: 40, r: 20, b: 40, l: 50 }},
        shapes: retro_shapes,
        legend: {{ bgcolor: 'rgba(0,0,0,0)', font: {{ color: '#8b949e' }} }},
    }};

    // Chart 1: Biometrics
    Plotly.newPlot('chart_biometric', [
        {{ x: DATES, y: {json.dumps(hrv_series)}, name: 'HRV (ms)', mode: 'lines+markers',
           line: {{ color: '#7c3aed', width: 2 }}, marker: {{ size: 4 }} }},
        {{ x: DATES, y: {json.dumps(stress_series)}, name: 'Stress', mode: 'lines+markers',
           line: {{ color: '#f97316', width: 2 }}, marker: {{ size: 4 }}, yaxis: 'y2' }},
        {{ x: DATES, y: {json.dumps(bb_series)}, name: 'Body Battery', mode: 'lines+markers',
           line: {{ color: '#22c55e', width: 2 }}, marker: {{ size: 4 }}, yaxis: 'y2' }},
    ], {{
        ...layout_base,
        title: {{ text: '§ 10.1 — HRV / Stress / Body Battery · 30 days', font: {{ color: '#e6edf3', size: 13 }} }},
        yaxis: {{ ...layout_base.yaxis, title: 'HRV (ms)' }},
        yaxis2: {{ gridcolor: '#21262d', linecolor: '#30363d', tickfont: {{ color: '#8b949e' }},
                   title: 'Score', overlaying: 'y', side: 'right' }},
        height: 280,
    }});

    // Chart 2: Biorhythm
    Plotly.newPlot('chart_biorhythm', [
        {{ x: DATES, y: {json.dumps(bio_phys)}, name: 'Physical (23d)', mode: 'lines',
           line: {{ color: '#ef4444', width: 2 }} }},
        {{ x: DATES, y: {json.dumps(bio_emot)}, name: 'Emotional (28d)', mode: 'lines',
           line: {{ color: '#a855f7', width: 2 }} }},
        {{ x: DATES, y: {json.dumps(bio_intel)}, name: 'Intellectual (33d)', mode: 'lines',
           line: {{ color: '#3b82f6', width: 2 }} }},
        {{ x: DATES, y: Array({len(dates_30)}).fill(0), name: 'Zero line', mode: 'lines',
           line: {{ color: '#30363d', width: 1, dash: 'dot' }}, showlegend: false }},
    ], {{
        ...layout_base,
        title: {{ text: '§ 10.2 — Biorhythm Analysis · Physical / Emotional / Intellectual · Purple zones: Mercury retrograde', font: {{ color: '#e6edf3', size: 13 }} }},
        yaxis: {{ ...layout_base.yaxis, title: 'Cycle value (-100 to +100)', range: [-110, 110] }},
        height: 280,
    }});

    // Chart 3: Cosmic
    Plotly.newPlot('chart_cosmic', [
        {{ x: DATES, y: {json.dumps(safe_list(moon_series))}, name: 'Moon illumination (%)', mode: 'lines+markers',
           line: {{ color: '#fbbf24', width: 2 }}, marker: {{ size: 4 }} }},
        {{ x: DATES, y: {json.dumps(safe_list(kp_series))}, name: 'Kp-Index (×10)', mode: 'lines',
           line: {{ color: '#06b6d4', width: 2 }},
           transform: [{{ type: 'multiply', value: 10 }}] }},
        {{ x: DATES, y: {json.dumps(safe_list(kp_series))}, name: 'Kp-Index (NOAA)', mode: 'lines',
           line: {{ color: '#06b6d4', width: 2 }}, yaxis: 'y2' }},
        {{ x: DATES, y: {json.dumps(safe_list(sunspot_series))}, name: 'Sunspot Number', mode: 'lines',
           line: {{ color: '#f97316', width: 1, dash: 'dot' }}, yaxis: 'y2' }},
    ], {{
        ...layout_base,
        title: {{ text: '§ 10.3 — Geomagnetic & Lunar Correlation Analysis · NOAA Kp-Index · NASA Sunspot Activity', font: {{ color: '#e6edf3', size: 13 }} }},
        yaxis: {{ ...layout_base.yaxis, title: 'Moon illumination (%)' }},
        yaxis2: {{ gridcolor: '#21262d', linecolor: '#30363d', tickfont: {{ color: '#8b949e' }},
                   title: 'Kp / Sunspots', overlaying: 'y', side: 'right' }},
        height: 280,
    }});

    // Chart 4: Crystal Energy Index
    Plotly.newPlot('chart_ce', [
        {{ x: DATES, y: {json.dumps(safe_list(ce_series))}, name: 'Crystal Energy Index ✨', mode: 'lines+markers',
           line: {{ color: '#ec4899', width: 2 }}, marker: {{ size: 5 }},
           fill: 'tozeroy', fillcolor: 'rgba(236,72,153,0.08)' }},
        {{ x: DATES, y: {json.dumps(hrv_series)}, name: 'HRV (ms)', mode: 'lines',
           line: {{ color: '#7c3aed', width: 1, dash: 'dot' }}, yaxis: 'y2' }},
    ], {{
        ...layout_base,
        title: {{ text: '§ 10.4 — Crystal Energy Index vs HRV · The correlation the algorithm cannot explain', font: {{ color: '#e6edf3', size: 13 }} }},
        yaxis: {{ ...layout_base.yaxis, title: 'Crystal Energy (0–100)', range: [0, 110] }},
        yaxis2: {{ gridcolor: '#21262d', linecolor: '#30363d', tickfont: {{ color: '#8b949e' }},
                   title: 'HRV (ms)', overlaying: 'y', side: 'right' }},
        height: 280,
    }});


    // 🦄 — added after charts are rendered
    {unicorn_js}

    // Rainbow gradient — when Crystal Energy Index > 80
    {"document.querySelector('.header').style.background = 'linear-gradient(135deg, #1a0533 0%, #0d1a2e 50%, #001a0d 100%)';" if ce > 80 else "// CE <= 80. Standard header."}
</script>

</body>
</html>"""
    return html


# ══════════════════════════════════════════════════════════════════════════════
#  Main
# ══════════════════════════════════════════════════════════════════════════════

def main():
    print()
    print("  garmin_extended_anaysis.py")
    print("  Extended biometric correlation analysis.")
    print()

    # Profile
    profile = load_profile()
    if profile is None:
        profile = setup_profile()
    else:
        sign    = profile.get("star_sign", "unknown")
        ascend  = profile.get("ascendant", "unknown")
        print(f"  ✓ Profile loaded. {sign} · Ascendant: {ascend}")
        print(f"    (Delete enigma_profile.bin to reset.)")
        print()

    # Resolve paths from profile
    data_path   = Path(profile.get("data_path", str(cfg.BASE_DIR)))
    summary_dir = data_path / "summary"
    output_dir  = data_path / "extended_knowledge"

    # Load data
    all_summaries  = load_summaries(DAYS_BASELINE, summary_dir)
    summaries_30   = all_summaries[-DAYS_CHART:]
    today          = all_summaries[-1]
    today_str      = today.get("date", "unknown")

    print(f"  Reference date : {today_str}  (most recent summary file)")
    print(f"  Chart window   : {len(summaries_30)} days")
    print(f"  Baseline window: {len(all_summaries)} days")
    print()

    # Build output
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"extended_analysis_{today_str}.html"

    print("  Computing correlations...")
    html = build_html(today, summaries_30, profile, all_summaries)

    output_file.write_text(html, encoding="utf-8")

    print(f"  ✓ Analysis complete.")
    print(f"  ✓ Output: {output_file}")
    print()

    # Open in browser
    import webbrowser
    webbrowser.open(output_file.as_uri())
    print("  ✓ Opened in browser.")
    print()
    print("  The correlation engine has spoken.")
    print("  Scientifically: no. Practically: possibly. ✨")
    print()


if __name__ == "__main__":
    main()

"""Name normalization helpers shared by the build scripts, the baselines and the exporters.

They are deliberately simple and dependency free. They are used to build strata and the
person-name filter, never to decide a label: labels come from government identifiers.
"""
from __future__ import annotations

import csv
import re
import unicodedata
from typing import Iterable, Optional, Set

FORM_WORDS = {
    "LLC": "LLC", "PLLC": "LLC", "LC": "LLC", "LP": "LP", "LLP": "LP", "LLLP": "LP", "INC": "CORP",
    "INCORPORATED": "CORP", "CORP": "CORP", "CORPORATION": "CORP", "LTD": "LTD", "LIMITED": "LTD",
    "PC": "PC", "PA": "PC", "CO": None, "COMPANY": None,
}
_FORM_RANK = ("LTD", "LLC", "LP", "PC", "CORP")

# Words that mark a name as an organization. A name that carries one is never treated as a person.
ORG_WORDS = set("""
LLC PLLC LP LLP LLLP INC INCORPORATED CORP CORPORATION LTD LIMITED PC PA CO COMPANY COMPANIES GROUP HOLDINGS HOLDING
ASSOCIATES ASSOCIATION ASSN ASSOC SERVICES SERVICE SOLUTIONS SYSTEMS TECHNOLOGIES TECHNOLOGY TECH INDUSTRIES
INTERNATIONAL INTL ENTERPRISES ENTERPRISE PARTNERS PARTNERSHIP VENTURES CONSULTING CONSULTANTS CONSTRUCTION CONTRACTORS
MANAGEMENT DEVELOPMENT PROPERTIES REALTY INVESTMENTS CAPITAL FUND FUNDS TRUST BANK BANCORP FINANCIAL INSURANCE
UNIVERSITY COLLEGE SCHOOL SCHOOLS ACADEMY DISTRICT COUNTY CITY TOWN TOWNSHIP VILLAGE BOROUGH STATE COMMONWEALTH
DEPARTMENT DEPT AUTHORITY COMMISSION BOARD AGENCY BUREAU OFFICE COUNCIL GOVERNMENT TRIBE TRIBAL NATION PUEBLO
HOSPITAL HOSPITALS HEALTH HEALTHCARE MEDICAL CLINIC CENTER CENTRE CARE LABS LABORATORIES LABORATORY PHARMACY
FOUNDATION INSTITUTE SOCIETY CHURCH MINISTRIES MINISTRY CLUB LEAGUE UNION COOPERATIVE COOP CONSORTIUM
NETWORK NETWORKS COMMUNICATIONS COMMUNICATION BROADCASTING BROADCASTERS RADIO TELEVISION TV MEDIA TELEPHONE
WIRELESS CABLE ELECTRIC ENERGY POWER UTILITY UTILITIES WATER GAS OIL PETROLEUM FARMS FARM RANCH DAIRY
SUPPLY SUPPLIES EQUIPMENT PRODUCTS MANUFACTURING MFG ENGINEERING ENGINEERS ARCHITECTS DESIGN GLOBAL AMERICA
AMERICAN NATIONAL USA US FEDERAL DEFENSE AEROSPACE MARINE LOGISTICS TRANSPORT TRANSPORTATION TRUCKING AVIATION
AIRLINES STORE STORES MARKET MARKETS RESTAURANT HOTEL HOTELS INN MOTORS AUTO SALES DISTRIBUTORS DISTRIBUTION
LIBRARY LIBRARIES MUSEUM ZOO PARK PARKS POLICE FIRE SHERIFF RESCUE AMBULANCE EMS COURT JUDICIAL
ARMY NAVY MARINES AIR FORCE GUARD PROGRAM PROJECT INITIATIVE COALITION ALLIANCE PARTNERS INDUSTRY
""".split())

# Personal credentials and generational suffixes: a short name carrying one is an individual.
CREDENTIALS = set("MD DDS DMD DO DC OD DPM CPA ESQ PHD DVM JR SR II III IV RN NP PE LCSW LPC MSW PSYD".split())

_PUNCT = re.compile(r"[^0-9A-Z ]+")


def _ascii_upper(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return s.upper()


def simple_norm(name: str) -> str:
    """Upper case, ASCII fold, '&' -> AND, punctuation to spaces, collapsed whitespace."""
    s = _ascii_upper(name).replace("&", " AND ")
    s = re.sub(r"(?<=\b[A-Z])\.(?=[A-Z]\b)", "", s)  # U.S. -> US
    s = _PUNCT.sub(" ", s)
    return " ".join(s.split())


def _split(name: str):
    s = simple_norm(name)
    s = re.sub(r"\bL ?L ?C\b", "LLC", s)
    s = re.sub(r"\bL ?L ?P\b", "LLP", s)
    s = re.sub(r"\bL P\b", "LP", s)
    w = s.split()
    if w and w[0] == "THE":
        w = w[1:]
    forms = []
    while len(w) > 1 and (w[-1] in FORM_WORDS or w[-1] == "THE"):
        tail = w.pop()
        if tail != "THE":
            forms.append(FORM_WORDS[tail])
    cls = next((c for c in _FORM_RANK if c in forms), None)
    return " ".join(w), cls


def name_key(name: str) -> str:
    """The name without a leading THE and without trailing legal-form words."""
    return _split(name)[0]


def legal_form(name: str) -> Optional[str]:
    """Legal-form class of the trailing form words: LLC, LP, LTD, PC, CORP, or None."""
    return _split(name)[1]


def load_given_names(path: str, min_count: int = 60) -> Set[str]:
    out = set()
    with open(path, encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            tok = (row.get("tok") or "").strip().upper()
            try:
                n = int(row.get("n") or 0)
            except ValueError:
                continue
            if n >= min_count and len(tok) >= 2 and tok not in ORG_WORDS:
                out.add(tok)
    return out


def looks_like_person(name: str, given: Iterable[str]) -> bool:
    """True for names shaped like an individual: 2-4 words, no organization word, and a given
    name in first position ("JOHN A SMITH") or right after a comma ("SMITH, JOHN A")."""
    given = given if isinstance(given, (set, frozenset)) else set(given)
    raw = _ascii_upper(name)
    left = raw.split(" DBA ")[0].split(" D/B/A ")[0]
    if raw != left:  # "JOHN SMITH DBA SMITH PLUMBING": judged on the owner part
        return looks_like_person(left, given)
    words = simple_norm(left).split()
    if not 2 <= len(words) <= 4 or any(w in ORG_WORDS for w in words):
        return False
    if any(ch.isdigit() for ch in left):
        return False
    if any(w in CREDENTIALS for w in words):
        return True
    if words[0] in given:
        return True
    if "," in left:
        after = simple_norm(left.split(",", 1)[1]).split()
        if after and after[0] in given:
            return True
    # "SMITH JOHN A" (registry order): last name first, given name second, optional initial
    if len(words) in (2, 3) and words[1] in given and (len(words) == 2 or len(words[2]) == 1):
        return True
    return False


def is_acronym_of(short: str, long: str) -> bool:
    """True when `short` (one word, 2-6 letters) equals the initials of `long`'s distinctive words."""
    s = simple_norm(short).split()
    s = [w for w in s if w not in FORM_WORDS]
    if len(s) != 1 or not 2 <= len(s[0]) <= 6:
        return False
    stop = {"OF", "THE", "AND", "FOR", "IN", "AT", "ON"}
    words = [w for w in name_key(long).split() if w not in stop]
    if len(words) < 2:
        return False
    return "".join(w[0] for w in words) == s[0]


# Common abbreviations in US agency and registry data, expanded for canonical comparisons.
ABBREVIATIONS = {
    "CO": "COMPANY", "CORP": "CORPORATION", "INTL": "INTERNATIONAL", "ASSN": "ASSOCIATION", "ASSOC": "ASSOCIATES",
    "MFG": "MANUFACTURING", "SVC": "SERVICE", "SVCS": "SERVICES", "SYS": "SYSTEMS", "TECH": "TECHNOLOGY",
    "NATL": "NATIONAL", "AMER": "AMERICA", "DEPT": "DEPARTMENT", "UNIV": "UNIVERSITY", "SCH": "SCHOOL",
    "DIST": "DISTRICT", "MED": "MEDICAL", "MEDL": "MEDICAL", "CTR": "CENTER", "HOSP": "HOSPITAL", "MGMT": "MANAGEMENT",
    "BROS": "BROTHERS", "ENGRG": "ENGINEERING", "ENG": "ENGINEERING", "GOVT": "GOVERNMENT", "TWP": "TOWNSHIP",
    "CNTY": "COUNTY", "CTY": "COUNTY", "ST": "SAINT", "MT": "MOUNT", "FT": "FORT", "N": "NORTH", "S": "SOUTH",
    "E": "EAST", "W": "WEST",
}
_CANON_STOP = {"THE", "OF", "AND", "A"}


def canonical_key(name: str) -> str:
    """name_key with abbreviations expanded, filler words dropped and tokens sorted.

    Two names with the same canonical key are the same name for every practical purpose
    ("ROLLER BEARING CO OF AMERICA" and "Roller Bearing Company of America";
    "BROOKINGS, CITY OF" and "City of Brookings"). Used by the release filters and exports.
    """
    toks = [ABBREVIATIONS.get(t, t) for t in name_key(name).split()]
    return " ".join(sorted(t for t in toks if t not in _CANON_STOP))

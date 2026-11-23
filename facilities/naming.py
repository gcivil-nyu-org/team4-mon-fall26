"""Readable names for NYC Parks facilities.

The city dataset names some fields by their size, for example
"Asser Levy Playground – 45-146ft W x 75-294ft L 1". clean_city_name() puts a
plain label in place of the size and keeps the park and the field number.
"""

import re

SEPARATOR = " – "
# The field number at the end of the name: "1", "1A", "001".
_NUMBER = re.compile(r"^(?P<desc>.*?)\s+(?P<number>\d+[A-Z]?)$")
# Soccer field size classes in the dataset.
_FULL_SIZE_SOCCER = re.compile(r"147-295ft W x 295-393ft L")
_SMALL_SOCCER = re.compile(r"45-146ft W x 75-294ft L|^\d+ ?(\(L\)|L) x \d+ ?(\(W\)|W)")
_BALLFIELD = re.compile(r"\bbase path\b")
_SPORT_LABELS = {
    "soccer": "Soccer field",
    "pickleball": "Pickleball court",
}


def clean_city_name(name, sports=""):
    """The name with a plain label in place of a raw size or "Unknown".

    `sports` is the row's `;`-separated sport names. A name that needs no
    change comes back as is.
    """
    park, separator, rest = name.partition(SEPARATOR)
    match = _NUMBER.match(rest) if separator else None
    if not match:
        return name
    desc, number = match.group("desc"), match.group("number")
    if _FULL_SIZE_SOCCER.search(desc):
        label = "Full-size soccer field"
    elif _SMALL_SOCCER.search(desc):
        label = "Small soccer field"
    elif _BALLFIELD.search(desc):
        label = "Softball field"
    elif desc == "Unknown":
        first_sport = sports.split(";")[0].strip().lower()
        label = _SPORT_LABELS.get(first_sport)
        if not label:
            return name
    else:
        return name
    return f"{park}{SEPARATOR}{label} {number}"

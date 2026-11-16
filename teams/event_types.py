"""The scoring stat of a sport, and the default event types (#254)."""

from django.db import transaction
from django.db.models import Count

from .catalog_rules import name_key
from .models import EventType, Sport

# The name fallback, used only when a sport has no marked scoring stat.
SCORING_NAMES = ("points", "point", "pts", "goal", "goals")

# Keys are name_key(sport name). The first type is the scoring stat when the
# flag is True. A volleyball final score is sets won, so it has no scoring stat.
DEFAULT_EVENT_TYPES = {
    "basketball": (("Points", "Assists", "Rebounds"), True),
    "futsal": (("Goals", "Assists", "Yellow cards"), True),
    "volleyball": (("Kills", "Aces"), False),
}


def pick_scoring_type(event_types):
    """The marked type in event_types, else the first with a scoring name."""
    for event_type in event_types:
        if event_type.is_scoring:
            return event_type
    known = [t for t in event_types if name_key(t.name) in SCORING_NAMES]
    if not known:
        return None
    return min(known, key=lambda t: SCORING_NAMES.index(name_key(t.name)))


def scoring_event_type(sport, event_types=None):
    """The sport's scoring EventType, or None. sport is a Sport or its pk.

    Pass event_types, the sport's loaded EventTypes, to pick from them with
    no query.
    """
    if event_types is not None:
        return pick_scoring_type(list(event_types))
    return pick_scoring_type(
        list(EventType.objects.filter(sport=sport).order_by("name", "pk"))
    )


def create_default_event_types():
    """Add the defaults to each known sport with no event types.

    Return [(sport, [created EventType, ...])], by sport name. A sport with
    any event type is left alone, so a second call creates nothing.
    """
    created = []
    empty = Sport.objects.annotate(type_count=Count("event_types")).filter(type_count=0)
    with transaction.atomic():
        for sport in sorted(empty, key=lambda s: (name_key(s.name), s.pk)):
            defaults = DEFAULT_EVENT_TYPES.get(name_key(sport.name))
            if defaults is None:
                continue
            names, first_scores = defaults
            types = [
                EventType.objects.create(
                    sport=sport, name=name, is_scoring=first_scores and index == 0
                )
                for index, name in enumerate(names)
            ]
            created.append((sport, types))
    return created

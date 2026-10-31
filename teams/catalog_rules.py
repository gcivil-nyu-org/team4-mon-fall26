"""Sport and event-type name rules for E2. The contract is in docs/E2_CONTRACT.md."""

from collections import Counter, defaultdict

from django.core.exceptions import ValidationError

# Matches the legacy sport CharField(max_length=50).
MAX_NAME_LENGTH = 50


def normalize_name(name):
    """Strip the name and collapse any run of whitespace to one space."""
    return " ".join(name.split())


def name_key(name):
    """Key for uniqueness and matching: ignores case and spacing."""
    return normalize_name(name).casefold()


def validate_catalog_name(name):
    """Return the normalized name, or raise ValidationError."""
    name = normalize_name(name)
    if not name:
        raise ValidationError("Enter a name.")
    if len(name) > MAX_NAME_LENGTH:
        raise ValidationError(f"Use {MAX_NAME_LENGTH} characters or fewer.")
    return name


def group_legacy_sports(values):
    """Map each name_key to a display name, skipping blanks.

    The display name is the most common normalized spelling; ties go to the
    alphabetically first spelling.
    """
    spellings = defaultdict(Counter)
    for value in values:
        name = normalize_name(value or "")
        if name:
            spellings[name.casefold()][name] += 1
    return {
        key: min(counts, key=lambda spelling: (-counts[spelling], spelling))
        for key, counts in spellings.items()
    }

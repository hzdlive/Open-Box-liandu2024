"""Core method implementations, one module per family.

Each function takes the method's positional args (a list) and returns
the value for an ok response. Rules are derived from core-golden.json
cases; anything not directly measured is marked INFERRED in
normalize.py and in the README queue notes.
"""

from .normalize import (  # noqa: F401
    normalize_custom,
    normalize_groups,
    normalize_policy,
    normalize_routing,
)
from .tags import builtin_tags  # noqa: F401
from .emit import emit_groups  # noqa: F401
from .plans import (bypass_plan, classes_fn, entry_plan,  # noqa: F401
                    forward_plan)
from .migrate import migrate_stored_routing  # noqa: F401

IMPLEMENTATIONS = {
    "normalizeRouting": normalize_routing,
    "normalizeGroups": normalize_groups,
    "normalizePolicy": normalize_policy,
    "normalizeCustom": normalize_custom,
    "builtinTags": builtin_tags,
    "emitGroups": emit_groups,
    "classes": classes_fn,
    "entryPlan": entry_plan,
    "bypassPlan": bypass_plan,
    "forwardPlan": forward_plan,
    "migrateStoredRouting": migrate_stored_routing,
}

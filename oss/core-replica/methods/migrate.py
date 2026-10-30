"""migrateStoredRouting: stored routing -> {changed, routing}.

Derived from core-golden.json (3 cases, all with changed=false):

- empty ({}), real (a full modern routing: 12 policies + fallback +
  custom), and legacy ({rules: [], final: "direct", groups: [],
  policies: []}) ALL return their input routing structurally
  unchanged with changed=false. The legacy shape's old top-level
  keys (rules/final/groups) are PRESERVED, not rewritten — unlike
  normalizeRouting, this method does not strip or reshape keys.

So the measured behavior is the identity function. What is NOT
measured: no case returns changed=true, so whatever migration
trigger exists for a non-empty legacy payload (if any) is UNPROBED.
This implementation deliberately does not invent one: it returns
the input unchanged with changed=false and documents the gap,
rather than guessing a transformation that could silently corrupt
stored routing. A stored routing with non-empty legacy content is
the case that would discriminate — it needs a new capture before
any migration logic can be written honestly.
"""

import copy


def migrate_stored_routing(args):
    routing = args[0] if len(args) > 0 else None
    return {"changed": False, "routing": copy.deepcopy(routing)}

"""A compact origin for each selected descriptive value, without an event log."""

import json

from stacks.models import now

FIELDS = ("title", "authors", "description")


def origins(work):
    saved = json.loads(work.metadata_origins_json)
    # Existing successor data predates provenance. Conservatively protect it.
    return {field: saved.get(field, {"source": "manual", "protected": True}) for field in FIELDS}


def manual_changes(work, before, after):
    saved = origins(work)
    for field in FIELDS:
        if before[field] != after[field]:
            saved[field] = {"source": "manual", "protected": True, "selected_at": now()}
    work.metadata_origins_json = json.dumps(saved)


def imported(accepted):
    return json.dumps(
        {
            field: {
                "source": "manual" if field in accepted else "embedded",
                "protected": field in accepted,
                "selected_at": now(),
            }
            for field in FIELDS
        }
    )

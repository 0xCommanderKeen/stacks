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
    explicit = accepted.get("manual_fields")
    manual = set(explicit) if explicit is not None else set(accepted)
    return json.dumps(
        {
            field: {
                "source": "manual" if field in manual else "embedded",
                "protected": field in manual,
                "selected_at": now(),
            }
            for field in FIELDS
        }
    )

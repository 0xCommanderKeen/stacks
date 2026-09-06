"""Rebuild disposable thumbnails with one bounded inspector at a time."""

import os

from sqlalchemy import select

from stacks.inspection import inspect_file
from stacks.library import digest, sync_dir, write_durable
from stacks.models import Asset, CoverBlob, Representation, identity


def rebuild(library):
    result = {"rebuilt": 0, "without_cover": 0, "unavailable": 0}

    def publish(relative, content):
        destination = library.managed / relative
        if not destination.resolve().is_relative_to(library.managed.resolve()):
            raise ValueError("Unsafe thumbnail path.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.parent / f".thumbnail-{identity()}"
        try:
            write_durable(temporary, content)
            os.replace(temporary, destination)
            sync_dir(destination.parent)
            sync_dir(library.managed)
        finally:
            temporary.unlink(missing_ok=True)

    with library.ingest_lock:
        for model in (CoverBlob, Representation):
            after = ""
            while True:
                # Keyset pages release the read transaction before inspecting originals.
                with library.sessions() as session:
                    ids = list(
                        session.scalars(
                            select(model.id).where(model.id > after).order_by(model.id).limit(100)
                        )
                    )
                if not ids:
                    break
                for identifier in ids:
                    after = identifier
                    try:
                        cover = None
                        if model is CoverBlob:
                            with library.sessions() as session:
                                blob = session.get(CoverBlob, identifier)
                                original = library.resolve(f".covers/{identifier}/original")
                                expected = blob.sha256
                            if digest(original) != expected:
                                raise ValueError("Chosen cover original failed verification.")
                            cover = inspect_file(original, "__custom_cover__").cover
                            relative = f".covers/{identifier}/thumbnail.jpg"
                        else:
                            relative = f"{identifier}/cover.jpg"
                            position = -1
                            while True:
                                with library.sessions() as session:
                                    asset = session.scalar(
                                        select(Asset)
                                        .where(
                                            Asset.representation_id == identifier,
                                            Asset.position > position,
                                        )
                                        .order_by(Asset.position)
                                        .limit(1)
                                    )
                                    if asset is None:
                                        break
                                    position = asset.position
                                    original = library.resolve_asset(asset)
                                    expected = asset.sha256
                                    name = asset.original_name
                                if digest(original) != expected:
                                    raise ValueError("Publication original failed verification.")
                                cover = inspect_file(original, name).cover
                                if cover:
                                    break
                        if cover:
                            publish(relative, cover)
                            if model is Representation:
                                with library.lock, library.sessions.begin() as session:
                                    session.get(Representation, identifier).cover_path = relative
                            result["rebuilt"] += 1
                        else:
                            result["without_cover"] += 1
                    except (OSError, ValueError):
                        result["unavailable"] += 1
    return result

"""Provider proposals stay separate from selected metadata and manual corrections."""

import json

from sqlalchemy import delete, select

from stacks.library import work_out
from stacks.models import Contributor, Credit, MetadataSuggestion, Work, WorkRedirect, now
from stacks.provenance import origins
from stacks.schemas import MetadataState, SuggestedValues, SuggestionOut, SuggestionPage, WorkEdit


def suggestion_out(suggestion):
    return SuggestionOut(
        id=suggestion.id,
        provider_key=suggestion.provider_key,
        source_url="https://openlibrary.org" + suggestion.provider_key,
        fetched_at=suggestion.fetched_at,
        detailed=suggestion.detailed,
        values=SuggestedValues.model_validate_json(suggestion.values_json),
    )


class Enrichment:
    def __init__(self, library, provider):
        self.library = library
        self.provider = provider

    def _work(self, session, work_id):
        work = session.get(Work, work_id)
        if work is None or session.get(WorkRedirect, work_id):
            raise KeyError(work_id)
        if work.trashed_at:
            raise ValueError("Restore this work before looking up metadata.")
        return work

    def state(self, work_id):
        with self.library.sessions() as session:
            work = self._work(session, work_id)
            return MetadataState(work=work_out(work), origins=origins(work))

    def search(self, work_id, request):
        with self.library.sessions() as session:
            self._work(session, work_id)
        result = self.provider.request(kind="search", q=request.q, offset=request.offset)
        with self.library.lock, self.library.sessions.begin() as session:
            self._work(session, work_id)
            items = []
            for match in result["matches"]:
                suggestion = session.scalar(
                    select(MetadataSuggestion).where(
                        MetadataSuggestion.work_id == work_id,
                        MetadataSuggestion.provider_key == match["key"],
                    )
                )
                values = {"title": match["title"]}
                if match["authors"]:
                    values["authors"] = match["authors"][:20]
                if suggestion is None:
                    suggestion = MetadataSuggestion(
                        work_id=work_id, provider_key=match["key"], values_json="{}"
                    )
                    session.add(suggestion)
                suggestion.values_json = SuggestedValues(**values).model_dump_json(
                    exclude_none=True
                )
                suggestion.fetched_at = now()
                suggestion.detailed = False
                session.flush()
                items.append(suggestion_out(suggestion))
            retained = (
                select(MetadataSuggestion.id)
                .where(MetadataSuggestion.work_id == work_id)
                .order_by(MetadataSuggestion.fetched_at.desc(), MetadataSuggestion.id)
                .limit(20)
            )
            session.execute(
                delete(MetadataSuggestion).where(
                    MetadataSuggestion.work_id == work_id, MetadataSuggestion.id.not_in(retained)
                )
            )
            return SuggestionPage(items=items, total=result["total"], offset=request.offset)

    def details(self, work_id, suggestion_id):
        with self.library.sessions() as session:
            self._work(session, work_id)
            suggestion = session.get(MetadataSuggestion, suggestion_id)
            if suggestion is None or suggestion.work_id != work_id:
                raise KeyError(suggestion_id)
            key = suggestion.provider_key
        result = self.provider.request(kind="details", key=key)
        with self.library.lock, self.library.sessions.begin() as session:
            self._work(session, work_id)
            suggestion = session.get(MetadataSuggestion, suggestion_id)
            if suggestion is None or suggestion.work_id != work_id:
                raise KeyError(suggestion_id)
            values = json.loads(suggestion.values_json)
            if result["description"]:
                values["description"] = result["description"]
            suggestion.values_json = SuggestedValues(**values).model_dump_json(exclude_none=True)
            suggestion.detailed = True
            suggestion.fetched_at = now()
            session.flush()
            return suggestion_out(suggestion)

    def accept(self, work_id, suggestion_id, request):
        with self.library.lock, self.library.sessions.begin() as session:
            work = self._work(session, work_id)
            if work.revision != request.revision:
                raise ValueError("This work changed. Reload the preview before accepting metadata.")
            suggestion = session.get(MetadataSuggestion, suggestion_id)
            if suggestion is None or suggestion.work_id != work_id:
                raise KeyError(suggestion_id)
            if suggestion.fetched_at != request.suggestion_fetched_at:
                raise ValueError("This suggestion changed. Reload the preview before accepting it.")
            proposed = json.loads(suggestion.values_json)
            selected_origins = origins(work)
            for field in request.fields:
                if field not in proposed:
                    raise ValueError("The provider did not suggest that field.")
                if selected_origins[field]["protected"] and field not in request.replace_protected:
                    raise ValueError("Explicitly choose to replace each protected manual value.")
            selected = {
                "title": work.title,
                "authors": [c.contributor.name for c in work.credits],
                "description": work.description,
            }
            selected.update({field: proposed[field] for field in request.fields})
            validated = WorkEdit(revision=work.revision, **selected)
            work.title, work.description = validated.title, validated.description
            if "authors" in request.fields:
                work.credits = [
                    Credit(position=index, contributor=Contributor(name=name))
                    for index, name in enumerate(validated.authors)
                ]
            for field in request.fields:
                selected_origins[field] = {
                    "source": "openlibrary",
                    "protected": False,
                    "provider_key": suggestion.provider_key,
                    "source_url": "https://openlibrary.org" + suggestion.provider_key,
                    "selected_at": now(),
                }
            work.metadata_origins_json = json.dumps(selected_origins)
            work.revision += 1
            session.flush()
            return work_out(work)

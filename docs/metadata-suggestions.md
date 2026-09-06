# Metadata suggestions

Open **Find book details** on a work, enter a title or author, and search Open
Library. Review a match, optionally look up its description, and select the fields
to accept. The preview shows current catalog values alongside the proposal and
links to its source. Searches send the entered query to Open Library; local import
never calls the provider.

Title, authors and description each record the origin of their selected value.
File-derived values start unprotected; explicit intake metadata and later manual
corrections are protected. Existing Stacks data from before field provenance is
conservatively treated as manual. Changing one field does not mark unchanged
fields as manual. Chosen covers remain independent and are never replaced by this
provider.

A protected field is unchecked by default. Selecting it also requires explicit
confirmation to replace protected values. Provider refresh only updates proposals.
Acceptance checks both the work revision and the exact retrieved-proposal token,
so another edit or refreshed proposal requires a new preview. Missing provider
fields are not suggested as empty values. Description lookup can fail while the
already-retrieved title/author proposal remains available.

Grouping carries the origin of each resolved value. If identical values have
different origins, manual protection is retained. Split copies selected origins;
guarded undo preserves them and rejects later selected-value changes. Current
field origins are compact records on Work, not a full edit history. Portable
export and full backup include them. At most 20 recent suggestions per work are
retained as a bounded cache; undo may discard cached proposals when recreating a
work, while selected-value provenance stays in its snapshot.

## Provider boundary

The [Search API](https://openlibrary.org/dev/docs/api/search) supports explicit
fields and offset/limit pagination. Stacks requests five matches with only key,
title and author names, then fetches one selected work record for a description.
It does not request every field or scan the library for bulk enrichment.

Open Library's [API guidance](https://openlibrary.org/developers/api) favors
low-volume human lookup, asks regular clients to identify themselves, and lists a
one-request-per-second default limit. Stacks serializes lookups and observes that
limit. Operators can set `STACKS_PROVIDER_CONTACT` to a contact email for the
User-Agent header; it is configuration, not portable catalog data.

Only fixed HTTPS Open Library endpoints are used. Queries are encoded; work keys
must match the provider's Work-ID shape. Redirects, arbitrary target URLs,
compressed responses, oversized bodies and malformed JSON are rejected. A lookup
has an eight-second socket timeout and a twelve-second subprocess deadline;
responses are limited to 256 KiB, with CPU and Linux memory limits on the process.
No catalog or ingestion lock is held while fetching. Errors leave selected
metadata unchanged and allow a later explicit retry.

On 2026-09-06 the actual bounded implementation returned five matches for the
public query “The Hobbit”. A details request initially failed without affecting
catalog data; a later request succeeded with 775 description characters. This is
connectivity evidence, not a provider uptime guarantee. External content and
private search queries are excluded from committed fixtures.

Backend tests cover malformed/oversized responses, redirects, invalid keys,
partial fields, timeout cleanup, offline import, bounded cached results, manual
protection, stale work/proposal tokens, grouping/split, undo and backup provenance.
Browser tests use a provider fixture at the disposable test-server boundary while
exercising real search storage, preview, pagination, acceptance and manual guards.
They do not depend on an external service during CI.

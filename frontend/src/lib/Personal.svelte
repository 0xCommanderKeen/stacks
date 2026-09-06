<script lang="ts">
  import { untrack } from 'svelte';
  import { json, request, type Book } from './api';
  import type { components } from './schema';
  type RecordItem = components['schemas']['RecordOut'];
  let { book, onupdate }: { book: Book; onupdate: (book: Book) => void } = $props();
  let editing = $state(false);
  let revision = 0;
  let shelf = $state('');
  let notes = $state('');
  let rating = $state('');
  let tags = $state('');
  let busy = $state(false);
  let error = $state('');
  let notice = $state('');
  let history = $state<components['schemas']['RecordPage'] | null>(null);
  let historyOffset = $state(0);
  let recordEditor = $state(false);
  let recordId = $state('');
  let recordRevision = 1;
  let kind = $state<'read' | 'listen'>('read');
  let representation = $state('');
  let started = $state('');
  let finished = $state('');
  const formats = $derived(
    book.editions.flatMap((e) =>
      e.representations.map((r) => ({ ...r, medium: e.medium, narrator: e.narrator })),
    ),
  );
  const eligible = $derived(formats.filter((r) => (r.medium === 'audio') === (kind === 'listen')));
  function edit() {
    revision = book.revision;
    shelf = book.personal.shelf_override || '';
    notes = book.personal.notes;
    rating = book.personal.rating ? String(book.personal.rating) : '';
    tags = (book.personal.tags || []).join(', ');
    editing = true;
    error = '';
  }
  async function action(run: () => Promise<void>) {
    busy = true;
    error = '';
    notice = '';
    try {
      await run();
    } catch (cause) {
      error = String(cause);
    } finally {
      busy = false;
    }
  }
  async function save(event: SubmitEvent) {
    event.preventDefault();
    await action(async () => {
      onupdate(
        await json<Book>(`/works/${book.id}/personal`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            revision,
            shelf_override: shelf || null,
            notes,
            rating: rating ? Number(rating) : null,
            tags: tags.split(','),
          }),
        }),
      );
      editing = false;
      notice = 'Personal details saved.';
    });
  }
  let historySequence = 0;
  async function loadHistory(offset = historyOffset) {
    const sequence = ++historySequence;
    const result = await json<components['schemas']['RecordPage']>(
      `/works/${book.id}/records?limit=5&offset=${offset}`,
    );
    if (sequence !== historySequence) return;
    history = result;
    historyOffset = offset;
  }
  $effect(() => {
    book.id;
    book.revision;
    untrack(() => {
      void loadHistory(0).catch((cause) => (error = String(cause)));
    });
  });
  function editRecord(item?: RecordItem) {
    recordId = item?.id || '';
    recordRevision = item?.revision || 1;
    kind = item?.kind || 'read';
    representation = item?.representation_id || '';
    const today = new Date();
    started =
      item?.started ||
      `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;
    finished = item?.finished || '';
    recordEditor = true;
    error = '';
  }
  async function saveRecord(event: SubmitEvent) {
    event.preventDefault();
    await action(async () => {
      await json(`/works/${book.id}/records${recordId ? '/' + recordId : ''}`, {
        method: recordId ? 'PATCH' : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          revision: recordRevision,
          kind,
          representation_id: representation || null,
          started,
          finished: finished || null,
        }),
      });
      onupdate(await json<Book>(`/works/${book.id}`));
      recordEditor = false;
      await loadHistory(0);
      notice = 'Reading record saved.';
    });
  }
  async function remove(item: RecordItem) {
    await action(async () => {
      await request(`/works/${book.id}/records/${item.id}?revision=${item.revision}`, {
        method: 'DELETE',
      });
      onupdate(await json<Book>(`/works/${book.id}`));
      await loadHistory(Math.max(0, historyOffset - (history?.items.length === 1 ? 5 : 0)));
      notice = 'Reading record removed.';
    });
  }
</script>

<section class="personal" aria-label="Personal library details">
  <div class="section-heading">
    <h2>Your copy, your story</h2>
    <button class="secondary" onclick={edit} disabled={busy}>Edit personal details</button>
  </div>
  {#if error}<p role="alert">{error}</p>{/if}
  {#if notice}<p role="status">{notice}</p>{/if}
  {#if editing}
    <form onsubmit={save}>
      <label
        >Shelf<select bind:value={shelf}
          ><option value="">Use default ({book.personal.default_shelf})</option><option
            value="library">Library</option
          ><option value="archive">Archive</option></select
        ></label
      >
      <label
        >Rating<select bind:value={rating}
          ><option value="">Unrated</option>{#each [1, 2, 3, 4, 5] as n}<option value={String(n)}
              >{n} / 5</option
            >{/each}</select
        ></label
      >
      <label class="wide"
        >Tags, separated by commas<input bind:value={tags} maxlength="10200" /></label
      >
      <label class="wide"
        >Personal notes<textarea bind:value={notes} maxlength="20000" rows="4"></textarea></label
      >
      <div class="actions wide">
        <button class="primary" disabled={busy}>Save personal details</button><button
          type="button"
          onclick={() => (editing = false)}>Cancel</button
        >
      </div>
    </form>
  {:else}
    <p class="personal-summary">
      {book.personal.shelf === 'library' ? 'On your library shelf' : 'In your archive'} · {book
        .personal.shelf_override
        ? 'Your choice'
        : 'Default shelf'}{#if book.personal.rating}{' · '}{book.personal.rating} / 5{/if}
    </p>
    {#if book.personal.tags?.length}<div class="tags">
        {#each book.personal.tags as tag}<span>{tag}</span>{/each}
      </div>{/if}
    {#if book.personal.notes}<p class="notes">{book.personal.notes}</p>{/if}
  {/if}
  <div class="section-heading history-heading">
    <h3>Reading & listening</h3>
    <button class="secondary" onclick={() => editRecord()} disabled={busy}
      >Add reading record</button
    >
  </div>
  <p class="hint">
    Each reading or listening gets its own record. Saved audio position stays with its recording.
  </p>
  {#if recordEditor}
    <form onsubmit={saveRecord}>
      <label
        >Activity<select bind:value={kind} onchange={() => (representation = '')}
          ><option value="read">Reading</option><option value="listen">Listening</option></select
        ></label
      >
      <label
        >Record format<select bind:value={representation}
          ><option value="">Whole work</option>{#each eligible as rep}<option value={rep.id}
              >{rep.format.toUpperCase()}{rep.narrator ? ' · ' + rep.narrator : ''}</option
            >{/each}</select
        ></label
      >
      <label>Started<input type="date" required bind:value={started} /></label>
      <label>Finished (optional)<input type="date" min={started} bind:value={finished} /></label>
      <div class="actions wide">
        <button class="primary" disabled={busy}>Save reading record</button><button
          type="button"
          onclick={() => (recordEditor = false)}>Cancel</button
        >
      </div>
    </form>
  {/if}
  {#if history?.items.length}
    <ol class="history">
      {#each history.items as item}<li>
          <div>
            <strong>{item.kind === 'read' ? 'Reading' : 'Listening'}</strong><span
              >{item.started} → {item.finished || 'In progress'}</span
            ><small
              >{item.representation_id
                ? formats.find((r) => r.id === item.representation_id)?.format.toUpperCase() ||
                  'Format'
                : 'Whole work'}</small
            >
          </div>
          <div class="actions">
            <button
              aria-label="Edit record from {item.started}"
              onclick={() => editRecord(item)}
              disabled={busy}>Edit</button
            ><button
              aria-label="Remove record from {item.started}"
              onclick={() => remove(item)}
              disabled={busy}>Remove</button
            >
          </div>
        </li>{/each}
    </ol>
    {#if history.total > 5}<div class="actions pagination">
        <button
          disabled={busy || historyOffset === 0}
          onclick={() => action(() => loadHistory(historyOffset - 5))}>← Previous records</button
        ><span
          >{historyOffset + 1}–{Math.min(historyOffset + 5, history.total)} of {history.total}</span
        ><button
          disabled={busy || historyOffset + 5 >= history.total}
          onclick={() => action(() => loadHistory(historyOffset + 5))}>Next records →</button
        >
      </div>{/if}
  {:else}<p class="hint">
      No reading records yet. Start a new one whenever you return to this work.
    </p>{/if}
</section>

<style>
  .personal {
    border-top: 1px solid var(--line);
    margin-top: 2rem;
    padding-top: 1.5rem;
  }
  .section-heading {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 1rem;
    flex-wrap: wrap;
  }
  h2,
  h3 {
    font-family: Georgia, serif;
    font-weight: 400;
    margin: 0;
  }
  h2 {
    font-size: 1.7rem;
  }
  h3 {
    font-size: 1.4rem;
  }
  form {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1rem;
    margin: 1.2rem 0;
  }
  label {
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
    font-size: 0.85rem;
    min-width: 0;
  }
  input,
  textarea,
  select {
    font: inherit;
    width: 100%;
    min-width: 0;
    background: #fffdf6;
    color: var(--ink);
    border: 1px solid #adb4a3;
    padding: 0.7rem;
    border-radius: 3px;
  }
  button {
    background: transparent;
    border: 0;
    padding: 0.5rem;
  }
  button.primary {
    background: var(--ink);
    color: var(--paper);
  }
  button.secondary {
    border: 1px solid var(--line);
  }
  .wide {
    grid-column: 1/-1;
  }
  .actions {
    display: flex;
    gap: 0.6rem;
    align-items: center;
    flex-wrap: wrap;
  }
  .personal-summary,
  .hint {
    font-size: 0.9rem;
    color: var(--muted);
    line-height: 1.6;
  }
  .notes {
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    line-height: 1.6;
  }
  .tags {
    display: flex;
    gap: 0.4rem;
    flex-wrap: wrap;
  }
  .tags span {
    background: #e5e6d5;
    border-radius: 3px;
    padding: 0.25rem 0.5rem;
    font-size: 0.8rem;
    overflow-wrap: anywhere;
  }
  .history-heading {
    margin-top: 2rem;
  }
  .history {
    padding: 0;
    list-style: none;
  }
  .history li {
    display: flex;
    gap: 1rem;
    justify-content: space-between;
    flex-wrap: wrap;
    border-bottom: 1px solid var(--line);
    padding: 1rem 0;
  }
  .history li span,
  .history li small {
    display: block;
    margin-top: 0.3rem;
    font-size: 0.85rem;
  }
  [role='alert'] {
    color: #9b482e;
  }
  @media (max-width: 700px) {
    form {
      grid-template-columns: 1fr;
    }
    .section-heading {
      align-items: flex-start;
    }
  }
</style>

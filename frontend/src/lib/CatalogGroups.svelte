<script lang="ts">
  import Cover from './Cover.svelte';
  import { json, type Book, type Page } from './api';
  import type { components } from './schema';
  type Preview = components['schemas']['GroupPreview'];
  type Operation = components['schemas']['OperationOut'];
  let { book, onchange }: { book: Book; onchange: (id: string) => Promise<void> } = $props();
  let expanded = $state(false);
  let mode = $state<'editions' | 'representation' | 'split'>('editions');
  let query = $state('');
  let appliedQuery = '';
  let results = $state<Book[]>([]);
  let total = $state(0);
  let offset = $state(0);
  let target = $state<Book | null>(null);
  let targetEdition = $state('');
  let representation = $state('');
  let preview = $state<Preview | null>(null);
  let resolutions = $state<Record<string, string>>({});
  let history = $state<Operation[]>([]);
  let historyOffset = $state(0);
  let historyTotal = $state(0);
  async function loadHistory(more = false) {
    try {
      const result = await json<components['schemas']['OperationPage']>(
        `/operations?work_id=${encodeURIComponent(book.id)}&offset=${more ? historyOffset : 0}`,
      );
      const items = result.items;
      history = more ? [...history, ...items] : items;
      historyOffset = result.offset + result.items.length;
      historyTotal = result.total;
    } catch (cause) {
      error = String(cause);
    }
  }
  let busy = $state(false);
  let error = $state('');

  async function search(more = false) {
    busy = true;
    error = '';
    try {
      const q = more ? appliedQuery : query;
      const page = await json<Page>(
        `/catalog?q=${encodeURIComponent(q)}&offset=${more ? offset : 0}&limit=24`,
      );
      results = more ? [...results, ...page.items] : page.items;
      offset = page.offset + page.items.length;
      total = page.total;
      appliedQuery = q;
    } catch (cause) {
      error = String(cause);
    } finally {
      busy = false;
    }
  }
  async function show() {
    expanded = !expanded;
    if (expanded) await loadHistory();
  }

  function describe(item: Book) {
    return item.editions
      .map((e) =>
        [
          e.language || 'Unknown language',
          e.narrator,
          e.abridgement !== 'unknown' ? e.abridgement : '',
          e.representations.map((r) => r.format.toUpperCase()).join('/'),
        ]
          .filter(Boolean)
          .join(' · '),
      )
      .join('; ');
  }
  async function makePreview() {
    busy = true;
    error = '';
    preview = null;
    try {
      preview = await json<Preview>('/operations/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          mode,
          source_work_id: book.id,
          target_work_id: mode === 'split' ? null : target?.id,
          representation_id: representation || null,
          target_edition_id: targetEdition || null,
        }),
      });
      resolutions = {};
    } catch (cause) {
      error = String(cause);
    } finally {
      busy = false;
    }
  }
  async function apply() {
    if (!preview) return;
    busy = true;
    error = '';
    try {
      const result = await json<Operation>(`/operations/${preview.id}/commit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ resolutions }),
      });
      preview = null;
      expanded = false;
      await onchange(result.work_ids[1]);
    } catch (cause) {
      error = String(cause);
    } finally {
      busy = false;
    }
  }
  async function undo(operation: Operation) {
    busy = true;
    error = '';
    try {
      await json<Operation>(`/operations/${operation.id}/undo`, { method: 'POST' });
      expanded = false;
      await onchange(operation.work_ids[0]);
    } catch (cause) {
      error = String(cause);
    } finally {
      busy = false;
    }
  }
</script>

<section class="groups">
  <button class="secondary" onclick={show}>Group or separate formats</button>
  {#if error}<p class="error" role="alert">{error}</p>{/if}
  {#if expanded}
    <h2>One book, several ways to read.</h2>
    <p>
      Keep recordings and translations as separate editions. Combine formats within one edition only
      when you know their content is equivalent.
    </p>
    {#if preview}
      <section class="preview" aria-label="Grouping preview">
        <h3>{preview.mode === 'split' ? 'Separate this format' : 'Review grouping'}</h3>
        <p>{preview.explanation}</p>
        <p><strong>{preview.source.title}</strong><br />{describe(preview.source)}</p>
        {#if preview.target}<p>
            Into <strong>{preview.target.title}</strong><br />{describe(preview.target)}
          </p>{/if}
        {#each preview.conflicts as conflict}
          {#if conflict.field === 'selected_cover_id' && preview.target}
            <div class="cover-comparison">
              <figure>
                <Cover book={preview.source} />
                <figcaption>Source</figcaption>
              </figure>
              <figure>
                <Cover book={preview.target} />
                <figcaption>Target</figcaption>
              </figure>
            </div>
          {/if}
          <label
            >{conflict.field.startsWith('personal:')
              ? 'Personal ' + conflict.field.slice(9)
              : conflict.field === 'selected_cover_id'
                ? 'Chosen cover'
                : conflict.field}<select bind:value={resolutions[conflict.field]}
              ><option value="">Choose which to keep</option><option value="target"
                >Keep target: {conflict.target}</option
              ><option value="source">Keep source: {conflict.source}</option></select
            ></label
          >
        {/each}
        <p class="small muted">
          Original values remain in the undo record. Files and saved reading positions stay attached
          to their formats.
        </p>
        <div class="actions">
          <button
            class="primary"
            disabled={busy || preview.conflicts.some((c) => !resolutions[c.field])}
            onclick={apply}>Confirm {preview.mode === 'split' ? 'split' : 'grouping'}</button
          ><button class="secondary" onclick={() => (preview = null)}>Back to choices</button>
        </div>
      </section>
    {:else}
      <label
        >Action<select bind:value={mode}
          ><option value="editions">Group as separate editions</option><option
            value="representation">Attach a format to the same edition</option
          ><option value="split">Separate a format into its own book</option></select
        ></label
      >
      {#if mode !== 'editions'}
        <label
          >Format to move<select bind:value={representation}
            ><option value="">Choose a format</option
            >{#each book.editions as edition}{#each edition.representations as rep}<option
                  value={rep.id}
                  >{rep.format.toUpperCase()} · {edition.language || 'Unknown language'} · {rep
                    .assets[0]?.original_name}</option
                >{/each}{/each}</select
          ></label
        >
      {/if}
      {#if mode !== 'split'}
        <label>Find the target book<input bind:value={query} maxlength="300" /></label>
        <button class="secondary" disabled={busy} onclick={() => search()}>Find target</button>
        <div class="matches">
          {#each results.filter((b) => b.id !== book.id) as item}<button
              class="match"
              class:chosen={target?.id === item.id}
              onclick={() => {
                target = item;
                targetEdition = item.editions[0]?.id || '';
              }}><strong>{item.title}</strong><small>{describe(item)}</small></button
            >{/each}
        </div>
        {#if offset < total}<button class="secondary" disabled={busy} onclick={() => search(true)}
            >More results</button
          >{/if}
        {#if target}<p>Selected: <strong>{target.title}</strong></p>{/if}
        {#if mode === 'representation' && target}<label
            >Target edition<select bind:value={targetEdition}
              >{#each target.editions as edition}<option value={edition.id}
                  >{edition.medium} · {edition.language || 'Unknown language'} · {edition.narrator ||
                    edition.publisher ||
                    edition.id.slice(0, 8)}</option
                >{/each}</select
            ></label
          >{/if}
      {/if}
      <button
        class="primary"
        disabled={busy || (mode !== 'split' && !target) || (mode !== 'editions' && !representation)}
        onclick={makePreview}>Preview changes</button
      >
    {/if}
    {#if history.length}<h3>Recent catalog changes</h3>
      {#each history as operation}<div class="operation">
          <span>{new Date(operation.created_at).toLocaleString()} · {operation.state}</span
          >{#if operation.state === 'applied'}<button
              class="secondary"
              disabled={busy}
              onclick={() => undo(operation)}>Undo grouping or split</button
            >{/if}
        </div>{/each}{/if}
    {#if historyOffset < historyTotal}<button class="secondary" onclick={() => loadHistory(true)}
        >More catalog changes</button
      >{/if}
  {/if}
</section>

<style>
  .cover-comparison {
    display: flex;
    gap: 1.5rem;
    margin: 1rem 0;
  }
  .cover-comparison figure {
    width: 100px;
    margin: 0;
  }
  figcaption {
    font-size: 0.8rem;
    margin-top: 0.5rem;
  }
  .groups {
    margin: 1.5rem 0;
    padding: 1.5rem 0;
    border-top: 1px solid #cfcabd;
  }
  h2 {
    font-family: Georgia, serif;
    font-size: 1.5rem;
    font-weight: normal;
  }
  label {
    display: block;
    margin: 1rem 0;
  }
  input,
  select {
    display: block;
    width: 100%;
    box-sizing: border-box;
    font: inherit;
    color: inherit;
    background: #fffcf5;
    border: 1px solid #cfcabd;
    padding: 0.6rem;
  }
  .matches {
    display: grid;
    gap: 0.5rem;
    margin: 1rem 0;
  }
  .match {
    text-align: left;
    padding: 0.8rem;
    border: 1px solid #cfcabd;
  }
  .match small {
    display: block;
    margin-top: 0.3rem;
  }
  .chosen {
    outline: 2px solid #344c40;
  }
  .preview {
    border-left: 3px solid #344c40;
    padding-left: 1rem;
  }
  .operation {
    display: flex;
    flex-wrap: wrap;
    gap: 0.6rem;
    align-items: center;
    margin: 0.8rem 0;
  }
</style>

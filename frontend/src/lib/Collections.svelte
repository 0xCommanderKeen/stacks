<script lang="ts">
  import { untrack } from 'svelte';
  import Cover from './Cover.svelte';
  import { json, type Book, type Page } from './api';
  import type { components } from './schema';
  type Collection = components['schemas']['CollectionOut'];
  type Contents = components['schemas']['CollectionWorksPage'];
  let {
    id = $bindable(''),
    offset = $bindable(0),
    listOffset = $bindable(0),
    onopen,
    onnavigate,
  }: {
    id: string;
    offset: number;
    listOffset: number;
    onopen: (book: Book) => void;
    onnavigate: () => void;
  } = $props();
  let listing = $state<components['schemas']['CollectionPage'] | null>(null);
  let page = $state<Contents | null>(null);
  let name = $state('');
  let home = $state(false);
  let error = $state('');
  let busy = $state(false);
  let query = $state('');
  let searchOffset = $state(0);
  let searchType = $state<'works' | 'series'>('works');
  let results = $state<Page | null>(null);
  let runs = $state<components['schemas']['SeriesPage'] | null>(null);
  let sequence = 0;
  let searchSequence = 0;
  async function load() {
    const current = ++sequence;
    error = '';
    try {
      if (id) {
        const result = await json<Contents>(`/collections/${id}/works?offset=${offset}`);
        if (current !== sequence) return;
        page = result;
        name = result.collection.name;
        home = result.collection.home;
        if (!result.items.length && offset > 0) {
          offset = result.total ? Math.floor((result.total - 1) / 24) * 24 : 0;
          onnavigate();
        }
      } else {
        const result = await json<components['schemas']['CollectionPage']>(
          `/collections?offset=${listOffset}`,
        );
        if (current !== sequence) return;
        listing = result;
        page = null;

        if (!result.items.length && listOffset > 0) {
          listOffset = result.total ? Math.floor((result.total - 1) / 24) * 24 : 0;
          onnavigate();
        }
      }
    } catch (cause) {
      if (current === sequence) error = String(cause);
    }
  }
  $effect(() => {
    id;
    offset;
    listOffset;
    untrack(() => {
      void load();
    });
  });
  function choose(next: string) {
    id = next;
    page = null;
    name = '';
    home = false;
    offset = 0;
    results = null;
    runs = null;
    query = '';
    searchSequence++;
    onnavigate();
  }
  async function save(event: SubmitEvent) {
    event.preventDefault();
    busy = true;
    error = '';
    const target = id;
    try {
      const result = await json<Collection>(`/collections${target ? '/' + target : ''}`, {
        method: target ? 'PATCH' : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, home, revision: page?.collection.revision || 1 }),
      });
      if (id !== target) return;
      if (!target) choose(result.id);
      else await load();
    } catch (cause) {
      error = String(cause);
    } finally {
      busy = false;
    }
  }
  async function change(
    action: components['schemas']['CollectionChange']['action'],
    workId?: string,
    seriesId?: string,
  ) {
    if (!page || busy) return;
    busy = true;
    error = '';
    const target = id;
    try {
      await json<Collection>(`/collections/${target}/entries`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          revision: page.collection.revision,
          action,
          work_id: workId,
          series_id: seriesId,
        }),
      });
      if (target === id) await load();
    } catch (cause) {
      error = String(cause);
    } finally {
      busy = false;
    }
  }
  async function search(next = 0) {
    const current = ++searchSequence;
    error = '';
    try {
      const path = searchType === 'works' ? 'catalog' : 'series';
      const result = await json<Page | components['schemas']['SeriesPage']>(
        `/${path}?q=${encodeURIComponent(query)}&limit=6&offset=${next}`,
      );
      if (current !== searchSequence) return;
      searchOffset = next;
      if (searchType === 'works') {
        results = result as Page;
        runs = null;
      } else {
        runs = result as components['schemas']['SeriesPage'];
        results = null;
      }
    } catch (cause) {
      if (current === searchSequence) error = String(cause);
    }
  }
  let searchTotal = $derived(results?.total ?? runs?.total ?? 0);
</script>

<div class="eyebrow">YOUR OWN READING ORDER</div>
{#if id}
  <button class="back" onclick={() => choose('')}>← All collections</button>
  <h1>{page?.collection.name || 'Opening collection…'}</h1>
{:else}
  <h1>A shelf for <em>every mood.</em></h1>
  <p class="intro">Bring books, comics, and audiobooks together in the order you choose.</p>
{/if}
{#if error}<p role="alert">{error} <button onclick={load}>Reload collection</button></p>{/if}
<form class="collection-form" onsubmit={save}>
  <label
    >{id ? 'Collection name' : 'New collection name'}<input
      bind:value={name}
      required
      maxlength="1024"
    /></label
  >
  <label class="check"
    ><input type="checkbox" bind:checked={home} /> Show next unfinished Library work on Home</label
  >
  <button class="primary" disabled={busy || (!!id && !page)}
    >{id ? 'Save collection' : 'Create collection'}</button
  >
</form>
{#if id && page}
  <section aria-label="Collection contents">
    <div class="section-top">
      <h2>{page.total} {page.total === 1 ? 'work' : 'works'}, your order.</h2>
      <span>Move entries one place at a time, including between pages.</span>
    </div>
    {#each page.items as item, index (item.id)}
      <div class="entry">
        <span class="ordinal">{offset + index + 1}</span>
        <button
          class="open"
          onclick={() => onopen(item.work)}
          aria-label={`Open ${item.work.title}`}
          ><div class="cover"><Cover book={item.work} /></div>
          <span
            ><strong>{item.work.title}</strong><small>{item.work.authors.join(', ')}</small><small
              >{item.work.editions
                .map((e) => e.medium)
                .filter((v, i, a) => a.indexOf(v) === i)
                .join(' · ')}{item.finished ? ' · Finished' : ''}</small
            ></span
          ></button
        >
        <div class="order-controls">
          <button
            disabled={busy || offset + index === 0}
            aria-label={`Move ${item.work.title} up`}
            onclick={() => change('up', item.work.id)}>↑</button
          >
          <button
            disabled={busy || offset + index + 1 === page!.total}
            aria-label={`Move ${item.work.title} down`}
            onclick={() => change('down', item.work.id)}>↓</button
          >
          <button
            disabled={busy}
            aria-label={`Remove ${item.work.title} from collection`}
            onclick={() => change('remove', item.work.id)}>Remove</button
          >
        </div>
      </div>
    {:else}<p class="empty-copy">
        Start with one book. Build a reading order that feels like yours.
      </p>{/each}
    {#if page.total > 24}<div class="pagination">
        <button
          disabled={offset === 0 || busy}
          onclick={() => {
            offset -= 24;
            onnavigate();
          }}>← Previous works</button
        ><span>{offset + 1}–{Math.min(offset + 24, page.total)} of {page.total}</span><button
          disabled={offset + 24 >= page.total || busy}
          onclick={() => {
            offset += 24;
            onnavigate();
          }}>Next works →</button
        >
      </div>{/if}
  </section>
  <section class="add" aria-label="Add to collection">
    <h2>What belongs here?</h2>
    <form
      onsubmit={(event) => {
        event.preventDefault();
        void search();
      }}
    >
      <label
        >Find<select
          bind:value={searchType}
          onchange={() => {
            results = null;
            runs = null;
            searchSequence++;
          }}
          ><option value="works">Books, comics, and audio</option><option value="series"
            >A whole owned series</option
          ></select
        ></label
      >
      <label>Search your library<input bind:value={query} type="search" /></label><button
        class="secondary">Search to add</button
      >
    </form>
    {#if searchType === 'series'}<p>
        Appends currently owned works in series order. Existing entries keep their place; future
        imports can be added later.
      </p>{/if}
    {#each results?.items || [] as work}<div class="result">
        <span>{work.title}</span><button
          disabled={busy}
          onclick={() => change('add', work.id)}
          aria-label={`Add ${work.title} to collection`}>Add</button
        >
      </div>{/each}
    {#each runs?.items || [] as run}<div class="result">
        <span>{run.name} · {run.run}</span><button
          disabled={busy}
          onclick={() => change('add_series', undefined, run.id)}
          aria-label={`Add series ${run.name} ${run.run}`}>Add owned works</button
        >
      </div>{/each}
    {#if (results || runs) && !searchTotal}<p>No matches.</p>{/if}
    {#if searchTotal > 6}<div class="pagination">
        <button disabled={searchOffset === 0} onclick={() => search(searchOffset - 6)}
          >← Previous matches</button
        ><span>{searchOffset + 1}–{Math.min(searchOffset + 6, searchTotal)} of {searchTotal}</span
        ><button disabled={searchOffset + 6 >= searchTotal} onclick={() => search(searchOffset + 6)}
          >Next matches →</button
        >
      </div>{/if}
  </section>
{:else if !id}
  <div class="collection-grid">
    {#each listing?.items || [] as collection}<button
        class="collection-card"
        onclick={() => choose(collection.id)}
        ><span class="eyebrow">{collection.count} WORKS {collection.home ? '· ON HOME' : ''}</span>
        <h2>{collection.name}</h2>
        <span>Open collection ↗</span></button
      >{/each}
  </div>
  {#if listing && listing.total > 24}<div class="pagination">
      <button
        disabled={listOffset === 0}
        onclick={() => {
          listOffset -= 24;
          onnavigate();
        }}>← Previous collections</button
      ><span>{listOffset + 1}–{Math.min(listOffset + 24, listing.total)} of {listing.total}</span
      ><button
        disabled={listOffset + 24 >= listing.total}
        onclick={() => {
          listOffset += 24;
          onnavigate();
        }}>Next collections →</button
      >
    </div>{/if}
{/if}

<style>
  h1 {
    overflow-wrap: anywhere;
  }
  h2 {
    font:
      400 1.8rem Georgia,
      serif;
  }
  button {
    font: inherit;
  }
  .collection-form {
    display: flex;
    flex-wrap: wrap;
    align-items: end;
    gap: 1.2rem;
    padding: 1.5rem 0 2rem;
    border-bottom: 1px solid var(--line);
  }
  label {
    display: grid;
    gap: 0.5rem;
    font-size: 0.85rem;
  }
  label.check {
    display: flex;
    align-items: center;
    max-width: 22rem;
    line-height: 1.5;
  }
  input:not([type='checkbox']),
  select {
    min-width: 0;
    width: 100%;
    padding: 0.8rem;
    border: 1px solid var(--line);
    background: transparent;
    font: inherit;
  }
  input[type='checkbox'] {
    width: 1.1rem;
    height: 1.1rem;
    flex-shrink: 0;
  }
  .collection-form > label:first-child {
    flex: 1;
    min-width: 12rem;
  }
  .section-top {
    margin-top: 2rem;
  }
  .section-top > span,
  .empty-copy,
  .add p {
    color: var(--muted);
    line-height: 1.6;
  }
  .entry {
    display: flex;
    align-items: center;
    gap: 1rem;
    padding: 1rem 0;
    border-bottom: 1px solid var(--line);
  }
  .ordinal {
    font-family: Georgia, serif;
    color: var(--muted);
    width: 2rem;
    flex-shrink: 0;
  }
  .open {
    display: flex;
    gap: 1rem;
    align-items: center;
    border: 0;
    background: transparent;
    padding: 0;
    text-align: left;
    flex: 1;
    min-width: 0;
  }
  .cover {
    width: 3.5rem;
    flex-shrink: 0;
  }
  strong {
    overflow-wrap: anywhere;
  }
  small {
    display: block;
    color: var(--muted);
    margin-top: 0.4rem;
  }
  .order-controls {
    display: flex;
    gap: 0.35rem;
  }
  .order-controls button,
  .result button {
    background: transparent;
    border: 1px solid var(--line);
    padding: 0.6rem;
    min-height: 44px;
  }
  .add {
    margin-top: 3rem;
    max-width: 60rem;
  }
  .add form {
    display: flex;
    gap: 1rem;
    flex-wrap: wrap;
    align-items: end;
  }
  .add form label:nth-child(2) {
    flex: 1;
    min-width: 12rem;
  }
  .result {
    display: flex;
    gap: 1rem;
    justify-content: space-between;
    align-items: center;
    padding: 0.8rem 0;
    border-bottom: 1px solid var(--line);
  }
  .collection-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
    gap: 1.5rem;
    margin-top: 2rem;
  }
  .collection-card {
    padding: 1.5rem;
    background: #ebe9de;
    border: 1px solid var(--line);
    text-align: left;
    overflow-wrap: anywhere;
  }
  [role='alert'] {
    color: #9b482e;
  }
  .back {
    margin-top: 1rem;
  }
  @media (max-width: 600px) {
    .entry {
      flex-wrap: wrap;
      gap: 0.7rem;
    }
    .order-controls {
      margin-left: 2.7rem;
      width: 100%;
    }
    .order-controls button {
      flex: 1;
    }
    .collection-form > button {
      width: 100%;
    }
  }
</style>

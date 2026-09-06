<script lang="ts">
  import { onMount } from 'svelte';
  import { json, type Book } from './api';
  import type { components } from './schema';
  import TrashAction from './TrashAction.svelte';
  let {
    query = $bindable(''),
    offset = $bindable(0),
    onopen,
    onnavigate,
  }: {
    query: string;
    offset: number;
    onopen: (book: Book) => void;
    onnavigate: () => void;
  } = $props();
  let typed = $state(query);
  let page = $state<components['schemas']['TrashPage'] | null>(null);
  let error = $state('');
  let active = $state(false);
  let sequence = 0;
  let controller: AbortController | undefined;
  let timer: ReturnType<typeof setTimeout> | undefined;
  $effect(() => {
    const q = query;
    const start = offset;
    if (active) {
      typed = q;
      page = null;
      void load(q, start);
    }
  });
  onMount(() => {
    active = true;
    return () => {
      active = false;
      sequence++;
      controller?.abort();
      clearTimeout(timer);
    };
  });
  async function load(q = query, start = offset) {
    clearTimeout(timer);
    controller?.abort();
    controller = new AbortController();
    const current = ++sequence;
    try {
      const result = await json<components['schemas']['TrashPage']>(
        `/trash?q=${encodeURIComponent(q)}&limit=12&offset=${start}`,
        { signal: controller.signal },
      );
      if (!active || current !== sequence) return;
      if (!result.items.length && start > 0) {
        offset = result.total ? Math.floor((result.total - 1) / 12) * 12 : 0;
        onnavigate();
        return;
      }
      page = result;
    } catch (cause) {
      if (active && current === sequence && !controller.signal.aborted) error = String(cause);
    } finally {
      if (active && current === sequence) timer = setTimeout(() => load(), 2000);
    }
  }
</script>

<div class="eyebrow">KEPT FOR RECOVERY</div>
<h1>Trash.</h1>
<p class="intro">A place to reconsider. Originals and your reading history remain recoverable.</p>
<form
  onsubmit={(event) => {
    event.preventDefault();
    query = typed;
    offset = 0;
    onnavigate();
  }}
>
  <label>Search Trash<input bind:value={typed} maxlength="300" placeholder="A book title" /></label>
  <button class="primary">Search Trash</button>
</form>
{#if error}<p class="error" role="alert">{error}</p>{/if}
{#if page}
  <p class="count">{page.total} books in Trash</p>
  <div class="entries">
    {#each page.items as item (item.work.id)}
      <article>
        <button class="title" onclick={() => onopen(item.work)}>{item.work.title}</button>
        <p class="byline">{item.work.authors.join(' · ') || 'Unknown author'}</p>
        <TrashAction
          book={item.work}
          onupdate={() => {
            void load();
          }}
        />
      </article>
    {:else}<p>Trash is empty. Books you remove will appear here until you restore them.</p>{/each}
  </div>
  {#if page.total > 12}<div class="pagination">
      <button
        class="secondary"
        disabled={offset === 0}
        onclick={() => {
          offset -= 12;
          onnavigate();
        }}>Previous trashed books</button
      >
      <span>{offset + 1}–{Math.min(offset + 12, page.total)} of {page.total}</span>
      <button
        class="secondary"
        disabled={offset + 12 >= page.total}
        onclick={() => {
          offset += 12;
          onnavigate();
        }}>Next trashed books</button
      >
    </div>{/if}
{:else}<p aria-live="polite">Loading Trash…</p>{/if}

<style>
  form {
    display: flex;
    align-items: end;
    gap: 1rem;
    margin: 2rem 0;
  }
  label {
    flex: 1;
    display: grid;
    gap: 0.5rem;
    font-size: 0.85rem;
  }
  input {
    width: 100%;
    min-width: 0;
    padding: 0.8rem;
    font: inherit;
    color: inherit;
    background: transparent;
    border: 1px solid var(--line);
  }
  .entries {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 1.5rem;
  }
  article {
    border: 1px solid var(--line);
    padding: 1.5rem;
    min-width: 0;
  }
  .title {
    padding: 0;
    border: 0;
    background: none;
    text-align: left;
    font-size: 1.2rem;
    color: var(--ink);
    overflow-wrap: anywhere;
  }
  .byline,
  .count {
    color: var(--muted);
    font-size: 0.9rem;
  }
  .pagination {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 1rem;
    margin: 2rem 0;
  }
  .error {
    color: #a33129;
  }
  @media (max-width: 650px) {
    .entries {
      grid-template-columns: 1fr;
    }
    form {
      flex-direction: column;
      align-items: stretch;
    }
    .pagination {
      flex-wrap: wrap;
    }
  }
</style>

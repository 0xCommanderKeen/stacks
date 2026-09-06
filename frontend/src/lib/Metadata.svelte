<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { json, type Book } from './api';
  import type { components } from './schema';
  type State = components['schemas']['MetadataState'];
  type Page = components['schemas']['SuggestionPage'];
  type Suggestion = components['schemas']['SuggestionOut'];
  type Field = 'title' | 'authors' | 'description';
  let { book, onupdate }: { book: Book; onupdate: (book: Book) => void } = $props();
  let q = $state('');
  onMount(() => {
    q = book.title.slice(0, 300);
  });
  let appliedQuery = '';
  let page = $state<Page | null>(null);
  let metadataState = $state<State | null>(null);
  let selected = $state<Suggestion | null>(null);
  let fields = $state<Field[]>([]);
  let replaceProtected = $state(false);
  let busy = $state(false);
  let error = $state('');
  let active = true;
  const names: Field[] = ['title', 'authors', 'description'];
  const protectedFields = $derived(
    fields.filter((field) => metadataState?.origins[field]?.protected),
  );
  onDestroy(() => {
    active = false;
  });
  async function run(action: () => Promise<void>) {
    busy = true;
    error = '';
    try {
      await action();
    } catch (cause) {
      if (active) error = String(cause);
    } finally {
      if (active) busy = false;
    }
  }
  async function loadState() {
    const value = await json<State>(`/works/${book.id}/metadata`);
    if (active) metadataState = value;
  }
  function search(event?: SubmitEvent, offset = 0) {
    event?.preventDefault();
    void run(async () => {
      await loadState();
      const query = event ? q.trim() : appliedQuery;
      const result = await json<Page>(`/works/${book.id}/metadata/search`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ q: query, offset }),
      });
      if (active) {
        appliedQuery = query;
        page = result;
        selected = null;
      }
    });
  }
  function select(item: Suggestion) {
    selected = item;
    fields = names.filter(
      (field) => item.values[field] != null && !metadataState?.origins[field]?.protected,
    );
    replaceProtected = false;
  }
  function details() {
    if (!selected) return;
    const id = selected.id;
    void run(async () => {
      const value = await json<Suggestion>(`/works/${book.id}/metadata/${id}/details`, {
        method: 'POST',
      });
      if (active) select(value);
    });
  }
  function accept() {
    if (!selected || !metadataState) return;
    const id = selected.id;
    const body = {
      revision: metadataState.work.revision,
      suggestion_fetched_at: selected.fetched_at,
      fields,
      replace_protected: replaceProtected ? protectedFields : [],
    };
    void run(async () => {
      const value = await json<Book>(`/works/${book.id}/metadata/${id}/accept`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (active) {
        selected = null;
        onupdate(value);
        await loadState();
      }
    });
  }
  function display(value: string | string[] | null | undefined) {
    return Array.isArray(value) ? value.join(', ') : value || 'No value';
  }
</script>

<details
  class="metadata"
  ontoggle={(event) => {
    if (event.currentTarget.open && !metadataState) void run(loadState);
  }}
>
  <summary>Find book details</summary>
  <p>
    Look up a title or author on Open Library, then choose the fields to use. Your search query is
    sent to Open Library.
  </p>
  {#if error}<p role="alert">{error}</p>{/if}
  <form onsubmit={search}>
    <label for="metadata-query">Title or author to look up</label>
    <div class="lookup">
      <input id="metadata-query" bind:value={q} maxlength="300" required disabled={busy} /><button
        class="secondary"
        disabled={busy || !q.trim()}>Search Open Library</button
      >
    </div>
  </form>
  {#if metadataState}
    <p class="origins">
      Current sources: {#each names as field, index}{index ? ' · ' : ''}{field}: {metadataState
          .origins[field]?.source === 'openlibrary'
          ? 'Open Library'
          : metadataState.origins[field]?.source === 'embedded'
            ? 'file metadata'
            : 'your choice'}{/each}
    </p>
  {/if}
  {#if page}
    <ul>
      {#each page.items as item (item.id)}<li>
          <div>
            <strong>{item.values.title}</strong>
            <p>{display(item.values.authors)}</p>
          </div>
          <button class="secondary" disabled={busy} onclick={() => select(item)}
            >Review {item.values.title}</button
          >
        </li>{/each}
    </ul>
    {#if !page.items.length}<p>No matches. Try a different title or author.</p>{/if}
    <nav aria-label="Metadata search pages">
      <button
        class="secondary"
        disabled={busy || !page.offset}
        onclick={() => search(undefined, page!.offset - 5)}>Previous matches</button
      ><span>{page.total} matches</span><button
        class="secondary"
        disabled={busy || page.offset + 5 >= page.total || page.offset >= 10000}
        onclick={() => search(undefined, page!.offset + 5)}>Next matches</button
      >
    </nav>
  {/if}
  {#if selected && metadataState}
    <section class="proposal" aria-label="Metadata preview">
      <h3>Choose what to keep.</h3>
      <p>
        <a href={selected.source_url} target="_blank" rel="noopener noreferrer"
          >View source on Open Library</a
        >
        · retrieved {new Date(selected.fetched_at).toLocaleString()}
      </p>
      {#each names as field}
        {#if selected.values[field] != null}<div class="field">
            <label
              ><input type="checkbox" value={field} bind:group={fields} disabled={busy} />Use
              suggested {field}</label
            >
            <div class="comparison">
              <div>
                <span>Current{metadataState.origins[field]?.protected ? ' · protected' : ''}</span>
                <p>{display(metadataState.work[field])}</p>
              </div>
              <div>
                <span>Suggestion</span>
                <p>{display(selected.values[field])}</p>
              </div>
            </div>
          </div>{/if}
      {/each}
      {#if !selected.detailed}<button class="secondary" disabled={busy} onclick={details}
          >Look up description</button
        >{/if}
      {#if protectedFields.length}<label class="permission"
          ><input type="checkbox" bind:checked={replaceProtected} disabled={busy} />Replace my
          protected {protectedFields.join(', ')} with these suggestions</label
        >{/if}
      <button
        class="primary accept"
        disabled={busy || !fields.length || (protectedFields.length > 0 && !replaceProtected)}
        onclick={accept}>Accept selected fields</button
      >
    </section>
  {/if}
</details>

<style>
  .metadata {
    border-top: 1px solid var(--line);
    padding: 1.1rem 0;
    margin-top: 1rem;
  }
  summary {
    cursor: pointer;
    font-weight: 500;
  }
  p {
    color: var(--muted);
    line-height: 1.6;
    overflow-wrap: anywhere;
    white-space: pre-wrap;
  }
  label {
    display: block;
    margin: 0.8rem 0;
  }
  .lookup {
    display: flex;
    flex-wrap: wrap;
    gap: 0.6rem;
  }
  .lookup input {
    flex: 1;
    min-width: 150px;
    background: transparent;
    border: 1px solid var(--line);
    padding: 0.7rem;
    font: inherit;
    color: inherit;
  }
  .origins {
    font-size: 0.8rem;
  }
  ul {
    list-style: none;
    padding: 0;
  }
  li,
  nav {
    display: flex;
    flex-wrap: wrap;
    gap: 0.8rem;
    align-items: center;
    justify-content: space-between;
    padding: 1rem 0;
    border-bottom: 1px solid var(--line);
  }
  li p {
    margin: 0.3rem 0;
  }
  nav {
    height: auto;
    width: 100%;
  }
  nav button {
    height: auto;
    padding: 0.75rem 1rem;
    border: 1px solid var(--line);
    font-size: 0.85rem;
  }
  .proposal {
    border: 1px solid var(--line);
    padding: 1.2rem;
    margin-top: 1.5rem;
  }
  h3 {
    font-size: 1.6rem;
    font-weight: 600;
    letter-spacing: -0.03em;
    margin: 0;
  }
  .comparison {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 1rem;
  }
  .comparison span {
    font-size: 0.75rem;
    text-transform: uppercase;
    color: var(--muted);
  }
  .field {
    border-top: 1px solid var(--line);
    padding: 0.7rem 0;
  }
  .permission {
    line-height: 1.5;
  }
  .accept {
    display: block;
    margin-top: 1rem;
  }
  a {
    color: var(--ink);
  }
  [role='alert'] {
    color: #9b482e;
  }
  @media (max-width: 600px) {
    .comparison {
      grid-template-columns: 1fr;
    }
  }
</style>

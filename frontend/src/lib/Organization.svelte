<script lang="ts">
  import { json, type Book } from './api';
  import type { components } from './schema';
  type Series = components['schemas']['SeriesOut'];
  type Membership = components['schemas']['MembershipEdit'];
  let { book, onupdate }: { book: Book; onupdate: (book: Book) => void } = $props();
  let editing = $state(false);
  let error = $state('');
  let busy = $state(false);
  let editions = $state<Book['editions']>([]);
  let memberships = $state<Membership[]>([]);
  let series = $state<Series[]>([]);
  let seriesId = $state('');
  let knownSeries = $state<Record<string, Series>>({});
  let editingRevision = 0;
  let seriesQuery = $state('');
  let appliedSeriesQuery = '';
  let seriesTotal = $state(0);
  let seriesOffset = $state(0);
  function seriesLabel(id: string) {
    const item = knownSeries[id];
    return item ? `${item.name} · ${item.run}` : id;
  }
  async function loadSeries(append = false) {
    try {
      const query = append ? appliedSeriesQuery : seriesQuery;
      const result = await json<components['schemas']['SeriesPage']>(
        `/series?q=${encodeURIComponent(query)}&offset=${append ? seriesOffset : 0}`,
      );
      for (const item of result.items) knownSeries[item.id] = item;
      series = append ? [...series, ...result.items] : result.items;
      seriesOffset = result.offset + result.items.length;
      seriesTotal = result.total;
      appliedSeriesQuery = query;
    } catch (cause) {
      error = String(cause);
    }
  }
  let seriesName = $state('');
  let seriesRun = $state('');
  let seriesEditing = $state<Series | null>(null);
  function editSeries(id: string) {
    const item = knownSeries[id];
    seriesEditing = item ? { ...item } : null;
  }
  async function saveSeries() {
    if (!seriesEditing) return;
    busy = true;
    error = '';
    try {
      const updated = await json<Series>(`/series/${seriesEditing.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(seriesEditing),
      });
      knownSeries[updated.id] = updated;
      series = series.map((s) => (s.id === updated.id ? updated : s));
      onupdate(await json<Book>(`/works/${book.id}`));
      seriesEditing = null;
    } catch (cause) {
      error = String(cause);
    } finally {
      busy = false;
    }
  }

  async function edit() {
    error = '';
    editingRevision = book.revision;
    for (const member of book.memberships) knownSeries[member.series_id] = member.series;
    editions = structuredClone($state.snapshot(book.editions));
    memberships = book.memberships.map(({ series_id, designation, position }) => ({
      series_id,
      designation,
      position,
    }));
    try {
      await loadSeries();
      editing = true;
    } catch (cause) {
      error = String(cause);
    }
  }
  function addMembership() {
    if (seriesId && !memberships.some((m) => m.series_id === seriesId))
      memberships.push({ series_id: seriesId, designation: '', position: 1 });
  }
  async function createSeries() {
    busy = true;
    error = '';
    try {
      const created = await json<Series>('/series', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: seriesName, run: seriesRun }),
      });
      knownSeries[created.id] = created;
      series = [...series, created];
      seriesId = created.id;
      addMembership();
      seriesName = '';
      seriesRun = '';
    } catch (cause) {
      error = String(cause);
    } finally {
      busy = false;
    }
  }
  async function save(event: SubmitEvent) {
    event.preventDefault();
    busy = true;
    error = '';
    try {
      const result = await json<Book>(`/works/${book.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          revision: editingRevision,
          title: book.title,
          authors: book.authors,
          description: book.description,
          editions: editions.map(
            ({ id, language, publisher, identifier, narrator, abridgement }) => ({
              id,
              language,
              publisher,
              identifier,
              narrator,
              abridgement,
            }),
          ),
          memberships,
        }),
      });
      onupdate(result);
      editing = false;
    } catch (cause) {
      error = String(cause);
    } finally {
      busy = false;
    }
  }
</script>

<section class="organization">
  <h2>Editions & series</h2>
  {#if error}<p class="error" role="alert">{error}</p>{/if}
  {#if editing}
    <form onsubmit={save}>
      {#each editions as edition, i}
        <fieldset>
          <legend>Edition {i + 1} · {edition.medium}</legend>
          <label>Language<input bind:value={edition.language} maxlength="64" /></label>
          <label>Publisher<input bind:value={edition.publisher} maxlength="1024" /></label>
          <label>Identifier<input bind:value={edition.identifier} maxlength="1024" /></label>
          {#if edition.medium === 'audio'}
            <label>Narrator<input bind:value={edition.narrator} maxlength="1024" /></label>
            <label
              >Abridgement<select bind:value={edition.abridgement}
                ><option value="unknown">Unknown</option><option value="unabridged"
                  >Unabridged</option
                ><option value="abridged">Abridged</option></select
              ></label
            >
          {/if}
        </fieldset>
      {/each}
      {#each memberships as member, i}
        <fieldset>
          <legend>{seriesLabel(member.series_id)}</legend>
          <button type="button" class="secondary" onclick={() => editSeries(member.series_id)}
            >Edit this series</button
          >
          <label
            >Issue or volume label<input
              bind:value={member.designation}
              maxlength="128"
              placeholder="Annual 2024"
            /></label
          >
          <label
            >Reading order<input
              type="number"
              step="any"
              required
              bind:value={member.position}
            /></label
          >
          <button
            type="button"
            class="secondary"
            onclick={() => (memberships = memberships.filter((_, index) => index !== i))}
            >Remove membership</button
          >
        </fieldset>
      {/each}
      {#if seriesEditing}
        <fieldset>
          <legend>Edit series metadata</legend>
          <label>Series title<input bind:value={seriesEditing.name} maxlength="1024" /></label>
          <label>Series run label<input bind:value={seriesEditing.run} maxlength="1024" /></label>
          <button
            type="button"
            class="secondary"
            disabled={busy || !seriesEditing.name.trim()}
            onclick={saveSeries}>Save series metadata</button
          >
          <button type="button" class="secondary" onclick={() => (seriesEditing = null)}
            >Cancel series edit</button
          >
        </fieldset>
      {/if}
      <label>Find a series<input bind:value={seriesQuery} maxlength="300" /></label>
      <button type="button" class="secondary" onclick={() => loadSeries()}>Search series</button>
      {#if seriesOffset < seriesTotal}<button
          type="button"
          class="secondary"
          onclick={() => loadSeries(true)}>More series</button
        >{/if}
      <label
        >Existing series<select bind:value={seriesId}
          ><option value="">Choose a series</option>{#each series as item}<option value={item.id}
              >{item.name} — {item.run || 'No run label'} · {item.id.slice(0, 8)}</option
            >{/each}</select
        ></label
      >
      <button class="secondary" type="button" disabled={!seriesId} onclick={addMembership}
        >Add to series</button
      >
      <details>
        <summary>Create a separate series</summary>
        <label>Series name<input bind:value={seriesName} maxlength="1024" /></label>
        <label
          >Run label<input
            bind:value={seriesRun}
            maxlength="1024"
            placeholder="2024 · Publisher"
          /></label
        >
        <p class="small muted">
          A new series stays separate even when its name matches another run.
        </p>
        <button
          class="secondary"
          type="button"
          disabled={busy || !seriesName.trim()}
          onclick={createSeries}>Create series</button
        >
      </details>
      <div class="actions">
        <button class="primary" disabled={busy}>Save editions & series</button><button
          type="button"
          class="secondary"
          onclick={() => (editing = false)}>Cancel</button
        >
      </div>
    </form>
  {:else}
    {#each book.memberships as member}<p>
        {member.series.name} · {member.series.run} · {member.designation}
        <span class="muted">(order {member.position})</span>
      </p>{/each}
    {#each book.editions as edition}
      <p class="small">
        {edition.medium.toUpperCase()} · {edition.language ||
          'Language unspecified'}{edition.narrator
          ? ` · Narrated by ${edition.narrator}`
          : ''}{edition.medium === 'audio' ? ` · ${edition.abridgement}` : ''}
      </p>
      {#each edition.representations as representation}
        {#if representation.facts.page_count}<p class="small">
            {String(representation.facts.page_count)}
            {representation.facts.page_count === 1 ? 'page' : 'pages'}
          </p>{/if}
        {#if representation.facts.duration_seconds}<p class="small">
            {Math.round(Number(representation.facts.duration_seconds) / 60)} minutes · {representation
              .assets.length} file(s)
          </p>{/if}
      {/each}
    {/each}
    <button class="secondary" onclick={edit}>Organize editions & series</button>
  {/if}
</section>

<style>
  .organization {
    margin: 2rem 0;
    padding-top: 1.5rem;
    border-top: 1px solid #cfcabd;
  }
  h2 {
    font-family: Georgia, serif;
    font-weight: normal;
    font-size: 1.5rem;
  }
  fieldset {
    border: 1px solid #cfcabd;
    padding: 1rem;
    margin: 1rem 0;
    min-width: 0;
  }
  label {
    display: block;
    margin: 0.7rem 0;
  }
  input,
  select {
    display: block;
    width: 100%;
    box-sizing: border-box;
    padding: 0.6rem;
    background: #fffcf5;
    border: 1px solid #cfcabd;
    color: inherit;
    font: inherit;
  }
  details {
    margin: 1rem 0;
  }
</style>

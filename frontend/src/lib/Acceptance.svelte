<script lang="ts">
  import { onMount, tick } from 'svelte';
  import { json } from './api';
  import type { components } from './schema';
  type Candidate = components['schemas']['CandidateOut'];
  type Metadata = components['schemas']['AcceptedMetadata'];
  type Page = components['schemas']['AcceptancePage'];
  type Job = components['schemas']['JobOut'];
  type SeriesPage = components['schemas']['SeriesPage'];
  let {
    selected,
    query,
    filter,
    scanId,
    jobId,
    editing = $bindable(null),
    onjob,
    onclear,
    onrefresh,
    onopen,
  }: {
    selected: string[];
    query: string;
    filter: string;
    scanId: string;
    jobId: string;
    editing: Candidate | null;
    onjob: (id: string) => void;
    onclear: () => void;
    onrefresh: () => void;
    onopen: (event: MouseEvent, id: string) => Promise<void>;
  } = $props();
  let mode = $state<'register' | 'copy'>('register');
  let title = $state('');
  let authors = $state('');
  let shelf = $state<'default' | 'library' | 'archive'>('default');
  let seriesQuery = $state('');
  let series = $state<SeriesPage | null>(null);
  let seriesId = $state('');
  let chosenSeries = $state<components['schemas']['SeriesOut'] | null>(null);
  let appliedSeriesQuery = '';
  let seriesOffset = $state(0);
  let designation = $state('');
  let position = $state<number | undefined>(undefined);
  let groupAudio = $state(false);
  let audioSingles = $state(false);
  let page = $state<Page | null>(null);
  let offset = $state(0);
  let busy = $state(false);
  let error = $state('');
  let editTitle = $state('');
  let editAuthors = $state('');
  let editShelf = $state<'default' | 'library' | 'archive'>('default');
  let editDesignation = $state('');
  let editPosition = $state<number | undefined>(undefined);
  let editIdentity = '';
  let loadedJob = '';
  let active = $state(false);
  let sequence = 0;
  let controller: AbortController | undefined;
  let timer: ReturnType<typeof setTimeout> | undefined;
  $effect(() => {
    if (!selected.length) groupAudio = false;
  });
  $effect(() => {
    if (editing && editIdentity !== editing.id) {
      editIdentity = editing.id;
      editTitle = String(editing.edits.title ?? editing.facts.title ?? '');
      const names = editing.edits.authors ?? editing.facts.authors;
      editAuthors = Array.isArray(names) ? names.join('\n') : '';
      editShelf = (editing.edits.shelf as typeof editShelf) || 'default';
      editDesignation = String(editing.edits.designation || '');
      editPosition =
        typeof editing.edits.position === 'number' ? editing.edits.position : undefined;
      void tick().then(() => document.getElementById('accepted-title')?.focus());
    } else if (!editing) editIdentity = '';
  });
  $effect(() => {
    if (active && jobId !== loadedJob) {
      loadedJob = jobId;
      offset = 0;
      page = null;
      void load();
    }
  });
  onMount(() => {
    active = true;
    loadedJob = jobId;
    void load();
    return () => {
      active = false;
      sequence++;
      controller?.abort();
      clearTimeout(timer);
    };
  });
  async function load() {
    clearTimeout(timer);
    controller?.abort();
    controller = new AbortController();
    const current = ++sequence;
    const id = jobId;
    if (!id) {
      page = null;
      return;
    }
    try {
      const result = await json<Page>(
        `/intake/acceptance/${encodeURIComponent(id)}?limit=12&offset=${offset}`,
        { signal: controller.signal },
      );
      if (active && current === sequence && id === jobId) page = result;
    } catch (cause) {
      if (active && current === sequence && !controller.signal.aborted) error = String(cause);
    } finally {
      if (active && current === sequence && id === jobId) timer = setTimeout(load, 1500);
    }
  }
  async function findSeries(offset = 0) {
    busy = true;
    error = '';
    try {
      if (offset === 0) appliedSeriesQuery = seriesQuery;
      const result = await json<SeriesPage>(
        `/series?q=${encodeURIComponent(appliedSeriesQuery)}&limit=20&offset=${offset}`,
      );
      if (active) {
        series = result;
        seriesOffset = offset;
      }
    } catch (cause) {
      error = String(cause);
    } finally {
      busy = false;
    }
  }
  function metadata(): Partial<Metadata> {
    return {
      ...(title.trim() ? { title: title.trim() } : {}),
      ...(authors.trim()
        ? {
            authors: authors
              .split('\n')
              .map((name) => name.trim())
              .filter(Boolean),
          }
        : {}),
      ...(shelf !== 'default' ? { shelf } : {}),
      ...(seriesId
        ? {
            series_id: seriesId,
            ...(designation.trim() ? { designation } : {}),
            ...(position !== undefined ? { position } : {}),
          }
        : {}),
    };
  }
  async function preview(event: SubmitEvent) {
    event.preventDefault();
    busy = true;
    error = '';
    try {
      const result = await json<Job>('/intake/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...(selected.length
            ? { candidate_ids: selected }
            : { q: query, state: filter, scan_id: scanId }),
          mode,
          metadata: metadata(),
          group_audio: groupAudio,
          audio_singles_confirmed: audioSingles,
        }),
      });
      if (!active) return;
      onjob(result.id);
      onclear();
      onrefresh();
    } catch (cause) {
      if (active) error = String(cause);
    } finally {
      busy = false;
    }
  }
  async function change(action: 'confirm' | 'cancel' | 'retry') {
    if (!page || page.job.id !== jobId) return;
    busy = true;
    error = '';
    try {
      await json<Job>(`/intake/jobs/${page.job.id}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, revision: page.job.revision }),
      });
      if (!active) return;
      onrefresh();
      await load();
    } catch (cause) {
      if (active) {
        error = String(cause);
        await load();
      }
    } finally {
      busy = false;
    }
  }
  async function saveEdit(event: SubmitEvent) {
    event.preventDefault();
    if (!editing) return;
    busy = true;
    error = '';
    try {
      await json<Candidate>(`/intake/candidates/${editing.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          revision: editing.revision,
          metadata: {
            ...editing.edits,
            title: editTitle,
            authors: editAuthors
              .split('\n')
              .map((name) => name.trim())
              .filter(Boolean),
            shelf: editShelf,
            designation: editDesignation.trim() || undefined,
            position: editPosition,
          },
        }),
      });
      if (!active) return;
      editing = null;
      onrefresh();
    } catch (cause) {
      if (active) error = String(cause);
    } finally {
      busy = false;
    }
  }
</script>

<section class="acceptance" aria-label="Batch acceptance">
  <div class="heading">
    <h2>{jobId ? 'Acceptance details.' : 'Bring them into Stacks.'}</h2>
    {#if jobId}<button class="secondary" disabled={busy} onclick={() => onjob('')}
        >Close batch details</button
      >
    {:else}<span
        >{selected.length ? `${selected.length} selected` : 'All eligible files in this view'}</span
      >{/if}
  </div>
  <p>
    {jobId
      ? 'The saved preview and its publication results.'
      : 'Preview your choices before adding anything. Exact byte duplicates keep their existing metadata.'}
  </p>
  {#if error}<p role="alert" class="error">{error}</p>{/if}
  {#if editing}
    <form class="editor" onsubmit={saveEdit}>
      <h3>Acceptance metadata: {editing.relative_path}</h3>
      <label
        >Accepted title<input
          id="accepted-title"
          bind:value={editTitle}
          required
          maxlength="1024"
          disabled={busy}
        /></label
      >
      <label
        >Accepted authors (one per line)<textarea bind:value={editAuthors} rows="2" disabled={busy}
        ></textarea></label
      >
      <label
        >Candidate shelf<select bind:value={editShelf} disabled={busy}
          ><option value="default">Archive; followed runs enter Library</option><option
            value="library">Keep in Library</option
          ><option value="archive">Keep in Archive</option></select
        ></label
      >
      <div class="fields">
        <label
          >Candidate designation<input
            bind:value={editDesignation}
            maxlength="100"
            disabled={busy}
            placeholder="Use embedded issue number"
          /></label
        ><label
          >Candidate sort position<input
            type="number"
            min="-1000000000"
            max="1000000000"
            step="any"
            bind:value={editPosition}
            disabled={busy}
            placeholder="Use numeric designation"
          /></label
        >
      </div>
      <p>
        These choices stay separate from embedded metadata and apply when this file is accepted.
      </p>
      <div class="actions">
        <button class="primary" disabled={busy}>Save acceptance metadata</button><button
          type="button"
          class="secondary"
          disabled={busy}
          onclick={() => (editing = null)}>Close editor</button
        >
      </div>
    </form>
  {/if}
  {#if !jobId}<form onsubmit={preview}>
      <div class="fields">
        <label
          >Original storage<select bind:value={mode} disabled={busy}
            ><option value="register">Register in place</option><option value="copy"
              >Copy into managed storage</option
            ></select
          ></label
        >
        <label
          >Batch shelf<select bind:value={shelf} disabled={busy}
            ><option value="default">Keep candidate choices / Archive by default</option><option
              value="library">Keep in Library</option
            ><option value="archive">Keep in Archive</option></select
          ></label
        >
      </div>
      <p class="hint">
        {mode === 'register'
          ? 'Originals stay in the source. Protect them with your separate source backup.'
          : 'Verified copies live in Stacks. Source originals remain unchanged.'}
      </p>
      <details>
        <summary>Shared metadata and audio grouping</summary>
        <div class="fields">
          <label
            >Batch title (optional)<input
              bind:value={title}
              maxlength="1024"
              disabled={busy}
              placeholder="Keep each file’s title"
            /></label
          >
          <label
            >Batch authors (one per line)<textarea
              bind:value={authors}
              rows="2"
              disabled={busy}
              placeholder="Keep each file’s authors"
            ></textarea></label
          >
        </div>
        <label
          >Find an existing run<input
            bind:value={seriesQuery}
            maxlength="300"
            disabled={busy}
          /></label
        >
        <button type="button" class="secondary" disabled={busy} onclick={() => findSeries()}
          >Find runs</button
        >
        <label
          >Batch series/run<select
            bind:value={seriesId}
            disabled={busy}
            onchange={(event) => {
              const id = event.currentTarget.value;
              chosenSeries =
                series?.items.find((item) => item.id === id) ||
                (chosenSeries?.id === id ? chosenSeries : null);
            }}
            ><option value="">Keep candidate choices / no run</option
            >{#if chosenSeries && !series?.items.some((item) => item.id === chosenSeries?.id)}<option
                value={chosenSeries.id}
                >{chosenSeries.name} · {chosenSeries.run || 'Unspecified run'}</option
              >{/if}{#each series?.items || [] as item}<option value={item.id}
                >{item.name} · {item.run || 'Unspecified run'}</option
              >{/each}</select
          ></label
        >
        {#if series && series.total > 20}<div class="actions" aria-label="Matching run pages">
            <button
              type="button"
              class="secondary"
              disabled={busy || seriesOffset === 0}
              onclick={() => findSeries(seriesOffset - 20)}>Previous runs</button
            >
            <span
              >{seriesOffset + 1}–{Math.min(seriesOffset + 20, series.total)} of {series.total} matching
              runs</span
            >
            <button
              type="button"
              class="secondary"
              disabled={busy || seriesOffset + 20 >= series.total}
              onclick={() => findSeries(seriesOffset + 20)}>Next runs</button
            >
          </div>{/if}
        {#if seriesId}<div class="fields">
            <label
              >Designation (optional)<input
                bind:value={designation}
                maxlength="100"
                disabled={busy}
              /></label
            ><label
              >Sort position<input
                type="number"
                min="-1000000000"
                max="1000000000"
                step="any"
                bind:value={position}
                placeholder="Use embedded issue number"
                disabled={busy}
              /></label
            >
          </div>
          <p class="hint">
            Blank values use each file’s embedded issue number. Non-numeric or out-of-range
            designations start at position 0; review annuals and specials before accepting.
          </p>{/if}
        <label class="check"
          ><input
            type="checkbox"
            bind:checked={groupAudio}
            disabled={busy || !selected.length}
          />Group selected audio tracks as one recording</label
        >
        <label class="check"
          ><input type="checkbox" bind:checked={audioSingles} disabled={busy || groupAudio} />I
          reviewed recording boundaries; accept audio files individually</label
        >
        <p class="hint">
          Grouped audio uses natural filename order, including disc folders. Review that order in
          the preview.
        </p>
      </details>
      <div class="actions">
        <button class="primary" disabled={busy}
          >{selected.length
            ? `Preview ${selected.length} selected files`
            : 'Preview all eligible files'}</button
        >{#if selected.length}<button
            type="button"
            class="secondary"
            disabled={busy}
            onclick={onclear}>Clear selection</button
          >{/if}
      </div>
    </form>{/if}
  {#if jobId && !page}<p role="status">Loading acceptance preview…</p>{/if}
  {#if page && page.job.id === jobId}
    <section class="preview" aria-label="Acceptance preview">
      <div class="heading">
        <h3>{page.grouped_audio ? 'One reviewed recording' : 'Acceptance batch'}</h3>
        <strong>{page.job.state}</strong>
      </div>
      <p>
        {page.total} files · {page.mode === 'register' ? 'Register in place' : 'Managed copies'} · {page
          .job.completed} accepted · {page.job.skipped} duplicates · {page.job.failed} failed · {page
          .job.remaining} remaining
      </p>
      {#if page.job.error}<p class="error">{page.job.error}</p>{/if}
      <ol start={offset + 1}>
        {#each page.items as item (item.id)}<li>
            <strong
              >{item.metadata.title ||
                String(item.candidate.facts.title || item.candidate.relative_path)}</strong
            >
            <p class="path">{item.candidate.root} / {item.candidate.relative_path}</p>
            <p>
              {(
                item.metadata.authors ||
                (Array.isArray(item.candidate.facts.authors) ? item.candidate.facts.authors : [])
              ).join(', ')} · {item.metadata.shelf === 'default'
                ? 'Archive by default'
                : item.metadata.shelf} · {item.state}
            </p>
            {#if item.series}<p>
                {item.series.name} · {item.series.run || 'Unspecified run'} · {item.metadata
                  .designation || 'No designation'} · position {item.metadata.position}
              </p>{/if}
            {#if item.error}<p class="error">{item.error}</p>{/if}
            {#if item.work_id}<a
                data-sveltekit-reload
                href={`/?book=${encodeURIComponent(item.work_id)}&scope=all`}
                onclick={(event) => onopen(event, item.work_id!)}>Open accepted work</a
              >{/if}
          </li>{/each}
      </ol>
      {#if page.total > 12}<div class="actions">
          <button
            class="secondary"
            disabled={offset === 0}
            onclick={() => {
              offset = Math.max(0, offset - 12);
              void load();
            }}>Previous preview files</button
          ><span>{offset + 1}–{Math.min(offset + 12, page.total)} of {page.total}</span><button
            class="secondary"
            disabled={offset + 12 >= page.total}
            onclick={() => {
              offset += 12;
              void load();
            }}>Next preview files</button
          >
        </div>{/if}
      <div class="actions">
        {#if page.job.state === 'preview'}<button
            class="primary"
            disabled={busy}
            onclick={() => change('confirm')}>Confirm acceptance</button
          ><button class="secondary" disabled={busy} onclick={() => change('cancel')}
            >Cancel preview</button
          >
        {:else if ['queued', 'running'].includes(page.job.state)}<button
            class="secondary"
            disabled={busy}
            onclick={() => change('cancel')}>Cancel acceptance</button
          >
        {:else if page.confirmed && (page.job.failed || page.job.remaining)}<button
            class="secondary"
            disabled={busy}
            onclick={() => change('retry')}>Retry acceptance</button
          >{/if}
      </div>
      <p class="hint">
        Cancellation stops at a checkpoint. A publication already committing may finish and will
        appear here.
      </p>
    </section>
  {/if}
</section>

<style>
  .acceptance {
    margin: 1.5rem 0 2rem;
    padding: 1.5rem;
    border: 1px solid var(--line);
  }
  h2 {
    font:
      400 1.8rem Georgia,
      serif;
    margin: 0;
  }
  h3 {
    font-size: 1rem;
    overflow-wrap: anywhere;
  }
  p {
    color: var(--muted);
    line-height: 1.6;
  }
  .heading,
  .actions {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 0.8rem;
  }
  .heading span,
  .hint,
  .path,
  li p {
    font-size: 0.85rem;
  }
  .fields {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1rem;
  }
  label {
    display: block;
    font-size: 0.85rem;
    margin: 1rem 0;
  }
  input:not([type='checkbox']),
  select,
  textarea {
    display: block;
    width: 100%;
    min-width: 0;
    margin-top: 0.5rem;
    padding: 0.7rem;
    border: 1px solid var(--line);
    background: transparent;
    color: inherit;
    font: inherit;
  }
  .check {
    display: flex;
    align-items: start;
    gap: 0.6rem;
  }
  .check input {
    margin-top: 0.2rem;
  }
  details {
    margin: 1rem 0;
  }
  summary {
    cursor: pointer;
    font-size: 0.9rem;
  }
  .actions {
    justify-content: start;
    margin: 1rem 0;
  }
  .preview,
  .editor {
    border-top: 1px solid var(--line);
    padding-top: 1.3rem;
    margin-top: 1.5rem;
  }
  li {
    padding: 1rem 0;
    border-bottom: 1px solid var(--line);
    overflow-wrap: anywhere;
  }
  ol {
    padding-left: 1.3rem;
  }
  li p {
    margin: 0.4rem 0;
  }
  .error {
    color: #9b482e;
  }
  @media (max-width: 600px) {
    .fields {
      grid-template-columns: 1fr;
    }
    .acceptance {
      padding: 1rem;
    }
    .actions button {
      width: 100%;
    }
  }
</style>

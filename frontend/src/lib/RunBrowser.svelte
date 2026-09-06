<script lang="ts">
  import { untrack } from 'svelte';
  import Cover from './Cover.svelte';
  import { json, type Book } from './api';
  import type { components } from './schema';
  type Run = components['schemas']['SeriesOut'];
  let {
    scope,
    query,
    seriesId = $bindable(''),
    runOffset = $bindable(0),
    offset = $bindable(0),
    onopen,
    onnavigate,
    onunassigned,
  }: {
    scope: string;
    query: string;
    seriesId: string;
    runOffset: number;
    offset: number;
    onopen: (book: Book) => void;
    onnavigate: () => void;
    onunassigned: () => void;
  } = $props();
  let runs = $state<components['schemas']['RunPage'] | null>(null);
  let works = $state<components['schemas']['RunWorksPage'] | null>(null);
  let series = $state<Run | null>(null);
  let error = $state('');
  let busy = $state(false);
  let sequence = 0;
  async function load() {
    const current = ++sequence;
    busy = true;
    error = '';
    try {
      if (seriesId) {
        const id = seriesId;
        const [details, page] = await Promise.all([
          json<Run>(`/series/${id}`),
          json<components['schemas']['RunWorksPage']>(
            `/series/${id}/works?scope=${scope}&medium=comic&offset=${offset}&limit=24`,
          ),
        ]);
        if (current !== sequence) return;
        series = details;
        works = page;
        if (!page.items.length && offset > 0) {
          offset = page.total ? Math.floor((page.total - 1) / 24) * 24 : 0;
          onnavigate();
        }
      } else {
        const page = await json<components['schemas']['RunPage']>(
          `/browse/series?medium=comic&scope=${scope}&q=${encodeURIComponent(query)}&limit=24&offset=${runOffset}`,
        );
        if (current !== sequence) return;
        runs = page;
        series = null;
        works = null;
        if (!page.items.length && runOffset > 0) {
          runOffset = page.total ? Math.floor((page.total - 1) / 24) * 24 : 0;
          onnavigate();
        }
      }
    } catch (cause) {
      if (current === sequence) error = String(cause);
    } finally {
      if (current === sequence) busy = false;
    }
  }
  $effect(() => {
    scope;
    query;
    seriesId;
    runOffset;
    offset;
    untrack(() => {
      void load();
    });
  });
  function open(id: string) {
    seriesId = id;
    offset = 0;
    onnavigate();
  }
  function back() {
    seriesId = '';
    offset = 0;
    onnavigate();
  }
  async function follow() {
    if (!series) return;
    busy = true;
    error = '';
    try {
      await json(`/series/${series.id}/following`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ revision: series.revision, following: !series.following }),
      });
      await load();
    } catch (cause) {
      error = String(cause);
    } finally {
      busy = false;
    }
  }
</script>

<section aria-label="Comic runs" class="runs">
  {#if error}<p role="alert">{error}</p>{/if}
  {#if seriesId}
    <button class="back" onclick={back}>← All comic runs</button>
    {#if series}<div class="run-heading">
        <div>
          <span class="eyebrow">PUBLICATION RUN · {series.run || 'UNDATED'}</span>
          <h2>{series.name}</h2>
        </div>
        <button class="secondary" onclick={follow} disabled={busy}
          >{series.following ? 'Unfollow series' : 'Follow series'}</button
        >
      </div>
      <p class="hint">
        {series.following
          ? 'Following. New members default to your Library shelf.'
          : 'Follow to keep this run close at hand.'} Your explicit shelf choices always stay yours.
      </p>
    {/if}
    {#if works?.items.length}<div class="book-grid">
        {#each works.items as work}<button
            class="book"
            onclick={() => onopen(work)}
            aria-label="Open {work.title}"
            ><Cover book={work} />
            <div class="book-caption">
              <h3>{work.title}</h3>
              <p>
                {work.memberships.find((m) => m.series_id === seriesId)?.designation ||
                  'Unnumbered'}
              </p>
              <span>{works.finished_work_ids.includes(work.id) ? 'Finished' : 'Unread'}</span>
            </div></button
          >{/each}
      </div>
      {#if works.total > 24}<div class="pagination">
          <button
            disabled={busy || offset === 0}
            onclick={() => {
              offset -= 24;
              onnavigate();
            }}>← Previous issues</button
          ><span>{offset + 1}–{Math.min(offset + 24, works.total)} of {works.total} owned</span
          ><button
            disabled={busy || offset + 24 >= works.total}
            onclick={() => {
              offset += 24;
              onnavigate();
            }}>Next issues →</button
          >
        </div>{/if}
    {:else if !busy}<p class="empty-run">
        No owned comics from this run in the selected shelf. Try Everything owned.
      </p>{/if}
  {:else}
    <div class="run-heading">
      <div>
        <span class="eyebrow">ONE RUN AT A TIME</span>
        <h2>Stories in sequence.</h2>
      </div>
      <button class="secondary" onclick={onunassigned}>Comics without a series</button>
    </div>
    <p class="hint">{runs?.total || 0} runs in this shelf. Counts describe your owned works.</p>
    {#if runs?.items.length}<div class="run-grid">
        {#each runs.items as item}<button
            class="run-card"
            onclick={() => open(item.series.id)}
            aria-label="Open run {item.series.name} {item.series.run}"
            ><span class="eyebrow">{item.series.run || 'UNDATED RUN'}</span>
            <h3>{item.series.name}</h3>
            <span class="run-count">{item.owned} owned · {item.finished} finished</span><span
              class="following">{item.series.following ? 'Following ↗' : 'Explore run ↗'}</span
            ></button
          >{/each}
      </div>
      {#if runs.total > 24}<div class="pagination">
          <button
            disabled={busy || runOffset === 0}
            onclick={() => {
              runOffset -= 24;
              onnavigate();
            }}>← Previous runs</button
          ><span>{runOffset + 1}–{Math.min(runOffset + 24, runs.total)} of {runs.total}</span
          ><button
            disabled={busy || runOffset + 24 >= runs.total}
            onclick={() => {
              runOffset += 24;
              onnavigate();
            }}>Next runs →</button
          >
        </div>{/if}
    {:else if !busy}<p class="empty-run">
        No matching runs. Comics without a series are available above; assign their series from the
        work page.
      </p>{/if}
  {/if}
</section>

<style>
  .runs {
    margin-top: 2rem;
  }
  button {
    font: inherit;
    color: inherit;
    background: transparent;
    border: 0;
    cursor: pointer;
  }
  .run-heading {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 1rem;
    flex-wrap: wrap;
    margin: 1rem 0;
  }
  h2,
  h3 {
    font-family: inherit;
    font-weight: 600;
    font-weight: 400;
  }
  .run-heading h2 {
    font-size: 2.5rem;
    margin: 0.7rem 0;
  }
  .hint,
  .empty-run {
    font-size: 0.9rem;
    color: var(--muted);
    line-height: 1.7;
  }
  .run-grid {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 1.2rem;
    margin-top: 2rem;
  }
  .run-card {
    text-align: left;
    display: flex;
    flex-direction: column;
    min-height: 220px;
    padding: 1.5rem;
    background: var(--accent-soft);
    border-top: 4px solid var(--accent);
    border-radius: 2px;
  }
  .run-card h3 {
    font-size: 1.9rem;
    margin: 1.5rem 0;
    overflow-wrap: anywhere;
  }
  .run-count {
    font-size: 0.9rem;
  }
  .following {
    margin-top: auto;
    padding-top: 1.5rem;
    font-size: 0.8rem;
  }
  .secondary {
    border: 1px solid var(--line);
    padding: 0.7rem 1rem;
  }
  .back {
    padding: 0;
    margin-bottom: 1.5rem;
  }
  .book {
    padding: 0;
    text-align: left;
    min-width: 0;
  }
  .book-caption h3 {
    font-size: 1rem;
    font-family: inherit;
    font-weight: 600;
    margin-bottom: 0.4rem;
  }
  [role='alert'] {
    color: #9b482e;
  }
  @media (max-width: 700px) {
    .run-grid {
      grid-template-columns: 1fr;
    }
    .run-heading h2 {
      font-size: 2rem;
    }
  }
</style>

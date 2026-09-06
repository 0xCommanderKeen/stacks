<script lang="ts">
  import { onMount } from 'svelte';
  import { json } from './api';
  import type { components } from './schema';
  type Job = components['schemas']['JobOut'];
  type Candidates = components['schemas']['CandidatePage'];
  type Jobs = components['schemas']['JobPage'];
  type Source = components['schemas']['SourceOut'];
  let roots = $state<Source[]>([]);
  let root = $state('');
  let prefix = $state('');
  let query = $state('');
  let appliedQuery = $state('');
  let filter = $state('');
  let selectedJob = $state('');
  let offset = $state(0);
  let jobsOffset = $state(0);
  let page = $state<Candidates | null>(null);
  let jobs = $state<Jobs | null>(null);
  let busy = $state(false);
  let error = $state('');
  let notice = $state('');
  let active = false;
  let sequence = 0;
  let controller: AbortController | undefined;
  let timer: ReturnType<typeof setTimeout> | undefined;

  function readUrl() {
    const params = new URLSearchParams(location.search);
    query = params.get('inbox_q') || '';
    appliedQuery = query;
    filter = params.get('inbox_state') || '';
    selectedJob = params.get('inbox_job') || '';
    const number = (key: string) => {
      const value = Number(params.get(key) || 0);
      return Number.isSafeInteger(value) && value >= 0 ? value : 0;
    };
    offset = number('inbox_offset');
    jobsOffset = number('jobs_offset');
    page = null;
    jobs = null;
    void load();
  }
  function writeUrl() {
    const params = new URLSearchParams(location.search);
    for (const [key, value] of Object.entries({
      inbox_q: appliedQuery,
      inbox_state: filter,
      inbox_job: selectedJob,
      inbox_offset: offset ? String(offset) : '',
      jobs_offset: jobsOffset ? String(jobsOffset) : '',
    })) {
      if (value) params.set(key, value);
      else params.delete(key);
    }
    history.pushState({}, '', `/?${params}`);
    page = null;
    void load();
  }
  async function load() {
    clearTimeout(timer);
    controller?.abort();
    controller = new AbortController();
    const current = ++sequence;
    const params = new URLSearchParams({
      q: appliedQuery,
      state: filter,
      job_id: selectedJob,
      limit: '24',
      offset: String(offset),
    });
    try {
      const [candidates, batches] = await Promise.all([
        json<Candidates>(`/intake/candidates?${params}`, { signal: controller.signal }),
        json<Jobs>(`/intake/jobs?limit=6&offset=${jobsOffset}`, { signal: controller.signal }),
      ]);
      if (!active || current !== sequence) return;
      page = candidates;
      jobs = batches;
    } catch (cause) {
      if (active && current === sequence && !controller.signal.aborted) error = String(cause);
    } finally {
      if (active && current === sequence) timer = setTimeout(load, 1500);
    }
  }
  onMount(() => {
    active = true;
    readUrl();
    void json<Source[]>('/sources')
      .then((items) => {
        if (!active) return;
        roots = items;
        if (!root) root = roots.find((item) => item.configured)?.alias || '';
      })
      .catch((cause) => {
        if (active) error = String(cause);
      });
    window.addEventListener('popstate', readUrl);
    return () => {
      active = false;
      sequence++;
      controller?.abort();
      clearTimeout(timer);
      window.removeEventListener('popstate', readUrl);
    };
  });
  async function scan(event: SubmitEvent) {
    event.preventDefault();
    busy = true;
    error = '';
    notice = '';
    try {
      const job = await json<Job>('/intake/scans', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ root, prefix }),
      });
      if (!active) return;
      selectedJob = job.id;
      offset = jobsOffset = 0;
      notice = 'Scan queued. You can leave this page while it runs.';
      writeUrl();
    } catch (cause) {
      if (active) error = String(cause);
    } finally {
      busy = false;
    }
  }
  async function change(job: Job, action: 'cancel' | 'retry') {
    busy = true;
    error = '';
    try {
      await json<Job>(`/intake/jobs/${job.id}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, revision: job.revision }),
      });
      if (!active) return;
      notice =
        action === 'cancel'
          ? 'Cancellation saved. Current inspection may finish before stopping.'
          : 'Retry queued from saved checkpoints.';
    } catch (cause) {
      if (active) error = String(cause);
    } finally {
      busy = false;
      if (active) await load();
    }
  }
</script>

<section class="inbox" aria-label="Inbox">
  <div class="eyebrow">FROM YOUR SOURCES</div>
  <h1>Inbox.</h1>
  <p class="intro">
    Discover what is there, then decide what belongs. Scans read originals and save their metadata
    without adding works to your library.
  </p>
  {#if error}<p class="error" role="alert">{error}</p>{/if}
  {#if notice}<p role="status">{notice}</p>{/if}
  <form class="scan" onsubmit={scan}>
    <div>
      <label for="scan-root">Source</label><select id="scan-root" bind:value={root} disabled={busy}>
        {#each roots.filter((item) => item.configured) as item}<option value={item.alias}
            >{item.alias}{item.available ? '' : ' · unavailable'}</option
          >{/each}
      </select>
    </div>
    <div class="folder">
      <label for="scan-prefix">Folder within source</label><input
        id="scan-prefix"
        bind:value={prefix}
        maxlength="1024"
        disabled={busy}
        placeholder="Leave blank for the whole source"
      />
    </div>
    <button class="primary" disabled={busy || !root}>Scan source</button>
  </form>
  {#if !roots.some((item) => item.configured)}<p>
      Configure a read-only source in Settings to begin.
    </p>{/if}
  <section class="batches" aria-label="Scan jobs">
    <div class="section-heading">
      <h2>Scans</h2>
      <button
        class="secondary"
        onclick={() => {
          error = '';
          void load();
        }}>Refresh</button
      >
    </div>
    {#if jobs}
      {#each jobs.items as job (job.id)}
        <article class:chosen={selectedJob === job.id}>
          <div class="batch-title">
            <button
              class="job-name"
              onclick={() => {
                selectedJob = job.id;
                offset = 0;
                writeUrl();
              }}>{job.root}{job.prefix ? ` / ${job.prefix}` : ''}</button
            ><span class="state">{job.state}</span>
          </div>
          <p>
            {job.discovered} discovered · {job.completed} inspected · {job.remaining} remaining · {job.skipped}
            skipped or waiting · {job.failed} failed
          </p>
          <div class="batch-bottom">
            <span
              >{job.directories_remaining} folders remaining · {new Date(
                job.created_at,
              ).toLocaleString()}</span
            >
            <button
              class="secondary"
              disabled={busy}
              onclick={() =>
                change(job, ['queued', 'running'].includes(job.state) ? 'cancel' : 'retry')}
              >{['queued', 'running'].includes(job.state) ? 'Cancel scan' : 'Retry scan'}</button
            >
          </div>
          {#if job.error}<p class="error">{job.error}</p>{/if}
        </article>
      {:else}<p>No scans yet. Choose a source above.</p>{/each}
      {#if jobs.total > 6}<div class="pagination">
          <button
            disabled={jobsOffset === 0}
            onclick={() => {
              jobsOffset = Math.max(0, jobsOffset - 6);
              writeUrl();
            }}>Previous scans</button
          ><span>{jobsOffset + 1}–{Math.min(jobsOffset + 6, jobs.total)} of {jobs.total}</span
          ><button
            disabled={jobsOffset + 6 >= jobs.total}
            onclick={() => {
              jobsOffset += 6;
              writeUrl();
            }}>Next scans</button
          >
        </div>{/if}
    {/if}
  </section>
  <section aria-label="Discovered files">
    <div class="section-heading">
      <h2>Discovered files</h2>
      {#if selectedJob}<button
          class="secondary"
          onclick={() => {
            selectedJob = '';
            offset = 0;
            writeUrl();
          }}>Show all scans</button
        >{/if}
    </div>
    <form
      class="filters"
      onsubmit={(event) => {
        event.preventDefault();
        appliedQuery = query;
        offset = 0;
        writeUrl();
      }}
    >
      <div class="folder">
        <label for="inbox-search">Search files or titles</label><input
          id="inbox-search"
          bind:value={query}
          maxlength="300"
          placeholder="A title or relative path"
        />
      </div>
      <div>
        <label for="inbox-filter">Review state</label><select
          id="inbox-filter"
          bind:value={filter}
          onchange={() => {
            offset = 0;
            writeUrl();
          }}
          ><option value="">All states</option
          >{#each ['pending', 'ready', 'review', 'duplicate', 'waiting', 'error'] as state}<option
              value={state}>{state}</option
            >{/each}</select
        >
      </div>
      <button class="secondary">Search Inbox</button>
    </form>
    <p class="hint">
      Ready files have inspected metadata. Audio needs a recording-boundary review. Duplicates match
      original bytes; titles alone never establish a match.
    </p>
    {#if page}
      <p class="count">{page.total} files{selectedJob ? ' in this scan' : ''}</p>
      <div class="files">
        {#each page.items as item (item.id)}
          <article>
            <div class="file-title">
              <h3>{String(item.facts.title || item.relative_path.split('/').pop())}</h3>
              <span class="state">{item.state}</span>
            </div>
            <p class="path">{item.root} / {item.relative_path}</p>
            {#if Array.isArray(item.facts.authors)}<p>{item.facts.authors.join(', ')}</p>{/if}
            {#if item.error}<p class="error">{item.error}</p>{/if}
            <details>
              <summary>Inspection evidence</summary>
              {#if item.sha256}<p class="checksum">SHA-256 {item.sha256}</p>{/if}
              {#if item.work_id}<p>
                  Matching catalog work: <a
                    href={`/?book=${encodeURIComponent(item.work_id)}&scope=all`}>Open work</a
                  >
                </p>{/if}
              <dl>
                {#each [['format', 'Format'], ['medium', 'Medium'], ['language', 'Language'], ['publisher', 'Publisher'], ['identifier', 'Identifier'], ['narrator', 'Narrator'], ['page_count', 'Pages'], ['duration_seconds', 'Duration (seconds)']] as [key, label]}
                  {#if item.facts[key]}<dt>{label}</dt>
                    <dd>{String(item.facts[key])}</dd>{/if}
                {/each}
              </dl>
              {#if item.facts.series_hint && typeof item.facts.series_hint === 'object'}<p>
                  Embedded series: {Object.entries(item.facts.series_hint)
                    .filter(([, value]) => value)
                    .map(([key, value]) => `${key}: ${value}`)
                    .join(' · ')}
                </p>{/if}
              {#if item.facts.description}<p>{String(item.facts.description)}</p>{/if}
            </details>
          </article>
        {:else}<p class="empty">
            No files match this view. A running scan will add results here.
          </p>{/each}
      </div>
      {#if page.total > 24 || offset > 0}<div class="pagination">
          <button
            disabled={offset === 0}
            onclick={() => {
              offset = Math.max(0, offset - 24);
              writeUrl();
            }}>Previous files</button
          ><span
            >{page.total ? offset + 1 : 0}–{Math.min(offset + 24, page.total)} of {page.total}</span
          ><button
            disabled={offset + 24 >= page.total}
            onclick={() => {
              offset += 24;
              writeUrl();
            }}>Next files</button
          >
        </div>{/if}
    {:else}<p role="status">Loading Inbox…</p>{/if}
  </section>
</section>

<style>
  .inbox {
    max-width: 72rem;
    margin: 0 auto;
  }
  h1 {
    font:
      400 4rem Georgia,
      serif;
    margin: 0.5rem 0 1rem;
  }
  h2 {
    font:
      400 2rem Georgia,
      serif;
    margin: 0;
  }
  h3 {
    font-size: 1.1rem;
    margin: 0;
    overflow-wrap: anywhere;
  }
  p {
    line-height: 1.6;
    color: var(--muted);
  }
  .intro {
    max-width: 44rem;
    margin-bottom: 2rem;
  }
  .scan,
  .filters {
    display: flex;
    align-items: end;
    gap: 1rem;
    flex-wrap: wrap;
  }
  .scan {
    padding: 1.5rem;
    background: var(--paper, #f5f2e9);
    border: 1px solid var(--line);
  }
  form > div {
    min-width: 10rem;
  }
  .folder {
    flex: 1;
  }
  label {
    display: block;
    margin-bottom: 0.5rem;
    font-size: 0.85rem;
  }
  input,
  select {
    width: 100%;
    min-width: 0;
    padding: 0.8rem;
    font: inherit;
    color: inherit;
    background: transparent;
    border: 1px solid var(--line);
  }
  .batches {
    margin: 2.5rem 0;
  }
  .section-heading,
  .batch-title,
  .batch-bottom,
  .file-title,
  .pagination {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    flex-wrap: wrap;
  }
  .section-heading {
    margin-bottom: 1.3rem;
  }
  article {
    border-top: 1px solid var(--line);
    padding: 1.2rem 0;
  }
  .batches article {
    padding: 1.1rem;
    border: 1px solid var(--line);
    margin: 0.6rem 0;
  }
  .chosen {
    border-left: 3px solid var(--accent, #536748) !important;
  }
  .job-name {
    border: 0;
    background: transparent;
    font: inherit;
    font-weight: 600;
    color: inherit;
    padding: 0;
    text-align: left;
    overflow-wrap: anywhere;
  }
  .state {
    text-transform: uppercase;
    font-size: 0.7rem;
    letter-spacing: 0.08em;
    border: 1px solid var(--line);
    padding: 0.25rem 0.5rem;
  }
  .batch-bottom,
  .hint,
  .path,
  details,
  .count {
    font-size: 0.85rem;
  }
  .path,
  .checksum {
    overflow-wrap: anywhere;
  }
  .files p {
    margin: 0.4rem 0;
  }
  details {
    margin-top: 0.8rem;
  }
  summary {
    cursor: pointer;
  }
  dl {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 0.5rem 1rem;
  }
  dt {
    color: var(--muted);
  }
  dd {
    margin: 0;
    overflow-wrap: anywhere;
  }
  .error {
    color: #9b482e;
  }
  .pagination {
    margin: 1.5rem 0;
  }
  .pagination button {
    background: transparent;
    border: 1px solid var(--line);
    color: inherit;
    padding: 0.6rem;
    font: inherit;
  }
  button:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  @media (max-width: 600px) {
    .scan,
    .filters {
      align-items: stretch;
      flex-direction: column;
    }
    h1 {
      font-size: 3rem;
    }
    .file-title {
      align-items: start;
    }
  }
</style>

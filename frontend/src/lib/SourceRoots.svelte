<script lang="ts">
  import { onMount } from 'svelte';
  import { json, type Book, type ImportResult } from './api';
  import type { components } from './schema';
  let { onopen }: { onopen: (book: Book) => void } = $props();
  let roots = $state<components['schemas']['SourceOut'][]>([]);
  let root = $state('');
  let paths = $state('');
  let busy = $state(false);
  let error = $state('');
  let result = $state<ImportResult | null>(null);
  async function load() {
    try {
      roots = await json<components['schemas']['SourceOut'][]>('/sources');
      if (!root) root = roots.find((r) => r.configured)?.alias || '';
    } catch (cause) {
      error = String(cause);
    }
  }
  onMount(() => {
    void load();
  });
  async function register(event: SubmitEvent) {
    event.preventDefault();
    busy = true;
    error = '';
    result = null;
    try {
      result = await json<ImportResult>('/sources/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          root,
          paths: paths
            .split('\n')
            .map((p) => p.trim())
            .filter(Boolean),
        }),
      });
      await load();
    } catch (cause) {
      error = String(cause);
    } finally {
      busy = false;
    }
  }
</script>

<section aria-label="Read-only sources" class="sources">
  <div class="eyebrow">KEEP ORIGINALS WHERE THEY ARE</div>
  <h2>Read-only sources.</h2>
  <p>
    Register an existing book or audiobook without copying its original files. New registrations
    start in Archive. Your notes, covers, and reading history live in Stacks.
  </p>
  <p>
    <strong>Protect source originals separately.</strong> The library backup includes your catalog and
    Stacks-owned files. It records source locations and checksums, but does not include registered original
    files.
  </p>
  {#if error}<p role="alert">{error}</p>{/if}
  {#if roots.length}
    <ul>
      {#each roots as item}<li>
          <strong>{item.alias}</strong><span
            >{item.registered_assets} registered files · {item.available
              ? 'Available'
              : item.configured
                ? 'Source unavailable'
                : 'Needs configuration'}</span
          >
        </li>{/each}
    </ul>
    <form onsubmit={register}>
      <label for="source-alias">Source</label><select
        id="source-alias"
        bind:value={root}
        disabled={busy}
        >{#each roots.filter((r) => r.configured) as item}<option value={item.alias}
            >{item.alias}</option
          >{/each}</select
      >
      <label for="source-paths">Paths within this source</label><textarea
        id="source-paths"
        bind:value={paths}
        rows="4"
        required
        disabled={busy}
        placeholder="Books/My book.epub"
      ></textarea>
      <p class="hint">
        One book file, or one audio track per line for a single audiobook. Audio tracks use natural
        filename order, including disc folders.
      </p>
      <button class="primary" disabled={busy || !root}
        >{busy ? 'Inspecting and registering…' : 'Register originals'}</button
      >
    </form>
  {:else}<p>
      No sources configured. Add a read-only directory mount and a source alias in the deployment
      configuration to register files here.
    </p>{/if}
  <button class="secondary" disabled={busy} onclick={load}>Refresh sources</button>
  {#if result}<div role="status">
      <p>
        {result.duplicate ? 'Already in your catalog.' : 'Registered in Archive.'}
        {result.work.title}
      </p>
      <button class="secondary" onclick={() => onopen(result!.work)}>Open registered work</button>
    </div>{/if}
</section>

<style>
  .sources {
    border-top: 1px solid var(--line);
    margin-top: 3rem;
    padding: 2rem 0;
    max-width: 54rem;
  }
  h2 {
    font-size: 2rem;
    font-weight: 600;
    letter-spacing: -0.03em;
  }
  p {
    color: var(--muted);
    line-height: 1.7;
  }
  ul {
    list-style: none;
    padding: 0;
  }
  li {
    display: flex;
    flex-wrap: wrap;
    justify-content: space-between;
    gap: 0.5rem;
    padding: 0.8rem 0;
    border-bottom: 1px solid var(--line);
  }
  li span {
    color: var(--muted);
    font-size: 0.85rem;
  }
  form {
    display: grid;
    gap: 0.7rem;
    margin: 1.5rem 0;
  }
  label {
    font-size: 0.85rem;
  }
  select,
  textarea {
    width: 100%;
    min-width: 0;
    background: transparent;
    border: 1px solid var(--line);
    padding: 0.8rem;
    font: inherit;
  }
  .hint {
    font-size: 0.85rem;
    margin: 0;
  }
  form button {
    justify-self: start;
  }
  [role='alert'] {
    color: #9b482e;
  }
</style>

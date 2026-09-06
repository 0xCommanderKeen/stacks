<script lang="ts">
  import { onMount } from 'svelte';
  import { json, request } from './api';
  import type { components } from './schema';
  type Page = components['schemas']['BackupPage'];
  type Health = components['schemas']['MaintenanceOut'];
  let page = $state<Page | null>(null);
  let health = $state<Health | null>(null);
  let mode = $state<'catalog' | 'full'>('catalog');
  let offset = $state(0);
  let busy = $state(false);
  let error = $state('');
  let mounted = false;
  let loading = false;
  const active = $derived(page?.items.some((item) => ['queued', 'running'].includes(item.state)));
  function size(value: number) {
    return value >= 1024 ** 3
      ? `${(value / 1024 ** 3).toFixed(1)} GB`
      : `${(value / 1024 ** 2).toFixed(1)} MB`;
  }
  async function load() {
    if (loading) return;
    loading = true;
    try {
      const [nextPage, nextHealth] = await Promise.all([
        json<Page>(`/backups?limit=12&offset=${offset}`),
        json<Health>('/maintenance'),
      ]);
      if (mounted) {
        page = nextPage;
        health = nextHealth;
      }
    } finally {
      loading = false;
    }
  }
  async function run(action: () => Promise<void>) {
    busy = true;
    error = '';
    try {
      await action();
    } catch (cause) {
      if (mounted) error = String(cause);
    } finally {
      if (mounted) busy = false;
    }
  }
  onMount(() => {
    mounted = true;
    void run(load);
    const timer = setInterval(() => {
      if (!busy)
        void load().catch((cause) => {
          if (mounted) error = String(cause);
        });
    }, 2000);
    return () => {
      mounted = false;
      clearInterval(timer);
    };
  });
  function create() {
    void run(async () => {
      await json('/backups', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode }),
      });
      offset = 0;
      await load();
    });
  }
  function remove(id: string) {
    void run(async () => {
      await request(`/backups/${id}/copy`, { method: 'DELETE' });
      await load();
    });
  }
  function navigate(value: number) {
    offset = value;
    void run(load);
  }
</script>

<section class="backups" aria-label="Library backups">
  <div class="eyebrow">RECOVERY & STORAGE</div>
  <h2>Keep your choices safe.</h2>
  <p>
    Back up your catalog and chosen cover originals regularly. Download a copy to separate storage
    after it finishes.
  </p>
  {#if health}
    <div class="health">
      <p><strong>{size(health.disk_free_bytes)}</strong> free on Stacks storage</p>
      <p>
        {health.pending_intake} active intake jobs · {health.failed_intake} intake jobs needing attention
        · {health.pending_trash} unfinished Trash operations
      </p>
      <p>
        Last successful backup: {health.last_backup?.finished_at
          ? new Date(health.last_backup.finished_at).toLocaleString()
          : 'None yet'}
      </p>
    </div>
  {/if}
  {#if error}<p role="alert">{error}</p>{/if}
  <label for="backup-mode">Include in this backup</label>
  <select id="backup-mode" bind:value={mode} disabled={busy || active}>
    <option value="catalog">Catalog and chosen covers</option>
    <option value="full">Catalog, covers and managed originals</option>
  </select>
  <p class="muted">
    {mode === 'catalog'
      ? 'Publication files and thumbnails are excluded. Protect managed originals separately and restore them alongside this catalog.'
      : 'This can be large. Stacks-owned originals are included; registered source originals still need a separate backup.'}
  </p>
  <button class="primary" onclick={create} disabled={busy || active}>Create backup</button>
  <p class="muted">
    Registered source originals are always protected separately. Restore into a fresh data directory
    with the documented restore command. Reader passwords must be issued again.
  </p>
  <h3>Backup history</h3>
  {#if page}
    {#if !page.total}<p>No backups yet.</p>{/if}
    <ul>
      {#each page.items as item (item.id)}
        <li>
          <div>
            <strong
              >{item.mode === 'catalog'
                ? 'Catalog and covers'
                : 'Including managed originals'}</strong
            ><br /><span
              >{new Date(item.created_at).toLocaleString()} · {item.state} · {size(
                item.bytes,
              )}</span
            >
          </div>
          {#if item.error}<p role="alert">{item.error}</p>{/if}
          {#if item.available}
            <a class="button secondary" href={`/api/backups/${item.id}/download`} download
              >Download backup</a
            >
            <button onclick={() => remove(item.id)} disabled={busy}>Remove server copy</button>
          {:else if item.state === 'error'}
            <button onclick={() => remove(item.id)} disabled={busy}
              >Remove unfinished server copy</button
            >
          {:else if item.state === 'complete'}<span class="muted">Server copy removed</span>{/if}
        </li>
      {/each}
    </ul>
    {#if page.total > 12}
      <div class="paging">
        <button disabled={busy || !offset} onclick={() => navigate(Math.max(0, offset - 12))}
          >Newer backups</button
        ><button disabled={busy || offset + 12 >= page.total} onclick={() => navigate(offset + 12)}
          >Older backups</button
        >
      </div>
    {/if}
  {/if}
</section>

<style>
  .backups {
    background: var(--surface);
    border-radius: 12px;
    margin: 2rem 0;
    padding: 2rem;
    border: 1px solid var(--line);
  }
  h2 {
    margin: 0.6rem 0 1rem;
  }
  p {
    max-width: 68ch;
    line-height: 1.6;
  }
  label {
    display: block;
    margin-bottom: 0.5rem;
  }
  select {
    width: 100%;
    max-width: 32rem;
    min-height: 44px;
    padding: 0.65rem;
    font: inherit;
    color: inherit;
    background: transparent;
    border: 1px solid var(--line);
    margin-bottom: 0.4rem;
  }
  .health {
    border-left: 3px solid var(--line);
    padding-left: 1rem;
    margin: 1.5rem 0;
  }
  ul {
    list-style: none;
    padding: 0;
  }
  li {
    padding: 1rem 0;
    border: 1px solid var(--line);
    display: flex;
    gap: 0.8rem;
    align-items: center;
    flex-wrap: wrap;
  }
  li div {
    flex: 1 1 18rem;
  }
  li p {
    width: 100%;
  }
  .paging {
    display: flex;
    flex-wrap: wrap;
    gap: 0.8rem;
  }
  @media (max-width: 600px) {
    .backups {
      background: var(--surface);
      border-radius: 12px;
      padding: 1.2rem;
    }
  }
</style>

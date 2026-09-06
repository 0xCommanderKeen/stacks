<script lang="ts">
  import { onMount } from 'svelte';
  import { json, request } from './api';
  import type { components } from './schema';
  type Page = components['schemas']['DevicePage'];
  type Issued = components['schemas']['DeviceIssued'];
  let page = $state<Page | null>(null);
  let issued = $state<Issued | null>(null);
  let name = $state('');
  let scope = $state<'library' | 'all'>('library');
  let offset = $state(0);
  let busy = $state(false);
  let error = $state('');
  async function load() {
    page = await json<Page>(`/devices?limit=12&offset=${offset}`);
    if (offset && !page.items.length) {
      offset = Math.max(0, Math.floor((page.total - 1) / 12) * 12);
      page = await json<Page>(`/devices?limit=12&offset=${offset}`);
    }
  }
  async function run(action: () => Promise<void>) {
    busy = true;
    error = '';
    try {
      await action();
    } catch (cause) {
      error = String(cause);
    } finally {
      busy = false;
    }
  }
  onMount(() => {
    void run(load);
  });
  function create(event: SubmitEvent) {
    event.preventDefault();
    void run(async () => {
      issued = await json<Issued>('/devices', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, scope }),
      });
      name = '';
      offset = 0;
      await load();
    });
  }
  function revoke(id: string) {
    void run(async () => {
      await request(`/devices/${id}`, { method: 'DELETE' });
      if (issued?.device.id === id) issued = null;
      await load();
    });
  }
</script>

<section aria-label="Reader devices" class="devices">
  <div class="eyebrow">TAKE YOUR LIBRARY WITH YOU</div>
  <h2>Reader devices.</h2>
  <p>
    Connect an OPDS reader to browse and download your originals. Give each reader its own password
    so you can revoke access separately.
  </p>
  <p>
    Use an HTTPS address when connecting a reader. This password grants download access to the shelf
    you choose.
  </p>
  {#if error}<p role="alert">{error}</p>{/if}
  <form onsubmit={create}>
    <label for="device-name">Reader name</label>
    <input
      id="device-name"
      bind:value={name}
      maxlength="100"
      required
      disabled={busy}
      placeholder="My reading tablet"
    />
    <label for="device-scope">Available books</label>
    <select id="device-scope" bind:value={scope} disabled={busy}>
      <option value="library">Library only</option>
      <option value="all">Library and Archive</option>
    </select>
    <button class="primary" disabled={busy || !name.trim()}>Create reader password</button>
  </form>
  {#if issued}
    <div class="credential" role="status">
      <h3>Connect {issued.device.name}</h3>
      <p>Save this password in your reader now. It is shown only here, once.</p>
      <label for="reader-url">Catalog URL</label><input
        id="reader-url"
        readonly
        value={issued.catalog_url}
      />
      <label for="reader-user">Username</label><input
        id="reader-user"
        readonly
        value={issued.username}
      />
      <label for="reader-password">Reader password</label><input
        id="reader-password"
        readonly
        value={issued.password}
        autocomplete="off"
      />
      <button
        class="secondary"
        onclick={() => {
          issued = null;
        }}>I saved the password</button
      >
    </div>
  {/if}
  {#if page}
    <ul>
      {#each page.items as device (device.id)}
        <li>
          <div>
            <strong>{device.name}</strong><span
              >{device.scope === 'all' ? 'Library and Archive' : 'Library only'} · {device.last_used_at
                ? `Last used ${new Date(device.last_used_at).toLocaleString()}`
                : 'Not used yet'}</span
            >
          </div>
          <button
            class="secondary"
            disabled={busy}
            aria-label={`Revoke ${device.name}`}
            onclick={() => revoke(device.id)}>Revoke access</button
          >
        </li>
      {/each}
    </ul>
    {#if !page.total}<p>No readers connected yet.</p>{/if}
    {#if page.total > 12}<nav aria-label="Reader pages">
        <button
          class="secondary"
          disabled={busy || !offset}
          onclick={() =>
            run(async () => {
              offset -= 12;
              await load();
            })}>Previous readers</button
        >
        <span>{offset + 1}–{Math.min(offset + 12, page.total)} of {page.total}</span>
        <button
          class="secondary"
          disabled={busy || offset + 12 >= page.total}
          onclick={() =>
            run(async () => {
              offset += 12;
              await load();
            })}>Next readers</button
        >
      </nav>{/if}
  {/if}
</section>

<style>
  .devices {
    border-top: 1px solid var(--line);
    margin-top: 3rem;
    padding: 2rem 0;
    max-width: 54rem;
  }
  h2 {
    font:
      400 2.4rem Georgia,
      serif;
  }
  p {
    color: var(--muted);
    line-height: 1.7;
  }
  form,
  .credential {
    display: grid;
    gap: 0.7rem;
    margin: 1.5rem 0;
  }
  .credential {
    border: 1px solid var(--line);
    padding: 1.5rem;
    background: var(--paper);
  }
  h3 {
    margin: 0;
    font:
      400 1.6rem Georgia,
      serif;
  }
  input,
  select {
    width: 100%;
    min-width: 0;
    background: transparent;
    border: 1px solid var(--line);
    padding: 0.8rem;
    font: inherit;
    color: inherit;
  }
  label {
    font-size: 0.85rem;
  }
  button {
    justify-self: start;
  }
  ul {
    list-style: none;
    padding: 0;
  }
  li,
  nav {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    padding: 1rem 0;
    border-bottom: 1px solid var(--line);
  }
  li span {
    display: block;
    color: var(--muted);
    font-size: 0.85rem;
    margin-top: 0.4rem;
  }
  [role='alert'] {
    color: #9b482e;
  }
</style>

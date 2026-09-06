<script lang="ts">
  import { untrack } from 'svelte';
  import { json, type Book } from './api';
  import type { components } from './schema';
  let { book }: { book: Book } = $props();
  let statuses = $state<components['schemas']['AssetAvailability'][]>([]);
  let error = $state('');
  let sequence = 0;
  async function load() {
    const current = ++sequence;
    error = '';
    try {
      const result = await json<components['schemas']['AssetAvailability'][]>(
        `/works/${book.id}/availability`,
      );
      if (current === sequence) statuses = result;
    } catch (cause) {
      if (current === sequence) error = String(cause);
    }
  }
  $effect(() => {
    book.id;
    untrack(() => {
      statuses = [];
      void load();
    });
  });
  let assets = $derived(book.editions.flatMap((e) => e.representations.flatMap((r) => r.assets)));
</script>

<section aria-label="Original availability">
  <h3>Original files</h3>
  {#if error}<p role="alert">{error}</p>{/if}
  {#each statuses as status}<p class:missing={!status.available}>
      <strong>{assets.find((a) => a.id === status.asset_id)?.original_name}</strong><br
      />{status.available ? status.detail : `Unavailable: ${status.detail}`}
    </p>{/each}
  <button class="secondary" onclick={load}>Check availability</button>
</section>

<style>
  section {
    margin-top: 2rem;
    border-top: 1px solid var(--line);
    padding-top: 1rem;
  }
  p {
    font-size: 0.85rem;
    line-height: 1.6;
    overflow-wrap: anywhere;
    color: var(--muted);
  }
  .missing,
  [role='alert'] {
    color: #9b482e;
  }
</style>

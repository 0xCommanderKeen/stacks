<script lang="ts">
  import { onMount } from 'svelte';
  import Cover from './Cover.svelte';
  import { json, type Book } from './api';
  import type { components } from './schema';

  let {
    onopen,
    onplay,
    onerror,
  }: {
    onopen: (book: Book) => void;
    onplay: (id: string) => void;
    onerror: (error: unknown) => void;
  } = $props();
  let page = $state<components['schemas']['ContinuePage'] | null>(null);
  onMount(() => {
    let active = true;
    json<components['schemas']['ContinuePage']>('/home/continue?limit=3')
      .then((result) => {
        if (active) page = result;
      })
      .catch((error) => {
        if (active) onerror(error);
      });
    return () => {
      active = false;
    };
  });
  function position(seconds: number) {
    const minutes = Math.floor(seconds / 60);
    return `${minutes}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`;
  }
</script>

{#if page?.items.length}
  <section class="continue-listening" aria-label="Continue listening">
    <h2>Continue listening</h2>
    <div class="continue-items">
      {#each page.items as item (item.representation_id)}
        <div class="continue-item">
          <button
            class="mini-cover"
            aria-label="Details for {item.work.title}"
            onclick={() => onopen(item.work)}><Cover book={item.work} /></button
          >
          <div class="continue-copy">
            <strong>{item.work.title}</strong><span
              >Saved at {position(item.progress.position)} in current track</span
            >
          </div>
          <button
            class="secondary"
            aria-label="Resume {item.work.title}"
            onclick={() => onplay(item.representation_id)}
            >Listen <span aria-hidden="true">▷</span></button
          >
        </div>
      {/each}
    </div>
  </section>
{/if}

<style>
  .continue-listening {
    padding: 18px 20px;
    margin-bottom: 26px;
    background: var(--surface);
    border: 1px solid var(--line);
    border-radius: 12px;
  }
  h2 {
    font-size: 12px;
    margin: 0 0 14px;
    color: var(--muted);
    font-weight: 500;
  }
  .continue-items {
    display: grid;
    gap: 16px;
    grid-template-columns: repeat(auto-fit, minmax(min(100%, 270px), 1fr));
  }
  .continue-item {
    display: flex;
    align-items: center;
    gap: 12px;
    min-width: 0;
  }
  .mini-cover {
    width: 38px;
    flex: none;
    border: 0;
    padding: 0;
    background: none;
  }
  .continue-copy {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 5px;
  }
  strong {
    font-size: 13px;
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
  }
  .continue-copy span {
    color: var(--muted);
    font-size: 11px;
    line-height: 1.5;
  }
  .secondary {
    padding: 8px 10px;
    font-size: 12px;
    flex: none;
  }
</style>

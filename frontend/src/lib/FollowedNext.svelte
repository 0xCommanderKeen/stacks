<script lang="ts">
  import { untrack } from 'svelte';
  import Cover from './Cover.svelte';
  import { json, type Book } from './api';
  import type { components } from './schema';
  let {
    onopen,
    offset = $bindable(0),
    onnavigate,
  }: {
    onopen: (book: Book, seriesId: string) => void;
    offset: number;
    onnavigate: () => void;
  } = $props();
  let page = $state<components['schemas']['NextPage'] | null>(null);
  let error = $state('');
  let sequence = 0;
  async function load() {
    const current = ++sequence;
    try {
      const result = await json<components['schemas']['NextPage']>(
        `/home/next?offset=${offset}&limit=12`,
      );
      if (current !== sequence) return;
      page = result;
      if (!result.items.length && offset > 0) {
        offset = result.total ? Math.floor((result.total - 1) / 12) * 12 : 0;
        onnavigate();
      }
    } catch (cause) {
      if (current === sequence) error = String(cause);
    }
  }
  $effect(() => {
    offset;
    untrack(() => {
      void load();
    });
  });
</script>

<section class="next" aria-label="Next in followed series">
  <span class="eyebrow">KEEP THE STORY GOING</span>
  <h2>Next in your series.</h2>
  {#if error}<p role="alert">{error}</p>{/if}
  {#if page?.items.length}<div class="book-grid">
      {#each page.items as item}<button
          class="book"
          onclick={() => onopen(item.work, item.series.id)}
          aria-label="Open next {item.work.title}"
          ><Cover book={item.work} />
          <div class="book-caption">
            <h3>{item.work.title}</h3>
            <p>{item.series.name} · {item.series.run}</p>
            <span>{item.designation || 'Next unread owned work'}</span>
          </div></button
        >{/each}
    </div>
    {#if page.total > 12}<div class="pagination">
        <button
          disabled={offset === 0}
          onclick={() => {
            offset -= 12;
            onnavigate();
          }}>← Previous series</button
        ><span>{offset + 1}–{Math.min(offset + 12, page.total)} of {page.total}</span><button
          disabled={offset + 12 >= page.total}
          onclick={() => {
            offset += 12;
            onnavigate();
          }}>Next series →</button
        >
      </div>{/if}
  {:else}<p>
      Follow a series from Comics to bring its next unfinished Library work here. Reading records
      mark what you have finished.
    </p>{/if}
</section>

<style>
  .next {
    border-top: 1px solid var(--line);
    margin-top: 3rem;
    padding-top: 2rem;
  }
  h2 {
    font-family: inherit;
    font-weight: 600;
    font-weight: 400;
    font-size: 2.4rem;
    margin: 0.8rem 0 2rem;
  }
  .next > p {
    color: var(--muted);
    line-height: 1.7;
  }
  button {
    background: transparent;
    border: 0;
    padding: 0;
    color: inherit;
    font: inherit;
    text-align: left;
  }
  h3 {
    font-size: 1rem;
    margin-bottom: 0.4rem;
  }
  [role='alert'] {
    color: #9b482e;
  }
</style>

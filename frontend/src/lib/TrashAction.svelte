<script lang="ts">
  import { onMount } from 'svelte';
  import { json, type Book } from './api';
  import type { components } from './schema';
  type Operation = components['schemas']['TrashOperationOut'];
  let {
    book,
    onupdate,
    beforeTrash = async () => {},
  }: {
    book: Book;
    onupdate: (book: Book) => void;
    beforeTrash?: () => Promise<void>;
  } = $props();
  let operation = $state<Operation | null>(null);
  let busy = $state(false);
  let error = $state('');
  let active = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let controller: AbortController | undefined;
  let sequence = 0;
  let completedRevision = '';
  const managed = $derived(
    book.editions.some((edition) =>
      edition.representations.some((rep) => rep.assets.some((asset) => asset.root === 'managed')),
    ),
  );
  onMount(() => {
    active = true;
    if (book.trashed_at) void load();
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
    const id = book.id;
    try {
      const result = await json<Operation | null>(`/works/${id}/trash`, {
        signal: controller.signal,
      });
      if (!active || current !== sequence || book.id !== id) return;
      operation = result;
      if (result?.state === 'complete' && completedRevision !== `${result.id}:${result.revision}`) {
        const restored = await json<Book>(`/works/${id}`, { signal: controller.signal });
        if (active && current === sequence && book.id === id) {
          completedRevision = `${result.id}:${result.revision}`;
          onupdate(restored);
        }
      }
    } catch (cause) {
      if (active && current === sequence && !controller.signal.aborted) error = String(cause);
    } finally {
      if (
        active &&
        current === sequence &&
        operation &&
        ['queued', 'running'].includes(operation.state)
      )
        timer = setTimeout(load, 1000);
    }
  }
  async function change(action: 'trash' | 'restore' | 'retry') {
    busy = true;
    error = '';
    const id = book.id;
    try {
      if (action === 'trash') await beforeTrash();
      if (!active || id !== book.id) return;
      const path =
        action === 'retry' ? `/trash/operations/${operation!.id}/retry` : `/works/${id}/trash`;
      const result = await json<Operation>(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(
          action === 'retry'
            ? { revision: operation!.revision }
            : { action, revision: book.revision },
        ),
      });
      if (!active || id !== book.id) return;
      operation = result;
      const updated = await json<Book>(`/works/${id}`);
      if (!active || id !== book.id) return;
      onupdate(updated);
      await load();
    } catch (cause) {
      if (active && id === book.id) {
        error = String(cause);
        const updated = await json<Book>(`/works/${id}`).catch(() => null);
        if (active && id === book.id && updated) onupdate(updated);
      }
    } finally {
      busy = false;
    }
  }
</script>

<section class="trash-action" aria-label="Recoverable removal">
  {#if book.trashed_at}
    <h3>In Trash</h3>
    <p>
      Your metadata, collections and reading history are kept. {managed
        ? 'Owned originals remain recoverable.'
        : 'Source files stay in their original location.'}
    </p>
    {#if operation}
      <p class="progress" aria-live="polite">
        {operation.action === 'restore' ? 'Restoring' : 'Moving to Trash'} · {operation.state} · {operation.completed}
        of {operation.total} managed originals
      </p>
      {#if operation.error}<p class="error" role="alert">{operation.error}</p>{/if}
      {#if operation.state === 'error'}<button
          class="secondary"
          disabled={busy}
          onclick={() => change('retry')}>Retry relocation</button
        >
      {:else if operation.state === 'complete' && operation.action === 'trash'}<button
          class="primary"
          disabled={busy}
          onclick={() => change('restore')}>Restore book</button
        >{/if}
    {:else}<p>Loading recovery details…</p>{/if}
  {:else}
    <details>
      <summary>Remove from your catalog</summary>
      <p>
        {managed
          ? 'Move owned originals to recoverable Trash and hide this book from browsing.'
          : 'Hide this registration from browsing. Its source files will stay untouched.'} Your notes,
        collections and reading history will be kept.
      </p>
      <button class="secondary" disabled={busy} onclick={() => change('trash')}
        >Move to Trash</button
      >
    </details>
  {/if}
  {#if error}<p class="error" role="alert">{error}</p>{/if}
</section>

<style>
  .trash-action {
    margin-top: 1.5rem;
    padding-top: 1.2rem;
    border-top: 1px solid var(--line);
  }
  h3 {
    margin: 0 0 0.5rem;
  }
  p {
    color: var(--muted);
    font-size: 0.9rem;
    line-height: 1.6;
  }
  summary {
    cursor: pointer;
    color: var(--muted);
  }
  .progress {
    font-variant-numeric: tabular-nums;
  }
  .error {
    color: #a33129;
  }
</style>

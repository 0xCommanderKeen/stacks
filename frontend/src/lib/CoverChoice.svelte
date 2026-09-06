<script lang="ts">
  import { onDestroy } from 'svelte';
  import { json, type Book } from './api';
  let { book, onupdate }: { book: Book; onupdate: (book: Book) => void } = $props();
  let file = $state<File | null>(null);
  let preview = $state('');
  let revision = 0;
  let busy = $state(false);
  let error = $state('');
  let active = true;
  $effect(() => {
    const url = file ? URL.createObjectURL(file) : '';
    preview = url;
    return () => {
      if (url) URL.revokeObjectURL(url);
    };
  });
  onDestroy(() => {
    active = false;
  });
  function select(event: Event) {
    error = '';
    const selected = (event.currentTarget as HTMLInputElement).files?.[0] || null;
    if (selected && selected.size > 10 * 1024 * 1024) {
      error = 'Choose a cover smaller than 10 MiB.';
      file = null;
      return;
    }
    file = selected;
    revision = book.revision;
  }
  async function save(reset = false) {
    busy = true;
    error = '';
    try {
      const result = await json<Book>(
        `/works/${book.id}/cover?revision=${reset ? book.revision : revision}`,
        reset
          ? { method: 'DELETE' }
          : {
              method: 'POST',
              headers: { 'Content-Type': 'application/octet-stream' },
              body: file,
            },
      );
      if (active) {
        file = null;
        onupdate(result);
      }
    } catch (cause) {
      if (active) error = String(cause);
    } finally {
      busy = false;
    }
  }
</script>

<details class="choice">
  <summary>Choose a cover</summary>
  <p>
    Your chosen cover stays with this work. The original image is included in your Stacks backup.
  </p>
  {#if error}<p role="alert">{error}</p>{/if}
  <label for="custom-cover">Cover image</label>
  <input
    id="custom-cover"
    type="file"
    accept="image/jpeg,image/png,image/webp"
    onchange={select}
    disabled={busy}
  />
  <p class="hint">JPEG, PNG or WebP · up to 10 MiB and 12 million pixels</p>
  {#if file && preview}
    <div class="preview">
      <img src={preview} alt="Preview of your chosen cover" />
      <div>
        <p>{file.name}</p>
        <button class="primary" disabled={busy} onclick={() => save()}>Use this cover</button>
      </div>
    </div>
  {/if}
  {#if book.selected_cover_id}
    <div class="saved">
      <span>Chosen by you</span><a href="/api/works/{book.id}/cover/original"
        >Download chosen image</a
      >
      <button class="secondary" disabled={busy} onclick={() => save(true)}
        >Use embedded cover</button
      >
    </div>
  {/if}
</details>

<style>
  .choice {
    border-top: 1px solid var(--line);
    padding: 1.1rem 0;
    margin-top: 1rem;
  }
  summary {
    cursor: pointer;
    font-weight: 500;
  }
  p {
    color: var(--muted);
    line-height: 1.6;
    overflow-wrap: anywhere;
  }
  label {
    display: block;
    margin: 1rem 0 0.5rem;
  }
  input {
    max-width: 100%;
    font: inherit;
  }
  .hint {
    font-size: 0.8rem;
  }
  .preview {
    display: flex;
    flex-wrap: wrap;
    gap: 1.5rem;
    align-items: center;
    margin: 1.2rem 0;
  }
  img {
    width: 100px;
    max-height: 180px;
    object-fit: contain;
  }
  .saved {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 1rem;
    margin-top: 1rem;
    font-size: 0.85rem;
  }
  a {
    color: var(--ink);
  }
  [role='alert'] {
    color: #9b482e;
  }
</style>

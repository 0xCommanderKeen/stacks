<script lang="ts">
  import type { Book } from './api';
  let { book, large = false }: { book: Book; large?: boolean } = $props();
  let failed = $state(false);
  const representation = $derived(book.editions[0]?.representations[0]);
  const tone = $derived(book.title.split('').reduce((sum, ch) => sum + ch.charCodeAt(0), 0) % 5);
</script>

<div class:large class="cover tone-{tone}">
  {#if representation?.has_cover && !failed}
    <img
      src="/api/representations/{representation.id}/cover"
      alt="Cover of {book.title}"
      loading="lazy"
      onerror={() => (failed = true)}
    />
  {:else}
    <div class="cover-type">
      <span class="cover-rule"></span><span class="cover-author"
        >{book.authors[0] || 'A BOOK FROM YOUR LIBRARY'}</span
      ><span class="cover-title">{book.title}</span><span class="cover-bottom"
        >STACKS · {representation?.format.toUpperCase() || 'BOOK'}</span
      >
    </div>
  {/if}
</div>

<style>
  .cover {
    aspect-ratio: 2 / 3;
    position: relative;
    overflow: hidden;
    background: #304e46;
    color: #f6eedc;
    box-shadow: 3px 5px 8px #252c2020;
    border-radius: 1px 4px 4px 1px;
  }
  .cover::after {
    content: '';
    position: absolute;
    inset: 0;
    pointer-events: none;
    box-shadow:
      inset 5px 0 5px #0002,
      inset 7px 0 0 #ffffff09;
  }
  .cover img {
    width: 100%;
    height: 100%;
    object-fit: cover;
  }
  .cover-type {
    position: absolute;
    inset: 11% 13%;
    display: flex;
    flex-direction: column;
  }
  .cover-rule {
    height: 3px;
    background: currentColor;
    margin-bottom: 16%;
    opacity: 0.65;
  }
  .cover-author {
    font-size: 9px;
    letter-spacing: 0.13em;
    text-transform: uppercase;
    line-height: 1.6;
  }
  .cover-title {
    font-family: Georgia, serif;
    font-size: clamp(19px, 2.3vw, 30px);
    line-height: 1.15;
    margin-top: 12%;
    overflow: hidden;
    overflow-wrap: anywhere;
  }
  .cover-bottom {
    margin-top: auto;
    padding-top: 10px;
    font-size: 8px;
    letter-spacing: 0.16em;
  }
  .tone-1 {
    background: #9b482e;
  }
  .tone-2 {
    background: #c4a155;
    color: #332c22;
  }
  .tone-3 {
    background: #384e61;
  }
  .tone-4 {
    background: #6f555b;
  }
  .large .cover-title {
    font-size: clamp(28px, 4vw, 40px);
  }
</style>

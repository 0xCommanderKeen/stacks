<script lang="ts">
  import { onMount } from 'svelte';
  import Cover from '$lib/Cover.svelte';
  import Organization from '$lib/Organization.svelte';
  import CatalogGroups from '$lib/CatalogGroups.svelte';
  import AudioPlayer from '$lib/AudioPlayer.svelte';
  import Personal from '$lib/Personal.svelte';
  import Inbox from '$lib/Inbox.svelte';
  import SourceRoots from '$lib/SourceRoots.svelte';
  import OriginalStatus from '$lib/OriginalStatus.svelte';
  import RunBrowser from '$lib/RunBrowser.svelte';
  import Collections from '$lib/Collections.svelte';
  import CollectionNext from '$lib/CollectionNext.svelte';
  import FollowedNext from '$lib/FollowedNext.svelte';
  import type { components } from '$lib/schema';
  import {
    ApiError,
    json,
    request,
    saveBlob,
    type Book,
    type Page,
    type ImportResult,
    type Status,
  } from '$lib/api';

  let ready = $state(false);
  let signedIn = $state(false);
  let password = $state('');
  let error = $state('');
  let notice = $state('');
  let busy = $state('');
  let books = $state<Book[]>([]);
  let total = $state(0);
  let q = $state('');
  let appliedQuery = $state('');
  let scope = $state('library');
  let medium = $state('');
  let seriesId = $state('');
  let runOffset = $state(0);
  let unassigned = $state(false);
  let nextOffset = $state(0);
  let collectionId = $state('');
  let collectionOffset = $state(0);
  let collectionListOffset = $state(0);
  let collectionNextOffset = $state(0);
  let offset = $state(0);
  let selected = $state<Book | null>(null);
  let view = $state<'library' | 'settings' | 'home' | 'collections' | 'inbox'>('library');
  let continuing = $state<components['schemas']['ContinuePage'] | null>(null);
  let homeOffset = $state(0);
  let player = $state<{
    start: (id: string, play?: boolean) => Promise<void>;
    flush: () => Promise<void>;
    pauseAndFlush: () => Promise<void>;
  }>(null!);
  async function loadHome(nextOffset = homeOffset) {
    continuing = await json<components['schemas']['ContinuePage']>(
      `/home/continue?offset=${nextOffset}`,
    );
    homeOffset = nextOffset;
  }
  async function showHome() {
    selected = null;
    view = 'home';
    setUrl();
    await loadHome().catch(fail);
  }
  let editing = $state(false);
  let editTitle = $state('');
  let editAuthors = $state('');
  let editDescription = $state('');
  let status = $state<Status | null>(null);
  let upload = $state<HTMLInputElement>(null!);
  let loadSequence = 0;
  const pageSize = 24;

  function fail(cause: unknown) {
    if (cause instanceof ApiError && cause.status === 401) signedIn = false;
    error = cause instanceof Error ? cause.message : 'Something went wrong.';
  }

  async function load(nextOffset = offset, query = appliedQuery) {
    const sequence = ++loadSequence;
    if (medium === 'comic' && !unassigned) {
      appliedQuery = query;
      offset = nextOffset;
      status = await json<Status>('/status');
      return;
    }
    let result = await json<Page>(
      `/catalog?q=${encodeURIComponent(query)}&limit=${pageSize}&offset=${nextOffset}&scope=${scope}${medium ? '&medium=' + medium : ''}${unassigned ? '&unassigned=true' : ''}`,
    );
    if (sequence !== loadSequence) return;
    if (!result.items.length && nextOffset > 0) {
      nextOffset = result.total ? Math.floor((result.total - 1) / pageSize) * pageSize : 0;
      if (result.total) {
        result = await json<Page>(
          `/catalog?q=${encodeURIComponent(query)}&limit=${pageSize}&offset=${nextOffset}&scope=${scope}${medium ? '&medium=' + medium : ''}${unassigned ? '&unassigned=true' : ''}`,
        );
        if (sequence !== loadSequence) return;
      }
      const params = new URLSearchParams(location.search);
      if (nextOffset) params.set('offset', String(nextOffset));
      else params.delete('offset');
      history.replaceState({}, '', params.size ? `?${params}` : location.pathname);
    }
    books = result.items;
    total = result.total;
    offset = nextOffset;
    appliedQuery = query;
    status = await json<Status>('/status');
  }

  async function openFromUrl() {
    const params = new URLSearchParams(location.search);
    collectionId = params.get('collection') || '';
    for (const key of ['collection_offset', 'collection_list_offset', 'collection_next_offset']) {
      const value = Number(params.get(key) || 0);
      const safe = Number.isSafeInteger(value) && value >= 0 ? value : 0;
      if (key === 'collection_offset') collectionOffset = safe;
      else if (key === 'collection_list_offset') collectionListOffset = safe;
      else collectionNextOffset = safe;
    }
    q = params.get('q') || '';
    medium = ['ebook', 'comic', 'audio'].includes(params.get('media') || '')
      ? params.get('media')!
      : '';
    seriesId = medium === 'comic' ? params.get('series') || '' : '';
    unassigned = medium === 'comic' && params.get('unassigned') === '1';
    const runs = Number(params.get('run_offset') || 0);
    runOffset = Number.isSafeInteger(runs) && runs >= 0 ? runs : 0;
    const next = Number(params.get('next_offset') || 0);
    nextOffset = Number.isSafeInteger(next) && next >= 0 ? next : 0;
    scope = ['all', 'library', 'archive'].includes(params.get('scope') || '')
      ? params.get('scope')!
      : 'library';
    const requestedOffset = Number(params.get('offset') || 0);
    offset = Number.isSafeInteger(requestedOffset) && requestedOffset >= 0 ? requestedOffset : 0;
    view =
      params.get('view') === 'settings'
        ? 'settings'
        : params.get('view') === 'home'
          ? 'home'
          : params.get('view') === 'collections'
            ? 'collections'
            : params.get('view') === 'inbox'
              ? 'inbox'
              : 'library';
    const continuationOffset = Number(params.get('continue_offset') || 0);
    homeOffset =
      Number.isSafeInteger(continuationOffset) && continuationOffset >= 0 ? continuationOffset : 0;
    selected = null;
    editing = false;
    await load(offset, q);
    if (view === 'home') await loadHome();
    if (params.get('book'))
      selected = await json<Book>(`/works/${encodeURIComponent(params.get('book')!)}`);
  }

  onMount(() => {
    void (async () => {
      try {
        await request('/session');
        signedIn = true;
        await openFromUrl();
      } catch (cause) {
        if (!(cause instanceof ApiError && cause.status === 401)) fail(cause);
      } finally {
        ready = true;
      }
    })();
    const navigate = () => {
      void openFromUrl().catch(fail);
    };
    window.addEventListener('popstate', navigate);
    return () => window.removeEventListener('popstate', navigate);
  });

  function setUrl() {
    const params = new URLSearchParams();
    if (collectionId) params.set('collection', collectionId);
    if (collectionOffset) params.set('collection_offset', String(collectionOffset));
    if (collectionListOffset) params.set('collection_list_offset', String(collectionListOffset));
    if (collectionNextOffset) params.set('collection_next_offset', String(collectionNextOffset));
    if (medium) params.set('media', medium);
    if (seriesId) params.set('series', seriesId);
    if (unassigned) params.set('unassigned', '1');
    if (runOffset) params.set('run_offset', String(runOffset));
    if (view === 'home' && nextOffset) params.set('next_offset', String(nextOffset));
    if (scope !== 'library') params.set('scope', scope);
    if (appliedQuery) params.set('q', appliedQuery);
    if (offset) params.set('offset', String(offset));
    if (selected) params.set('book', selected.id);
    if (view !== 'library') params.set('view', view);
    if (view === 'home' && homeOffset) params.set('continue_offset', String(homeOffset));
    history.pushState({}, '', params.size ? `/?${params}` : '/');
  }

  async function signIn(event: SubmitEvent) {
    event.preventDefault();
    busy = 'login';
    error = '';
    try {
      await request('/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password }),
      });
      signedIn = true;
      password = '';
      await openFromUrl();
    } catch (cause) {
      fail(cause);
    } finally {
      busy = '';
    }
  }

  async function signOut() {
    try {
      await player?.pauseAndFlush();
      await request('/logout', { method: 'POST' });
      signedIn = false;
      selected = null;
      books = [];
      notice = '';
    } catch (cause) {
      fail(cause);
    }
  }

  async function importFiles(event: Event) {
    const files = Array.from((event.target as HTMLInputElement).files || []);
    if (!files.length) return;
    error = '';
    notice = '';
    let added = 0;
    let duplicates = 0;
    try {
      for (const [index, file] of files.entries()) {
        busy = `Importing ${index + 1} of ${files.length}…`;
        const result = await json<ImportResult>('/import', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/octet-stream',
            'X-Filename': encodeURIComponent(file.name),
          },
          body: file,
        });
        if (result.duplicate) duplicates++;
        else added++;
      }
      notice = `${added} ${added === 1 ? 'book' : 'books'} added${duplicates ? ` · ${duplicates} already in your library` : ''}.`;
    } catch (cause) {
      fail(cause);
      notice = `${added} added before the import stopped. You can retry safely.`;
    } finally {
      busy = '';
      upload.value = '';
      q = '';
      appliedQuery = '';
      offset = 0;
      selected = null;
      view = 'library';
      setUrl();
      await load().catch(fail);
    }
  }

  async function changeMedia(value: string) {
    medium = value;
    seriesId = '';
    runOffset = 0;
    offset = 0;
    unassigned = false;
    q = '';
    appliedQuery = '';
    setUrl();
    await load().catch(fail);
  }

  async function search(event: SubmitEvent) {
    event.preventDefault();
    error = '';
    selected = null;
    runOffset = 0;
    try {
      await load(0, q);
      setUrl();
    } catch (cause) {
      fail(cause);
    }
  }

  async function paginate(nextOffset: number) {
    try {
      await load(nextOffset);
      q = appliedQuery;
      setUrl();
    } catch (cause) {
      fail(cause);
    }
  }

  function open(book: Book) {
    if (view !== 'collections') view = 'library';
    selected = book;
    editing = false;
    error = '';
    notice = '';
    setUrl();
    window.scrollTo(0, 0);
  }
  function libraryView() {
    selected = null;
    editing = false;
    view = 'library';
    setUrl();
  }
  function startEdit() {
    if (!selected) return;
    editTitle = selected.title;
    editAuthors = selected.authors.join('\n');
    editDescription = selected.description;
    editing = true;
  }
  async function save(event: SubmitEvent) {
    event.preventDefault();
    if (!selected) return;
    busy = 'save';
    error = '';
    try {
      selected = await json<Book>(`/works/${selected.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          revision: selected.revision,
          title: editTitle,
          authors: editAuthors.split('\n'),
          description: editDescription,
        }),
      });
      editing = false;
      notice = 'Book details saved.';
      await load();
    } catch (cause) {
      fail(cause);
    } finally {
      busy = '';
    }
  }
  async function makeBackup() {
    busy = 'backup';
    error = '';
    try {
      saveBlob(await (await request('/backup', { method: 'POST' })).blob(), 'stacks.backup.zip');
      notice = 'Your library backup is ready. Registered originals need separate protection.';
    } catch (cause) {
      fail(cause);
    } finally {
      busy = '';
    }
  }
  function formats(book: Book) {
    return [
      ...new Set(
        book.editions.flatMap((e) => e.representations.map((r) => r.format.toUpperCase())),
      ),
    ].join(' · ');
  }
  function bytes(size: number) {
    return size > 1024 * 1024
      ? `${(size / 1024 / 1024).toFixed(1)} MB`
      : `${Math.max(1, Math.round(size / 1024))} KB`;
  }
</script>

<svelte:head
  ><title>{selected ? `${selected.title} — Stacks` : 'Stacks — Your reading room'}</title><meta
    name="description"
    content="A little order for everything you love to read."
  /></svelte:head
>

{#if !ready}
  <main class="loading" aria-live="polite">Opening your library…</main>
{:else if !signedIn}
  <main class="login-shell">
    <div class="login-art" aria-hidden="true">
      <div class="large-wordmark">stacks<span>▰</span></div>
      <div class="spines"><i></i><i></i><i></i><i></i><i></i><i></i><i></i></div>
      <p>A place for the books<br />you come back to.</p>
      <span class="eyebrow">YOUR OWN READING ROOM</span>
    </div>
    <div class="login-form">
      <div class="eyebrow">WELCOME TO STACKS</div>
      <h1>Make yourself<br /><em>at home.</em></h1>
      <p class="muted">Your library is waiting.</p>
      <form onsubmit={signIn}>
        <label for="password">Library password</label><input
          id="password"
          type="password"
          bind:value={password}
          autocomplete="current-password"
          required
        /><button class="primary" disabled={!!busy}
          >{busy ? 'Opening…' : 'Open my library'} <span>↗</span></button
        >
      </form>
      {#if error}<p class="error" role="alert">{error}</p>{/if}
    </div>
  </main>
{:else}
  <a class="skip" href="#main">Skip to content</a>
  <header>
    <a
      class="wordmark"
      href="/"
      onclick={(event) => {
        event.preventDefault();
        libraryView();
      }}>stacks<span>▰</span></a
    >
    <nav aria-label="Main navigation">
      <button class:active={view === 'home'} onclick={showHome}>Home</button>
      <button class:active={view === 'library'} onclick={libraryView}>Library</button>
      <button
        class:active={view === 'inbox'}
        onclick={() => {
          selected = null;
          view = 'inbox';
          setUrl();
        }}>Inbox</button
      >
      <button
        class:active={view === 'collections'}
        onclick={() => {
          selected = null;
          view = 'collections';
          setUrl();
        }}>Collections</button
      ><button
        class:active={view === 'settings'}
        onclick={() => {
          view = 'settings';
          selected = null;
          setUrl();
        }}>Settings</button
      >
    </nav>
    <button class="signout" onclick={signOut}>Sign out <span>↗</span></button>
  </header>
  <main id="main" class="workspace">
    {#if error}<div class="message error" role="alert">
        {error}<button aria-label="Dismiss error" onclick={() => (error = '')}>×</button>
      </div>{/if}
    {#if notice}<div class="message success" role="status">
        {notice}<button aria-label="Dismiss notification" onclick={() => (notice = '')}>×</button>
      </div>{/if}
    {#if status?.import_errors}<div class="message error">
        {status.import_errors} interrupted import(s) need attention. Check storage, then restart Stacks
        to retry recovery. Original copies are retained.
      </div>{/if}
    {#if view === 'home'}
      <div class="eyebrow">PICK UP WHERE YOU LEFT OFF</div>
      <h1>A little more <em>listening.</em></h1>
      <p class="intro">Your place is here when you come back.</p>
      {#if continuing?.items.length}
        <div class="book-grid">
          {#each continuing.items as item}<div class="book">
              <button
                class="cover-button"
                aria-label="Open {item.work.title}"
                onclick={() => open(item.work)}><Cover book={item.work} /></button
              >
              <div class="book-caption">
                <h2>{item.work.title}</h2>
                <p>{item.work.authors.join(' · ')}</p>
              </div>
              <button class="secondary" onclick={() => player.start(item.representation_id)}
                >Continue {item.work.title}</button
              >
            </div>{/each}
        </div>
        {#if continuing.total > continuing.limit}<div class="pagination">
            <button
              class="secondary"
              disabled={homeOffset === 0}
              onclick={async () => {
                await loadHome(Math.max(0, homeOffset - continuing!.limit));
                setUrl();
              }}>← Previous</button
            ><span
              >{homeOffset + 1}–{Math.min(homeOffset + continuing.limit, continuing.total)} of {continuing.total}</span
            ><button
              class="secondary"
              disabled={homeOffset + continuing.limit >= continuing.total}
              onclick={async () => {
                await loadHome(homeOffset + continuing!.limit);
                setUrl();
              }}>Next →</button
            >
          </div>{/if}
      {:else}<section class="empty">
          <h2>Your next chapter is waiting.</h2>
          <p>Start an audiobook in your library. Its saved place will appear here.</p>
          <button class="secondary" onclick={libraryView}>Browse library</button>
        </section>{/if}
      <FollowedNext
        onopen={(book, id) => {
          medium = book.editions.some((e) => e.medium === 'comic') ? 'comic' : '';
          seriesId = medium === 'comic' ? id : '';
          offset = 0;
          runOffset = 0;
          unassigned = false;
          q = '';
          appliedQuery = '';
          open(book);
        }}
        bind:offset={nextOffset}
        onnavigate={setUrl}
      />
      <CollectionNext
        bind:offset={collectionNextOffset}
        onnavigate={setUrl}
        onopen={(book, id) => {
          collectionId = id;
          collectionOffset = 0;
          view = 'collections';
          open(book);
        }}
      />
    {:else if view === 'collections' && !selected}
      <Collections
        bind:id={collectionId}
        bind:offset={collectionOffset}
        bind:listOffset={collectionListOffset}
        onopen={open}
        onnavigate={setUrl}
      />
    {:else if view === 'inbox'}
      <Inbox onopen={open} />
    {:else if view === 'settings'}
      <div class="eyebrow">LOOK AFTER YOUR LIBRARY</div>
      <h1>Keep it <em>safe.</em></h1>
      <p class="intro">Your books and your choices belong to you.</p>
      <div class="settings-grid">
        <section class="settings-card">
          <span class="index">01</span>
          <h2>Library backup</h2>
          <p>
            Save your catalog, covers, and Stacks-owned original files together. Registered source
            originals are not included; protect them separately. Keep this backup on separate
            storage.
          </p>
          <button class="primary" onclick={makeBackup} disabled={!!busy}
            >{busy === 'backup' ? 'Preparing backup…' : 'Download backup'} <span>↓</span></button
          >
          <p class="small muted">
            Restore into a new data directory using the documented Stacks restore command.
          </p>
        </section>
        <section class="settings-card">
          <span class="index">02</span>
          <h2>Catalog export</h2>
          <p>
            Take your book details and file references with you in an open JSON format. This export
            contains no original files.
          </p>
          <a class="button secondary" href="/api/export" download>Export catalog <span>↓</span></a>
        </section>
      </div>
      <SourceRoots onopen={open} />
    {:else if selected}
      <button
        class="back"
        onclick={() => {
          if (view === 'collections') {
            selected = null;
            editing = false;
            setUrl();
          } else libraryView();
        }}>← Back to {view === 'collections' ? 'collection' : 'library'}</button
      >
      <div class="detail">
        <div class="detail-cover"><Cover book={selected} large /></div>
        <section class="detail-copy">
          <div class="eyebrow">
            IN YOUR {selected.personal.shelf === 'archive' ? 'ARCHIVE' : 'LIBRARY'} · {formats(
              selected,
            )}
          </div>
          {#if editing}
            <form onsubmit={save} class="edit-form">
              <h1>Edit book</h1>
              <label for="title">Title</label><input
                id="title"
                bind:value={editTitle}
                maxlength="1024"
                required
              /><label for="authors">Authors <span class="muted">— one per line</span></label
              ><textarea id="authors" bind:value={editAuthors} rows="2"></textarea><label
                for="description">Description</label
              ><textarea id="description" bind:value={editDescription} rows="7" maxlength="20000"
              ></textarea>
              <div class="actions">
                <button class="primary" disabled={!!busy}>Save details</button><button
                  type="button"
                  class="secondary"
                  onclick={() => (editing = false)}>Cancel</button
                >
              </div>
            </form>
          {:else}
            <h1>{selected.title}</h1>
            <p class="byline">{selected.authors.join(' · ') || 'Unknown author'}</p>
            <div class="actions">
              {#each selected.editions as edition}{#each edition.representations as representation}{#if representation.capabilities.includes('listen')}<button
                      class="primary"
                      onclick={() => player.start(representation.id)}
                      >Listen · {representation.format.toUpperCase()}{edition.narrator
                        ? ` · ${edition.narrator}`
                        : ''}</button
                    >{/if}{#each representation.assets as asset}<a
                      class="button primary"
                      href="/api/assets/{asset.id}/download"
                      download
                      >Download {representation.format.toUpperCase()}{representation.assets.length >
                      1
                        ? ` · ${asset.original_name}`
                        : ''} <span>↓</span></a
                    >{/each}{/each}{/each}<button class="secondary" onclick={startEdit}
                >Edit details</button
              >
            </div>
            <p class="description">
              {selected.description ||
                'A good book needs no introduction. Add a description to make this one easier to find again.'}
            </p>
            <OriginalStatus book={selected} />
            <Organization
              book={selected}
              onupdate={(book) => {
                selected = book;
                void load().catch(fail);
              }}
            />
            {#key selected.id}<CatalogGroups
                book={selected}
                onchange={async (id) => {
                  selected = await json<Book>(`/works/${id}`);
                  await load();
                  setUrl();
                }}
              />{/key}
            {#key selected.id}<Personal
                book={selected}
                onupdate={(book) => {
                  selected = book;
                  void load().catch(fail);
                }}
              />{/key}
            <dl class="book-facts">
              <div>
                <dt>Language</dt>
                <dd>{selected.editions[0]?.language || 'Not specified'}</dd>
              </div>
              <div>
                <dt>Publisher</dt>
                <dd>{selected.editions[0]?.publisher || 'Not specified'}</dd>
              </div>
              <div>
                <dt>File size</dt>
                <dd>{bytes(selected.editions[0]?.representations[0]?.assets[0]?.size || 0)}</dd>
              </div>
              <div>
                <dt>Added</dt>
                <dd>
                  {new Date(selected.created_at).toLocaleDateString(undefined, {
                    day: 'numeric',
                    month: 'short',
                    year: 'numeric',
                  })}
                </dd>
              </div>
            </dl>
          {/if}
        </section>
      </div>
    {:else}
      <div class="page-heading" class:compact={!!medium}>
        <div>
          <div class="eyebrow">YOUR OWN READING ROOM</div>
          {#if medium}<h1>
              {medium === 'comic'
                ? 'Comic runs.'
                : medium === 'audio'
                  ? 'Your listening shelf.'
                  : 'Your books.'}
            </h1>{:else}<h1>Good books.<br /><em>All in one place.</em></h1>{/if}
        </div>
        <div class="heading-aside">
          <p>A little order for<br />everything you love to read.</p>
          <button class="primary" onclick={() => upload.click()} disabled={!!busy}
            >{busy.startsWith('Importing') ? busy : '+ Add books'}</button
          ><input
            class="file-input"
            bind:this={upload}
            type="file"
            accept=".epub,.pdf,.cbz,.cbr,.mp3,.m4a,.m4b"
            multiple
            onchange={importFiles}
            aria-label="Choose publications"
          /><span class="small muted">Books, comics & audio · originals kept intact</span>
        </div>
      </div>
      <div class="media-tabs" role="group" aria-label="Publication type">
        {#each [['', 'Everything'], ['ebook', 'Books'], ['comic', 'Comics'], ['audio', 'Audio']] as [value, label]}<button
            class:active={medium === value}
            onclick={() => changeMedia(value)}>{label}</button
          >{/each}
      </div>
      {#if unassigned}<button
          class="back"
          onclick={async () => {
            unassigned = false;
            offset = 0;
            setUrl();
            await load().catch(fail);
          }}>← All comic runs</button
        >{/if}
      <div class="catalog-toolbar">
        <div class="catalog-count">Your books <span>{status?.books || 0}</span></div>
        <label class="scope-selector"
          >Browse<select
            aria-label="Library scope"
            bind:value={scope}
            onchange={async () => {
              offset = 0;
              runOffset = 0;
              setUrl();
              await load().catch(fail);
            }}
            ><option value="library">Library shelf</option><option value="archive">Archive</option
            ><option value="all">Everything owned</option></select
          ></label
        >
        {#if !seriesId}<form class="search" onsubmit={search}>
            <label class="sr-only" for="search"
              >{medium === 'comic' && !unassigned
                ? 'Search comic runs'
                : 'Search books or authors'}</label
            ><input
              id="search"
              type="search"
              placeholder={medium === 'comic' && !unassigned
                ? 'Find a series or run…'
                : 'Find a book or author…'}
              bind:value={q}
            /><button type="submit" aria-label="Search">↵</button>
          </form>{/if}
      </div>
      {#if medium === 'comic' && !unassigned}
        <RunBrowser
          {scope}
          query={appliedQuery}
          bind:seriesId
          bind:runOffset
          bind:offset
          onopen={open}
          onnavigate={setUrl}
          onunassigned={async () => {
            unassigned = true;
            seriesId = '';
            offset = 0;
            setUrl();
            await load().catch(fail);
          }}
        />
      {:else if !books.length}
        <section class="empty">
          <div class="empty-mark" aria-hidden="true">▥</div>
          <h2>
            {appliedQuery
              ? 'No books found.'
              : scope === 'archive'
                ? 'Your archive is empty.'
                : 'Nothing on this shelf yet.'}
          </h2>
          <p>
            {appliedQuery
              ? 'Try a different title or author.'
              : 'Add a publication or choose Everything owned to search across your shelves.'}
          </p>
          {#if !appliedQuery}<button
              class="secondary"
              onclick={() => upload.click()}
              disabled={!!busy}>Add your first book ↗</button
            >{/if}
        </section>
      {:else}
        {#if appliedQuery}<p class="search-summary">
            {total}
            {total === 1 ? 'result' : 'results'} for “{appliedQuery}”
          </p>{/if}
        <div class="book-grid">
          {#each books as book (book.id)}<button
              class="book"
              onclick={() => open(book)}
              aria-label="Open {book.title}"
              ><Cover {book} />
              <div class="book-caption">
                <h2>{book.title}</h2>
                <p>{book.authors.join(', ') || 'Unknown author'}</p>
                <span>{formats(book)}</span>
              </div></button
            >{/each}
        </div>
        {#if total > pageSize}<div class="pagination">
            <button
              class="secondary"
              disabled={offset === 0}
              onclick={() => paginate(Math.max(0, offset - pageSize))}>← Previous</button
            ><span>{offset + 1}–{Math.min(offset + pageSize, total)} of {total}</span><button
              class="secondary"
              disabled={offset + pageSize >= total}
              onclick={() => paginate(offset + pageSize)}>Next →</button
            >
          </div>{/if}
      {/if}
    {/if}
    <footer><span>STACKS</span><span>A library, on your terms.</span></footer>
  </main>
  <AudioPlayer
    bind:this={player}
    onopen={(id) => {
      void json<Book>(`/works/${id}`).then(open).catch(fail);
    }}
  />
{/if}

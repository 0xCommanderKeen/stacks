<script lang="ts">
  import { onMount, tick } from 'svelte';
  import { ApiError, json } from './api';
  import type { components } from './schema';
  type Playback = components['schemas']['PlaybackOut'];
  type Progress = components['schemas']['ProgressOut'];
  let { onopen }: { onopen: (workId: string) => void } = $props();
  let data = $state<Playback | null>(null);
  let audio = $state<HTMLAudioElement>(null!);
  let index = $state(0);
  let position = $state(0);
  let speed = $state(1);
  let playing = $state(false);
  let loading = $state(false);
  let unavailable = $state(false);
  let error = $state('');
  let conflicted = $state(false);
  let dirty = $state(false);
  let savingNow = $state(false);
  let completed = false;
  let pendingSeek = 0;
  let autoplay = false;
  let saving: Promise<void> | null = null;
  let generation = 0;
  const track = $derived(data?.tracks[index]);

  export async function flush() {
    while (saving) await saving;
    if (!data || !track || !dirty || conflicted || loading) return;
    dirty = false;
    const representation = data.representation_id;
    const payload = {
      revision: data.progress.revision,
      asset_id: track.asset_id,
      position: Math.min(position, track.duration),
      speed,
      completed,
    };
    savingNow = true;
    saving = (async () => {
      try {
        const progress = await json<Progress>(`/representations/${representation}/progress`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        if (data?.representation_id === representation) data.progress = progress;
      } catch (cause) {
        if (cause instanceof ApiError && cause.status === 409) {
          conflicted = true;
          audio.pause();
        } else dirty = true;
        error = cause instanceof Error ? cause.message : 'Could not save listening position.';
      }
    })();
    try {
      await saving;
    } finally {
      saving = null;
      savingNow = false;
    }
  }

  export async function pauseAndFlush() {
    audio?.pause();
    await flush();
    if (dirty && !conflicted)
      throw new Error('Listening position is not saved. Retry before signing out.');
  }

  export async function releaseWork(workId: string) {
    if (data?.work_id !== workId) return;
    await pauseAndFlush();
    generation++;
    data = null;
  }

  export async function start(representationId: string, play = true) {
    const sequence = ++generation;
    audio?.pause();
    await flush();
    if (sequence !== generation || (dirty && !conflicted)) return;
    loading = true;
    unavailable = false;
    if (audio) audio.pause();
    error = '';
    try {
      const result = await json<Playback>(`/representations/${representationId}/playback`);
      if (sequence !== generation) return;
      data = result;
      conflicted = false;
      dirty = false;
      completed = false;
      index = result.progress.completed
        ? 0
        : Math.max(
            0,
            result.tracks.findIndex((t) => t.asset_id === result.progress.asset_id),
          );
      pendingSeek = result.progress.completed ? 0 : result.progress.position;
      position = pendingSeek;
      speed = result.progress.speed;
      autoplay = play;
      await tick();
      audio.load();
    } catch (cause) {
      if (sequence !== generation) return;
      error = String(cause);
      loading = false;
    }
  }
  async function loaded() {
    if (!track || !audio.currentSrc.endsWith(`/api/assets/${track.asset_id}/stream`)) return;
    audio.currentTime = Math.min(pendingSeek, track.duration);
    audio.playbackRate = speed;
    loading = false;
    unavailable = false;
    if (data && data.progress.asset_id !== track.asset_id) dirty = true;
    if (autoplay) {
      autoplay = false;
      try {
        await audio.play();
      } catch {
        error = 'Ready to listen. Press Play to begin.';
      }
    }
  }
  function moved() {
    if (loading || unavailable || !track) return;
    const latest = Math.min(audio.currentTime, track.duration);
    if (Math.abs(latest - position) > 0.01) dirty = true;
    position = latest;
  }
  async function toggle() {
    if (conflicted || loading || unavailable) return;
    if (audio.paused) {
      error = '';
      completed = false;
      try {
        await audio.play();
      } catch {
        error = 'This browser could not play the original. Try its download.';
      }
    } else {
      audio.pause();
      await flush();
    }
  }
  async function changeTrack(next: number, play = playing) {
    if (!data || next < 0 || next >= data.tracks.length) return;
    const sequence = ++generation;
    audio.pause();
    await flush();
    if (dirty || conflicted || sequence !== generation) return;
    loading = true;
    unavailable = false;
    audio.pause();
    index = next;
    position = 0;
    pendingSeek = 0;
    completed = false;
    dirty = false;
    error = '';
    autoplay = play;
    await tick();
    audio.load();
  }
  async function ended() {
    if (!data || !track) return;
    position = track.duration;
    dirty = true;
    if (index + 1 < data.tracks.length) await changeTrack(index + 1, true);
    else {
      completed = true;
      await flush();
    }
  }
  async function seek(value: number) {
    if (!track || loading || conflicted || unavailable) return;
    position = Math.max(0, Math.min(value, track.duration));
    audio.currentTime = position;
    completed = false;
    dirty = true;
    await flush();
  }
  async function rate() {
    if (loading || unavailable) return;
    audio.playbackRate = speed;
    dirty = true;
    await flush();
  }
  async function openWork() {
    if (!data) return;
    try {
      const representationId = data.representation_id;
      const current = await json<Playback>(`/representations/${representationId}/playback`);
      if (data?.representation_id !== representationId) return;
      data.work_id = current.work_id;
      data.title = current.title;
      onopen(current.work_id);
    } catch (cause) {
      error = String(cause);
    }
  }
  function time(seconds: number) {
    const whole = Math.floor(seconds);
    return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`;
  }
  onMount(() => {
    const timer = setInterval(() => {
      if (dirty) void flush();
    }, 5000);
    const hidden = () => {
      if (document.visibilityState === 'hidden') void flush();
    };
    document.addEventListener('visibilitychange', hidden);
    return () => {
      clearInterval(timer);
      document.removeEventListener('visibilitychange', hidden);
      audio?.pause();
    };
  });
</script>

{#if data && track}
  <section class="player" aria-label="Audiobook player">
    <audio
      bind:this={audio}
      src="/api/assets/{track.asset_id}/stream"
      preload="metadata"
      onloadedmetadata={loaded}
      ontimeupdate={moved}
      onended={ended}
      onplay={() => (playing = true)}
      onpause={() => {
        playing = false;
        if (!loading) void flush();
      }}
      onerror={() => {
        unavailable = true;
        loading = false;
        playing = false;
        error = 'The audio could not be opened. Check the original or try its download.';
      }}
    ></audio>
    <div class="player-title">
      <span class="eyebrow">NOW LISTENING</span><button onclick={openWork}>{data.title}</button
      ><small>{index + 1} / {data.tracks.length} · {track.title}</small>
    </div>
    <div class="transport">
      <button
        aria-label="Previous track"
        disabled={index === 0 || loading || conflicted}
        onclick={() => changeTrack(index - 1)}>↤</button
      >
      <button
        class="play"
        disabled={loading || conflicted || unavailable}
        aria-label={playing ? 'Pause audio' : 'Play audio'}
        onclick={toggle}>{playing ? 'Ⅱ' : '▶'}</button
      >
      <button
        aria-label="Next track"
        disabled={index + 1 === data.tracks.length || loading || conflicted}
        onclick={() => changeTrack(index + 1)}>↦</button
      >
      <span class="time">{time(position)} / {time(track.duration)}</span>
      <input
        aria-label="Listening position"
        type="range"
        min="0"
        max={track.duration}
        step="0.1"
        value={position}
        disabled={loading || conflicted || unavailable}
        oninput={(event) => seek(Number(event.currentTarget.value))}
      />
      <label
        >Speed<select
          bind:value={speed}
          onchange={rate}
          disabled={loading || conflicted || unavailable}
          ><option value={0.5}>0.5×</option><option value={0.75}>0.75×</option><option value={1}
            >1×</option
          ><option value={1.25}>1.25×</option><option value={1.5}>1.5×</option><option value={2}
            >2×</option
          ><option value={3}>3×</option></select
        ></label
      >
    </div>
    <div class="track-options">
      <span class="save-state"
        >{savingNow
          ? 'Saving place…'
          : dirty
            ? 'Listening…'
            : data.progress.revision
              ? 'Place saved'
              : 'Not started'}</span
      >
      <label
        >Track<select
          value={index}
          disabled={loading || conflicted}
          onchange={(event) => changeTrack(Number(event.currentTarget.value))}
          >{#each data.tracks as item, i}<option value={i}>{i + 1}. {item.original_name}</option
            >{/each}</select
        ></label
      >
      {#if track.chapters.length}<label
          >Chapter<select
            aria-label="Jump to chapter"
            value=""
            onchange={(event) => {
              if (event.currentTarget.value !== '') void seek(Number(event.currentTarget.value));
            }}
            ><option value="">Choose a chapter</option>{#each track.chapters as chapter}<option
                value={chapter.start}>{time(chapter.start)} · {chapter.title}</option
              >{/each}</select
          ></label
        >{/if}
      <a href="/api/assets/{track.asset_id}/download">Download original</a>
    </div>
    {#if error}<div class="player-error" role="alert">
        {error}{#if conflicted}<button onclick={() => start(data!.representation_id, false)}
            >Reload saved position</button
          >{/if}
      </div>{/if}
  </section>
{/if}

<style>
  .player {
    position: fixed;
    z-index: 20;
    bottom: 0;
    left: 0;
    right: 0;
    background: #293e35;
    color: #f5f0e3;
    padding: 1rem max(1.5rem, calc((100vw - 1320px) / 2));
    display: grid;
    grid-template-columns: minmax(160px, 1fr) 2fr;
    gap: 0.5rem 2rem;
    box-shadow: 0 -4px 20px #19251c20;
  }
  button {
    background: transparent;
    border: 0;
    color: inherit;
  }
  .player-title {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }
  .player-title button {
    color: inherit;
    text-align: left;
    font-family: Georgia, serif;
    font-size: 1.3rem;
    padding: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .player-title small {
    opacity: 0.7;
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
  }
  .transport {
    display: flex;
    align-items: center;
    gap: 0.7rem;
    min-width: 0;
  }
  .transport button {
    color: inherit;
    font-size: 1.3rem;
    padding: 0.4rem;
  }
  .transport .play {
    border: 1px solid #bbcabb;
    border-radius: 50%;
    width: 42px;
    height: 42px;
    flex-shrink: 0;
  }
  .transport input {
    flex: 1;
    min-width: 60px;
    accent-color: #ccb56f;
  }
  .time {
    font-variant-numeric: tabular-nums;
    font-size: 0.8rem;
    white-space: nowrap;
  }
  label {
    font-size: 0.75rem;
    display: flex;
    align-items: center;
    gap: 0.5rem;
    min-width: 0;
  }
  select {
    font: inherit;
    color: inherit;
    background: #344e41;
    border: 1px solid #829687;
    padding: 0.3rem;
    max-width: 100%;
  }
  .save-state {
    font-size: 0.7rem;
    opacity: 0.7;
  }
  .track-options {
    grid-column: 1/-1;
    display: flex;
    gap: 1rem;
    align-items: center;
    min-width: 0;
  }
  .track-options label {
    max-width: 40%;
  }
  a {
    font-size: 0.75rem;
    color: inherit;
    white-space: nowrap;
  }
  .player-error {
    grid-column: 1/-1;
    font-size: 0.85rem;
    color: #ffd4b6;
  }
  .player-error button {
    color: inherit;
    text-decoration: underline;
    padding-left: 0.5rem;
  }
  @media (max-width: 700px) {
    .player {
      grid-template-columns: 1fr;
      padding: 0.7rem 1rem;
      gap: 0.4rem;
    }
    .player-title {
      max-width: 100%;
    }
    .player-title small {
      display: none;
    }
    .transport {
      gap: 0.4rem;
    }
    .track-options {
      gap: 0.5rem;
      flex-wrap: wrap;
    }
    .track-options label {
      max-width: 45%;
    }
    .player-title .eyebrow {
      display: none;
    }
  }
</style>

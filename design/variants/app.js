const books = [
  [
    "The Shape of Silence",
    "Elena Marsh",
    "Book",
    "Currently reading",
    64,
    "#e0ebfa",
    "#17374d",
    "01",
  ],
  [
    "Orbit: The Arrival",
    "Jules Navarro",
    "Comic",
    "To read",
    0,
    "#f2633b",
    "#1c2434",
    "02",
  ],
  [
    "A Walk Through the Night",
    "Theo Rivers",
    "Audio",
    "Listening",
    38,
    "#21383d",
    "#d8f396",
    "03",
  ],
  [
    "Every Small Adventure",
    "Ada Bennett",
    "Book",
    "To read",
    0,
    "#ffd956",
    "#be4536",
    "04",
  ],
  [
    "The Last Observatory",
    "Mira Sol",
    "Comic",
    "To read",
    0,
    "#302e59",
    "#ecafa1",
    "05",
  ],
  [
    "Ways of Seeing Again",
    "Noah Finch",
    "Book",
    "Finished",
    100,
    "#f3e6d8",
    "#c3533b",
    "06",
  ],
  [
    "Between the Lines",
    "Iris Cole",
    "Audio",
    "To read",
    0,
    "#d8ccf0",
    "#43344b",
    "07",
  ],
  [
    "Elsewhere, Tomorrow",
    "Luca West",
    "Book",
    "To read",
    0,
    "#90b8be",
    "#123e4b",
    "08",
  ],
  [
    "City of Satellites",
    "Jules Navarro",
    "Comic",
    "To read",
    0,
    "#e8a39c",
    "#482a3e",
    "09",
  ],
  [
    "The Art of Paying Attention",
    "Ada Bennett",
    "Book",
    "Currently reading",
    21,
    "#ebe9df",
    "#244e4c",
    "10",
  ],
  [
    "Nothing Stays Still",
    "Elena Marsh",
    "Book",
    "To read",
    0,
    "#c14234",
    "#f2dfb3",
    "11",
  ],
  [
    "Slow Frequencies",
    "Theo Rivers",
    "Audio",
    "To read",
    0,
    "#aab4d8",
    "#26334c",
    "12",
  ],
].map(([title, author, type, state, progress, bg, ink, n], id) => ({
  id,
  title,
  author,
  type,
  state,
  progress,
  bg,
  ink,
  n,
}));
const icons = {
  library:
    '<rect x="3" y="4" width="4" height="16"/><rect x="10" y="4" width="4" height="16"/><path d="m17 5 4 14"/>',
  home: '<path d="m3 10 9-7 9 7v10H3Z"/><path d="M9 20v-7h6v7"/>',
  search: '<circle cx="10" cy="10" r="6"/><path d="m15 15 6 6"/>',
  inbox: '<path d="M4 4h16v16H4Z"/><path d="M4 13h5l1 3h4l1-3h5"/>',
  folder: '<path d="M3 6h7l2 3h9v11H3Z"/>',
  audio:
    '<path d="M4 14v-3a8 8 0 0 1 16 0v3"/><rect x="3" y="12" width="4" height="8" rx="2"/><rect x="17" y="12" width="4" height="8" rx="2"/>',
  settings:
    '<circle cx="12" cy="12" r="4"/><path d="M12 2v4m0 12v4M2 12h4m12 0h4M5 5l3 3m8 8 3 3M5 19l3-3m8-8 3-3"/>',
};
const icon = (name) =>
  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">${icons[name] || icons.library}</svg>`;
const esc = (s) =>
  s.replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
function cover(b) {
  const pattern = Number(b.n) % 4;
  return `<svg class="cover" viewBox="0 0 260 360" role="img" aria-label="${esc(b.title)} cover"><rect width="260" height="360" fill="${b.bg}"/><g fill="none" stroke="${b.ink}" stroke-width="${pattern === 1 ? 2 : 20}">${pattern === 0 ? '<path d="M-30 180 130 30l160 150M-30 220 130 70l160 150M-30 260 130 110l160 150"/>' : pattern === 1 ? Array.from({ length: 9 }, (_, i) => `<ellipse cx="130" cy="170" rx="${25 + i * 12}" ry="${95 - i * 6}" transform="rotate(${i * 12} 130 170)"/>`).join("") : pattern === 2 ? '<circle cx="185" cy="150" r="80"/><path d="m-20 240 140-170M30 300 170 130"/>' : '<path d="M30 170h200M30 200h160M30 230h120M30 260h80"/>'}</g><text x="22" y="31" fill="${b.ink}" font-family="sans-serif" font-size="9" letter-spacing="2">${esc(b.author.toUpperCase())}</text><rect x="0" y="277" width="260" height="83" fill="${b.bg}"/><foreignObject x="21" y="283" width="220" height="64"><div xmlns="http://www.w3.org/1999/xhtml" style="font:600 22px/1.05 'Helvetica Neue',sans-serif;color:${b.ink};letter-spacing:-.8px">${esc(b.title)}</div></foreignObject><text x="22" y="350" fill="${b.ink}" font-size="7" font-family="sans-serif" letter-spacing="2">STACKS ORIGINALS / ${b.n}</text></svg>`;
}
let v = new URLSearchParams(location.search).get("v") || "a";
if (!["a", "b", "c"].includes(v)) v = "a";
document.body.dataset.variant = v;
document.querySelector(`[data-direction=${v}]`).classList.add("selected");
let filter = "All",
  query = "",
  shelf = "Library",
  selected = 0;
const app = document.querySelector("#app");
function side() {
  return `<aside><a class="logo" href="?v=${v}"><span class="mark">▥</span> stacks<span class="logo-dot">.</span></a><div class="space-label">YOUR SPACE</div><button data-shelf="Home">${icon("home")}Home</button><button data-shelf="Library" class="on">${icon("library")}Library <small>12</small></button><button data-shelf="Inbox">${icon("inbox")}Inbox <small>0</small></button><div class="space-label">YOUR COLLECTIONS <span>+</span></div><button data-shelf="Weekend reading"><i class="collection-dot"></i>Weekend reading</button><button data-shelf="On the move"><i class="collection-dot pink"></i>On the move</button><div class="sidebar-footer"><div class="storage"><span class="status-dot"></span> All caught up</div><button data-shelf="Settings">${icon("settings")}Settings</button><div class="profile"><span>M</span><div>My reading room<small>Personal library</small></div></div></div></aside>`;
}
function tools() {
  return `<div class="tools"><div class="filters" role="group" aria-label="Format filter">${["All", "Book", "Comic", "Audio"].map((x) => `<button data-filter="${x}" class="${filter === x ? "active" : ""}">${x === "All" ? "Everything" : x === "Audio" ? "Audio" : x + "s"}</button>`).join("")}</div><label class="search">${icon("search")}<input aria-label="Search library" placeholder="Search your library" value="${esc(query)}"></label></div>`;
}
function header() {
  return `<header><div class="crumb">Your space <span>/</span> ${shelf}</div><button class="add-button" data-add>+ <span>Add books</span></button></header>`;
}
function shell() {
  app.innerHTML =
    v === "c"
      ? `<div class="index-shell"><header class="index-top"><a class="logo" href="?v=c">stacks<span class="logo-dot">.</span></a><nav>${["Library", "Home", "Inbox", "Settings"].map((x) => `<button data-shelf="${x}" class="${shelf === x ? "on" : ""}">${x}</button>`).join("")}</nav><button class="add-button" data-add>+ Add books</button></header><main><div id="content"></div></main></div>`
      : `<div class="shell">${side()}<main>${header()}<div id="content"></div></main></div>`;
  renderContent();
  bindShell();
}
function visible() {
  return books.filter(
    (b) =>
      (filter === "All" || b.type === filter) &&
      `${b.title} ${b.author}`.toLowerCase().includes(query.toLowerCase()) &&
      (shelf !== "Weekend reading" || b.type === "Book") &&
      (shelf !== "On the move" || b.type === "Audio"),
  );
}
function cards(items) {
  return `<div class="book-grid">${items.map((b) => `<button class="book-card" data-book="${b.id}"><div class="cover-wrap">${cover(b)}<span class="format-badge">${b.type === "Audio" ? icon("audio") : b.type === "Comic" ? "CBZ" : "EPUB"}</span><span class="open-book">↗</span></div><h3>${b.title}</h3><p>${b.author}</p>${b.progress ? `<div class="tiny-progress"><i style="width:${b.progress}%"></i></div><span class="progress-label">${b.progress}% ${b.type === "Audio" ? "listened" : "read"}</span>` : `<span class="progress-label">${b.type} · To read</span>`}</button>`).join("")}</div>`;
}
function renderContent() {
  let html = "";
  if (shelf === "Inbox")
    html = `<div class="empty-page"><span class="eyebrow">INBOX / 00</span><h1>Room for something new.</h1><p>New additions appear here, ready for a quick review.</p><button class="add-button" data-add>+ Add books</button></div>`;
  else if (shelf === "Settings")
    html = `<div class="page-title"><span class="eyebrow">YOUR SPACE</span><h1>Settings</h1><p>A home for your library, on your terms.</p></div><div class="settings-preview">${["Library & storage", "Backups & recovery", "Reading devices", "Appearance"].map((x, i) => `<button data-setting="${x}"><span>0${i + 1}</span><strong>${x}</strong><span>↗</span></button>`).join("")}<p class="subtle">Design preview · settings are available in the main Stacks app.</p></div>`;
  else if (v === "b") {
    html = `<div class="night-heading"><div><span class="eyebrow">MAKE TIME FOR A GOOD STORY</span><h1>${shelf === "Library" || shelf === "Home" ? "Pick up where<br>you left off." : shelf}</h1></div><span class="night-count">12 titles.<br>A world to get lost in.</span></div><section class="listening-feature"><div class="featured-cover">${cover(books[2])}</div><div class="feature-copy"><span class="eyebrow">ON YOUR HEADPHONES</span><h2>A Walk Through<br>the Night</h2><p>Theo Rivers <span>·</span> Audiobook</p><div class="feature-progress"><i></i></div><div class="time-row"><span>Chapter 4 of 12</span><span>38% listened</span></div><button data-play="2">▶ <span>Continue listening</span></button></div><div class="next-note"><span>UP NEXT</span><button data-book="6">Between<br>the Lines <span>↗</span></button><small>Iris Cole · Audio</small></div></section><div class="section-heading"><h2>Your collection</h2><span id="result-count"></span></div>${tools()}<div id="results"></div>`;
  } else if (v === "c") {
    html = `<div class="index-heading"><div><span class="eyebrow">PERSONAL CATALOG / VOLUME 01</span><h1>${shelf === "Home" ? "Reading list" : shelf === "Library" ? "Your library" : shelf}<sup>12</sup></h1></div><p>Everything you own.<br>Exactly where you left it.</p></div>${tools()}<div class="index-workspace"><div id="results"></div><section id="inspector"></section></div>`;
  } else {
    html = `<div class="page-title"><div><span class="eyebrow">A PLACE FOR EVERY STORY</span><h1>${shelf === "Home" ? "Your reading room" : shelf === "Library" ? "Library" : shelf}</h1><p>Find your next read. Or return to an old favorite.</p></div><div class="library-stat"><strong>12</strong><span>titles, all yours</span></div></div><div class="continue-strip"><span class="mini-cover">${cover(books[0])}</span><div><small>KEEP READING</small><strong>The Shape of Silence</strong><span>Elena Marsh · 64% read</span></div><button data-book="0">Continue <span>↗</span></button><div class="strip-divider"></div><span class="mini-cover">${cover(books[2])}</span><div><small>KEEP LISTENING</small><strong>A Walk Through the Night</strong><span>Theo Rivers · 38% listened</span></div><button data-play="2">▶</button></div>${tools()}<div class="result-heading"><span id="result-count"></span><span>Recently added ↓</span></div><div id="results"></div>`;
  }
  document.querySelector("#content").innerHTML = html;
  renderResults();
  bindContent();
}
function renderResults() {
  let target = document.querySelector("#results");
  if (!target) return;
  const items = visible();
  const count = document.querySelector("#result-count");
  if (count) count.textContent = `${items.length} titles`;
  target.innerHTML =
    v === "c"
      ? `<div class="table-head"><span>PUBLICATION</span><span>FORMAT</span><span>STATUS</span><span></span></div>${items.map((b) => `<button class="catalog-row ${selected === b.id ? "row-selected" : ""}" data-book="${b.id}"><span class="row-book">${cover(b)}<span><strong>${b.title}</strong><small>${b.author}</small></span></span><span class="row-format">${b.type}</span><span class="row-status">${b.progress > 0 && b.progress < 100 ? `<i style="--progress:${b.progress}%"></i>${b.progress}%` : b.state}</span><span class="row-arrow">↗</span></button>`).join("")}<div class="index-total">${items.length} PUBLICATIONS <span>THE COLLECTION IS YOURS.</span></div>`
      : cards(items);
  if (!items.length)
    target.innerHTML =
      '<div class="empty-search"><h2>No titles found.</h2><p>Try another title, author or format.</p></div>';
  if (v === "c") inspector();
  bindBooks(target);
}
function inspector() {
  document.querySelector("#inspector").innerHTML =
    `<span class="eyebrow">SELECTED PUBLICATION</span>${cover(books[selected])}<span class="inspector-type">${books[selected].type} / ${books[selected].n}</span><h2>${books[selected].title}</h2><p>${books[selected].author}</p><button class="primary" data-open="${selected}">Open details ↗</button>`;
  document.querySelector("[data-open]").onclick = () => details(selected);
}
function bindBooks(root) {
  root.querySelectorAll("[data-book]").forEach(
    (el) =>
      (el.onclick = () => {
        selected = Number(el.dataset.book);
        if (v === "c" && !matchMedia("(max-width:850px)").matches)
          renderResults();
        else details(selected);
      }),
  );
}
function bindShell() {
  document.querySelectorAll("[data-shelf]").forEach(
    (el) =>
      (el.onclick = () => {
        shelf = el.dataset.shelf;
        filter = "All";
        query = "";
        shell();
        document
          .querySelectorAll("[data-shelf]")
          .forEach((x) => x.classList.toggle("on", x.dataset.shelf === shelf));
      }),
  );
  document
    .querySelectorAll("[data-add]")
    .forEach(
      (el) => (el.onclick = () => document.querySelector("#add").showModal()),
    );
}
function bindContent() {
  bindShell();
  bindBooks(document.querySelector("#content"));
  document
    .querySelectorAll("[data-play]")
    .forEach((el) => (el.onclick = () => play(Number(el.dataset.play))));
  document.querySelectorAll("[data-filter]").forEach(
    (el) =>
      (el.onclick = () => {
        filter = el.dataset.filter;
        document
          .querySelectorAll("[data-filter]")
          .forEach((x) =>
            x.classList.toggle("active", x.dataset.filter === filter),
          );
        renderResults();
      }),
  );
  const search = document.querySelector(".search input");
  if (search)
    search.oninput = () => {
      query = search.value;
      renderResults();
    };
  document.querySelectorAll("[data-setting]").forEach(
    (el) =>
      (el.onclick = () => {
        el.innerHTML = `<span>↗</span><strong>${el.dataset.setting}</strong><span>Available in the main app</span>`;
      }),
  );
}
function details(id) {
  const b = books[id];
  document.querySelector("#detail-content").innerHTML =
    `<div class="detail-art">${cover(b)}</div><div class="detail-text"><span class="eyebrow">${b.type.toUpperCase()} / YOUR LIBRARY</span><h2>${b.title}</h2><p class="detail-author">${b.author}</p><div class="detail-tags"><span>${b.state}</span><span>${b.type === "Audio" ? "M4B" : b.type === "Comic" ? "CBZ" : "EPUB"}</span></div><p>A story worth making time for. This sample publication shows how covers, formats, reading progress and your personal notes could come together in this direction.</p><div class="detail-meta"><div><small>YOUR PROGRESS</small><strong>${b.progress}%</strong></div><div><small>COLLECTION</small><strong>${b.type === "Audio" ? "On the move" : "Weekend reading"}</strong></div></div>${b.type === "Audio" ? `<button class="primary" data-detail-play>▶ Play sample audio</button>` : '<div class="detail-note"><small>YOUR NOTES</small><p>There’s always room for another good story.</p></div>'}</div>`;
  const p = document.querySelector("[data-detail-play]");
  if (p) p.onclick = () => play(id);
  document.querySelector("#details").showModal();
}
const audio = document.querySelector("#audio");
function play(id) {
  const b = books[id];
  document.querySelector("#player").hidden = false;
  document.querySelector("#player").innerHTML =
    `<div class="player-book">${cover(b)}<span><strong>${b.title}</strong><small>20-second sample recording</small></span></div><button id="play-toggle" aria-label="Pause sample">Ⅱ</button><span id="audio-time">0:00</span><input id="seek" aria-label="Seek sample audio" type="range" min="0" max="20" step=".1" value="0"><span>0:20</span><button id="close-player" aria-label="Close player">×</button>`;
  audio.currentTime = 0;
  audio.play().catch(() => {
    document.querySelector("#play-toggle").textContent = "▶";
  });
  document.querySelector("#play-toggle").onclick = () => {
    if (audio.paused) audio.play().catch(() => {});
    else audio.pause();
  };
  document.querySelector("#seek").oninput = (e) =>
    (audio.currentTime = Number(e.target.value));
  document.querySelector("#close-player").onclick = () => {
    audio.pause();
    document.querySelector("#player").hidden = true;
  };
}
audio.ontimeupdate = () => {
  const t = document.querySelector("#audio-time");
  if (t) {
    t.textContent = `0:${Math.floor(audio.currentTime).toString().padStart(2, "0")}`;
    document.querySelector("#seek").value = audio.currentTime;
  }
};
audio.onplay = audio.onpause = () => {
  const b = document.querySelector("#play-toggle");
  if (b) {
    b.textContent = audio.paused ? "▶" : "Ⅱ";
    b.setAttribute("aria-label", audio.paused ? "Play sample" : "Pause sample");
  }
};
document
  .querySelectorAll("dialog .close")
  .forEach((el) => (el.onclick = () => el.closest("dialog").close()));
document.querySelectorAll("dialog").forEach(
  (d) =>
    (d.onclick = (e) => {
      if (e.target === d) {
        const r = d.getBoundingClientRect();
        if (
          e.clientX < r.left ||
          e.clientX > r.right ||
          e.clientY < r.top ||
          e.clientY > r.bottom
        )
          d.close();
      }
    }),
);
document.querySelector("#files").onchange = (e) =>
  (document.querySelector("#file-message").textContent =
    `${e.target.files.length} file(s) selected for preview. Nothing was imported.`);
shell();

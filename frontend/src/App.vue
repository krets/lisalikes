<script setup>
import { ref, computed, onMounted, watch } from "vue";

const token = ref(localStorage.getItem("token") || "");
const tracks = ref([]);
const allTracks = ref([]);
const duplicatesOpen = ref(false);
const search = ref("");
const syncPaused = ref(false);
const syncStatus = ref("idle");
const lastIngestTime = ref(null);
const lastPublishTime = ref(null);
const syncError = ref("");
const playlistId = ref(null);
const playlistName = ref(null);
const rulesOpen = ref(false);
const blockedArtists = ref([]);
const blockedGenres = ref([]);
const newGenre = ref("");
const undoToast = ref(null);
const searching = ref(false);
const pendingChanges = ref(false);
const sortKey = ref(null);
const sortDir = ref("asc");
const columnWidths = ref({ title: 260, artist: 180, album: 180 });
let pollInterval = null;
let undoTimeout = null;
let resizing = null;

onMounted(() => {
  const params = new URLSearchParams(window.location.search);
  const urlToken = params.get("token");
  if (urlToken) {
    token.value = urlToken;
    localStorage.setItem("token", urlToken);
    window.history.replaceState({}, "", "/");
  }
  if (token.value) {
    loadState();
    loadTracks();
    loadRules();
    loadAllTracks();
    pollInterval = setInterval(loadState, 15000);
  }
});

async function apiFetch(path, opts = {}) {
  const res = await fetch(path, {
    ...opts,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token.value}`,
      ...(opts.headers || {}),
    },
  });
  const refreshed = res.headers.get("X-Refreshed-Token");
  if (refreshed) {
    token.value = refreshed;
    localStorage.setItem("token", refreshed);
  }
  if (res.status === 401) {
    localStorage.removeItem("token");
    token.value = "";
    throw new Error("Session expired");
  }
  if (!res.ok) throw new Error(await res.text());
  return res.status === 204 ? null : res.json();
}

async function loadState() {
  const s = await apiFetch("/api/state");
  syncPaused.value = s.sync_paused;
  syncStatus.value = s.sync_status;
  lastIngestTime.value = s.last_ingest_time;
  lastPublishTime.value = s.last_publish_time;
  syncError.value = s.sync_error || "";
  playlistId.value = s.target_playlist_id;
  playlistName.value = s.target_playlist_name;
}

let searchRequestId = 0;

async function loadTracks() {
  const requestId = ++searchRequestId;
  const q = search.value ? `?q=${encodeURIComponent(search.value)}` : "";
  searching.value = true;
  try {
    const result = await apiFetch(`/api/tracks${q}`);
    if (requestId === searchRequestId) {
      tracks.value = result;
    }
  } finally {
    if (requestId === searchRequestId) {
      searching.value = false;
    }
  }
}

async function loadRules() {
  const r = await apiFetch("/api/rules");
  blockedArtists.value = r.blocked_artists;
  blockedGenres.value = r.blocked_genres;
}

async function loadAllTracks() {
  allTracks.value = await apiFetch("/api/tracks");
}

function openDuplicates() {
  duplicatesOpen.value = true;
  loadAllTracks();
}

async function keepOnlyThisVersion(group, chosen) {
  for (const t of group) {
    const shouldHide = t.uri !== chosen.uri;
    if (!!t.is_hidden !== shouldHide) {
      t.is_hidden = shouldHide ? 1 : 0;
      await apiFetch("/api/tracks/visibility", {
        method: "POST",
        body: JSON.stringify({ uri: t.uri, is_hidden: shouldHide }),
      });
    }
  }
  pendingChanges.value = true;
  await loadTracks();
}

function formatAddedAt(iso) {
  const d = new Date(iso);
  return isNaN(d) ? "" : d.toLocaleDateString();
}

function formatDuration(ms) {
  if (!ms && ms !== 0) return "";
  const totalSeconds = Math.round(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

async function toggleSyncPaused() {
  const next = !syncPaused.value;
  await apiFetch(`/api/state/sync-paused?paused=${next}`, { method: "POST" });
  syncPaused.value = next;
}

async function triggerSyncNow() {
  await apiFetch("/api/sync-now", { method: "POST" });
  syncStatus.value = "syncing";
}

async function toggleVisibility(track) {
  track.is_hidden = track.is_hidden ? 0 : 1;
  await apiFetch("/api/tracks/visibility", {
    method: "POST",
    body: JSON.stringify({ uri: track.uri, is_hidden: !!track.is_hidden }),
  });
  pendingChanges.value = true;
}

async function blockArtist(track) {
  const confirmed = window.confirm(
    `Block "${track.artist_name}" from this playlist? All their tracks will be excluded from future syncs.`
  );
  if (!confirmed) return;

  await apiFetch("/api/rules/blocked-artists", {
    method: "POST",
    body: JSON.stringify({ artist_id: track.artist_id, name: track.artist_name }),
  });
  await loadRules();
  await loadTracks();
  pendingChanges.value = true;
  showUndoToast(track.artist_id, track.artist_name);
}

async function unblockArtist(artistId) {
  await apiFetch(`/api/rules/blocked-artists/${artistId}`, { method: "DELETE" });
  await loadRules();
  await loadTracks();
  pendingChanges.value = true;
}

function showUndoToast(artistId, artistName) {
  clearTimeout(undoTimeout);
  undoToast.value = { artistId, artistName };
  undoTimeout = setTimeout(() => {
    undoToast.value = null;
  }, 6000);
}

async function undoBlock() {
  if (!undoToast.value) return;
  clearTimeout(undoTimeout);
  const { artistId } = undoToast.value;
  undoToast.value = null;
  await unblockArtist(artistId);
}

async function addBlockedGenre() {
  if (!newGenre.value.trim()) return;
  await apiFetch("/api/rules/blocked-genres", {
    method: "POST",
    body: JSON.stringify({ genre_name: newGenre.value.trim() }),
  });
  newGenre.value = "";
  await loadRules();
  pendingChanges.value = true;
}

async function removeBlockedGenre(g) {
  await apiFetch(`/api/rules/blocked-genres/${encodeURIComponent(g)}`, { method: "DELETE" });
  await loadRules();
  pendingChanges.value = true;
}

let searchDebounce = null;
watch(search, () => {
  clearTimeout(searchDebounce);
  searchDebounce = setTimeout(loadTracks, 250);
});

function searchNow() {
  clearTimeout(searchDebounce);
  loadTracks();
}

function isArtistBlocked(track) {
  return blockedArtists.value.some((a) => a.artist_id === track.artist_id);
}

function setSort(key) {
  if (sortKey.value === key) {
    sortDir.value = sortDir.value === "asc" ? "desc" : "asc";
  } else {
    sortKey.value = key;
    sortDir.value = "asc";
  }
}

function startResize(key, event) {
  resizing = { key, startX: event.clientX, startWidth: columnWidths.value[key] };
  window.addEventListener("mousemove", onResizeMove);
  window.addEventListener("mouseup", stopResize);
}

function onResizeMove(event) {
  if (!resizing) return;
  const delta = event.clientX - resizing.startX;
  columnWidths.value[resizing.key] = Math.max(80, resizing.startWidth + delta);
}

function stopResize() {
  resizing = null;
  window.removeEventListener("mousemove", onResizeMove);
  window.removeEventListener("mouseup", stopResize);
}

watch(syncStatus, (next, prev) => {
  if (prev === "syncing" && next !== "syncing") {
    loadTracks();
    loadRules();
    loadAllTracks();
    if (next === "idle") {
      pendingChanges.value = false;
    }
  }
});

const lastIngestLabel = computed(() => {
  if (!lastIngestTime.value) return "Liked Songs never loaded";
  const d = new Date(Number(lastIngestTime.value) * 1000);
  return `Liked Songs loaded: ${d.toLocaleString()}`;
});

const lastPublishLabel = computed(() => {
  if (!lastPublishTime.value) return "Playlist never published";
  const d = new Date(Number(lastPublishTime.value) * 1000);
  return `Playlist published: ${d.toLocaleString()}`;
});

const playlistUrl = computed(() =>
  playlistId.value ? `https://open.spotify.com/playlist/${playlistId.value}` : null
);

const syncHelpText = computed(() =>
  syncPaused.value
    ? "Automatic syncing is paused — use Sync Now to sync manually."
    : "Auto-syncs every 4 hours. Toggle off to pause the automatic schedule."
);

const duplicateGroups = computed(() => {
  const groups = new Map();
  for (const t of allTracks.value) {
    const key = `${t.artist_id || ""}::${(t.title || "").trim().toLowerCase()}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(t);
  }
  return [...groups.values()]
    .filter((g) => g.length > 1)
    .sort((a, b) => a[0].title.localeCompare(b[0].title));
});

const sortedTracks = computed(() => {
  if (!sortKey.value) return tracks.value;
  const dir = sortDir.value === "asc" ? 1 : -1;
  return [...tracks.value].sort((a, b) => {
    const av = (a[sortKey.value] || "").toLowerCase();
    const bv = (b[sortKey.value] || "").toLowerCase();
    if (av < bv) return -1 * dir;
    if (av > bv) return 1 * dir;
    return 0;
  });
});
</script>

<template>
  <div v-if="!token" class="min-h-screen flex items-center justify-center p-6">
    <div class="text-center text-gray-400">
      <p class="text-lg">No access link detected.</p>
      <p class="text-sm mt-2">Open this page using the link that was emailed to you.</p>
    </div>
  </div>

  <div v-else class="min-h-screen max-w-5xl mx-auto p-4 sm:p-6">
    <header class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-6">
      <div>
        <h1 class="text-2xl font-semibold">Playlist Curator</h1>
        <a
          v-if="playlistUrl"
          :href="playlistUrl"
          target="_blank"
          rel="noopener noreferrer"
          title="View playlist on Spotify"
          class="text-sm text-spotify hover:underline inline-block"
        >
          {{ playlistName || "Open target playlist" }} ↗
        </a>
        <p class="text-sm text-gray-400">
          {{ syncStatus === "syncing" ? "Syncing..." : lastIngestLabel }}
        </p>
        <p class="text-sm text-gray-400">{{ lastPublishLabel }}</p>
        <p v-if="syncError" class="text-xs text-red-400 mt-0.5">{{ syncError }}</p>
        <p v-if="pendingChanges && syncStatus !== 'syncing'" class="text-xs text-amber-400 mt-0.5">
          Unsynced changes — click Sync Now to apply them
        </p>
        <p class="text-xs text-gray-400 mt-0.5">{{ syncHelpText }}</p>
      </div>
      <div class="flex items-center gap-3">
        <button
          @click="rulesOpen = true"
          class="px-3 py-2 rounded-lg bg-gray-800 hover:bg-gray-700 text-sm"
        >
          Rules
        </button>
        <button
          @click="openDuplicates"
          class="px-3 py-2 rounded-lg bg-gray-800 hover:bg-gray-700 text-sm"
        >
          Duplicates
          <span v-if="duplicateGroups.length" class="text-amber-400">({{ duplicateGroups.length }})</span>
        </button>
        <button
          @click="triggerSyncNow"
          :disabled="syncStatus === 'syncing'"
          class="px-3 py-2 rounded-lg bg-spotify hover:brightness-110 disabled:opacity-50 text-sm font-medium"
        >
          Sync Now
        </button>
        <label class="flex items-center gap-2 text-sm">
          <span>{{ syncPaused ? "Paused" : "Active" }}</span>
          <button
            @click="toggleSyncPaused"
            role="switch"
            :aria-checked="!syncPaused"
            aria-label="Automatic syncing"
            class="w-11 h-6 rounded-full relative transition-colors"
            :class="syncPaused ? 'bg-gray-600' : 'bg-spotify'"
          >
            <span
              class="absolute top-0.5 w-5 h-5 rounded-full bg-white transition-all"
              :class="syncPaused ? 'left-0.5' : 'left-5'"
            />
          </button>
        </label>
      </div>
    </header>

    <div class="relative mb-2">
      <input
        v-model="search"
        type="text"
        placeholder="Search title, artist, or album..."
        @keyup.enter="searchNow"
        class="w-full px-4 py-2 rounded-lg bg-gray-900 border border-gray-800 focus:outline-none focus:border-spotify"
      />
      <span
        v-if="searching"
        class="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-gray-400"
      >
        Searching…
      </span>
    </div>
    <p class="text-xs text-gray-400 mb-2">
      {{ tracks.length }} track{{ tracks.length === 1 ? "" : "s" }}
    </p>

    <div class="rounded-lg overflow-hidden border border-gray-800">
      <table class="w-full text-sm table-fixed">
        <colgroup>
          <col style="width: 64px" />
          <col :style="{ width: columnWidths.title + 'px' }" />
          <col class="hidden sm:table-column" :style="{ width: columnWidths.artist + 'px' }" />
          <col class="hidden md:table-column" :style="{ width: columnWidths.album + 'px' }" />
          <col style="width: 96px" />
        </colgroup>
        <thead class="bg-gray-900 text-gray-400 text-left">
          <tr>
            <th class="py-3 px-2"></th>
            <th class="py-3 px-2 relative select-none">
              <button @click="setSort('title')" class="flex items-center gap-1 hover:text-gray-100">
                <span>Title</span>
                <span v-if="sortKey === 'title'" class="text-[10px]">{{ sortDir === "asc" ? "▲" : "▼" }}</span>
              </button>
              <span
                class="hidden sm:block absolute top-0 right-0 h-full w-1.5 cursor-col-resize hover:bg-spotify/50"
                @mousedown="startResize('title', $event)"
              ></span>
            </th>
            <th class="py-3 px-2 hidden sm:table-cell relative select-none">
              <button @click="setSort('artist_name')" class="flex items-center gap-1 hover:text-gray-100">
                <span>Artist</span>
                <span v-if="sortKey === 'artist_name'" class="text-[10px]">{{ sortDir === "asc" ? "▲" : "▼" }}</span>
              </button>
              <span
                class="hidden sm:block absolute top-0 right-0 h-full w-1.5 cursor-col-resize hover:bg-spotify/50"
                @mousedown="startResize('artist', $event)"
              ></span>
            </th>
            <th class="py-3 px-2 hidden md:table-cell relative select-none">
              <button @click="setSort('album_name')" class="flex items-center gap-1 hover:text-gray-100">
                <span>Album</span>
                <span v-if="sortKey === 'album_name'" class="text-[10px]">{{ sortDir === "asc" ? "▲" : "▼" }}</span>
              </button>
              <span
                class="hidden sm:block absolute top-0 right-0 h-full w-1.5 cursor-col-resize hover:bg-spotify/50"
                @mousedown="startResize('album', $event)"
              ></span>
            </th>
            <th class="py-3 px-2 text-right">Include</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="t in sortedTracks"
            :key="t.uri"
            class="border-t border-gray-800 hover:bg-gray-900/50"
            :class="{ 'opacity-40': isArtistBlocked(t) }"
          >
            <td class="p-2">
              <img :src="t.image_url" class="w-12 h-12 rounded object-cover" loading="lazy" />
            </td>
            <td class="p-2">
              <div class="font-medium truncate">{{ t.title }}</div>
              <div class="text-xs text-gray-400 sm:hidden flex items-center gap-2 mt-0.5">
                <span class="truncate">{{ t.artist_name }}</span>
                <span
                  v-if="isArtistBlocked(t)"
                  class="text-[10px] uppercase tracking-wide text-red-400 bg-red-400/10 px-1.5 py-0.5 rounded shrink-0"
                >
                  Blocked
                </span>
                <button v-else @click="blockArtist(t)" class="underline hover:text-red-400 shrink-0">
                  Block
                </button>
              </div>
            </td>
            <td class="p-2 hidden sm:table-cell">
              <div class="flex items-center gap-2">
                <span class="text-left truncate">{{ t.artist_name }}</span>
                <span
                  v-if="isArtistBlocked(t)"
                  class="text-[10px] uppercase tracking-wide text-red-400 bg-red-400/10 px-1.5 py-0.5 rounded shrink-0"
                >
                  Blocked
                </span>
                <button
                  v-else
                  @click="blockArtist(t)"
                  title="Block this artist"
                  class="text-xs text-gray-400 hover:text-red-400 underline shrink-0"
                >
                  Block
                </button>
              </div>
            </td>
            <td class="p-2 hidden md:table-cell text-gray-400 truncate">{{ t.album_name }}</td>
            <td class="p-2 text-right">
              <button
                @click="toggleVisibility(t)"
                :disabled="isArtistBlocked(t)"
                :title="isArtistBlocked(t) ? 'Artist is blocked — this toggle has no effect' : ''"
                role="switch"
                :aria-checked="!t.is_hidden"
                :aria-label="`Include ${t.title} in playlist`"
                class="w-11 h-6 rounded-full relative transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                :class="t.is_hidden ? 'bg-gray-600' : 'bg-spotify'"
              >
                <span
                  class="absolute top-0.5 w-5 h-5 rounded-full bg-white transition-all"
                  :class="t.is_hidden ? 'left-0.5' : 'left-5'"
                />
              </button>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-if="!tracks.length" class="p-6 text-center text-gray-400">No tracks found.</p>
    </div>

    <!-- Rules modal -->
    <div
      v-if="rulesOpen"
      class="fixed inset-0 bg-black/60 flex items-center justify-center p-4 z-10"
      @click.self="rulesOpen = false"
    >
      <div class="bg-gray-900 rounded-lg p-5 w-full max-w-md border border-gray-800">
        <div class="flex justify-between items-center mb-4">
          <h2 class="text-lg font-semibold">Blocking Rules</h2>
          <button @click="rulesOpen = false" class="text-gray-400 hover:text-white">✕</button>
        </div>

        <h3 class="text-sm text-gray-400 mb-2">Blocked artists</h3>
        <ul class="mb-4 space-y-1 max-h-32 overflow-y-auto">
          <li
            v-for="a in blockedArtists"
            :key="a.artist_id"
            class="flex justify-between items-center text-sm bg-gray-800 rounded px-2 py-1"
          >
            {{ a.name }}
            <button @click="unblockArtist(a.artist_id)" class="text-gray-400 hover:text-red-400">✕</button>
          </li>
          <li v-if="!blockedArtists.length" class="text-xs text-gray-400">
            None yet — use the "Block" button next to an artist in the table.
          </li>
        </ul>

        <h3 class="text-sm text-gray-400 mb-1">Blocked genres</h3>
        <p class="text-xs text-gray-400 mb-2">
          Matches an artist's Spotify genre tags — not the track title or lyrics.
        </p>
        <div class="flex gap-2 mb-2">
          <input
            v-model="newGenre"
            @keyup.enter="addBlockedGenre"
            type="text"
            placeholder="e.g. sleep, holiday"
            class="flex-1 px-2 py-1 rounded bg-gray-800 border border-gray-700 text-sm"
          />
          <button @click="addBlockedGenre" class="px-3 py-1 rounded bg-spotify text-sm">Add</button>
        </div>
        <ul class="space-y-1 max-h-32 overflow-y-auto">
          <li
            v-for="g in blockedGenres"
            :key="g"
            class="flex justify-between items-center text-sm bg-gray-800 rounded px-2 py-1"
          >
            {{ g }}
            <button @click="removeBlockedGenre(g)" class="text-gray-400 hover:text-red-400">✕</button>
          </li>
        </ul>
      </div>
    </div>

    <!-- Duplicates modal -->
    <div
      v-if="duplicatesOpen"
      class="fixed inset-0 bg-black/60 flex items-center justify-center p-4 z-10"
      @click.self="duplicatesOpen = false"
    >
      <div class="bg-gray-900 rounded-lg p-5 w-full max-w-lg max-h-[80vh] overflow-y-auto border border-gray-800">
        <div class="flex justify-between items-center mb-2">
          <h2 class="text-lg font-semibold">Possible Duplicates</h2>
          <button @click="duplicatesOpen = false" class="text-gray-400 hover:text-white">✕</button>
        </div>
        <p class="text-xs text-gray-400 mb-4">
          Same title and artist, but different Spotify tracks (e.g. a reissue or a re-ingested
          album). Pick the version to keep — the others will be set to Hidden.
        </p>

        <p v-if="!duplicateGroups.length" class="text-sm text-gray-400">No duplicates found.</p>

        <div v-for="group in duplicateGroups" :key="group[0].artist_id + '::' + group[0].title" class="mb-4">
          <h3 class="text-sm font-medium mb-1 truncate">
            {{ group[0].title }} — {{ group[0].artist_name }}
          </h3>
          <ul class="space-y-1">
            <li
              v-for="t in group"
              :key="t.uri"
              class="flex justify-between items-center gap-2 text-sm bg-gray-800 rounded px-2 py-1.5"
            >
              <div class="min-w-0">
                <div class="truncate">
                  {{ t.album_name }}<span v-if="formatDuration(t.duration_ms)"> · {{ formatDuration(t.duration_ms) }}</span>
                </div>
                <div class="text-[10px] text-gray-400">Added {{ formatAddedAt(t.added_at) }}</div>
              </div>
              <div class="flex items-center gap-2 shrink-0">
                <span
                  class="text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded"
                  :class="t.is_hidden ? 'text-gray-400 bg-gray-700' : 'text-spotify bg-spotify/10'"
                >
                  {{ t.is_hidden ? "Hidden" : "Included" }}
                </span>
                <button
                  @click="keepOnlyThisVersion(group, t)"
                  class="text-xs text-gray-400 hover:text-spotify underline"
                >
                  Keep only this
                </button>
              </div>
            </li>
          </ul>
        </div>
      </div>
    </div>

    <!-- Undo toast -->
    <div
      v-if="undoToast"
      class="fixed bottom-4 left-1/2 -translate-x-1/2 bg-gray-800 border border-gray-700 rounded-lg px-4 py-3 flex items-center gap-3 shadow-lg z-20"
    >
      <span class="text-sm">Blocked {{ undoToast.artistName }}</span>
      <button @click="undoBlock" class="text-sm font-medium text-spotify hover:brightness-110">
        Undo
      </button>
    </div>
  </div>
</template>

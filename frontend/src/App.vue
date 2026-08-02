<script setup>
import { ref, computed, onMounted, watch } from "vue";

const token = ref(localStorage.getItem("token") || "");
const tracks = ref([]);
const search = ref("");
const syncPaused = ref(false);
const syncStatus = ref("idle");
const lastSyncTime = ref(null);
const rulesOpen = ref(false);
const blockedArtists = ref([]);
const blockedGenres = ref([]);
const newGenre = ref("");
const undoToast = ref(null);
const searching = ref(false);
let pollInterval = null;
let undoTimeout = null;

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
  lastSyncTime.value = s.last_sync_time;
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
  showUndoToast(track.artist_id, track.artist_name);
}

async function unblockArtist(artistId) {
  await apiFetch(`/api/rules/blocked-artists/${artistId}`, { method: "DELETE" });
  await loadRules();
  await loadTracks();
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
}

async function removeBlockedGenre(g) {
  await apiFetch(`/api/rules/blocked-genres/${encodeURIComponent(g)}`, { method: "DELETE" });
  await loadRules();
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

watch(syncStatus, (next, prev) => {
  if (prev === "syncing" && next !== "syncing") {
    loadTracks();
    loadRules();
  }
});

const lastSyncedLabel = computed(() => {
  if (!lastSyncTime.value) return "Never synced";
  const d = new Date(Number(lastSyncTime.value) * 1000);
  return `Last synced: ${d.toLocaleString()}`;
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
        <p class="text-sm text-gray-400">
          {{ syncStatus === "syncing" ? "Syncing..." : lastSyncedLabel }}
        </p>
      </div>
      <div class="flex items-center gap-3">
        <button
          @click="rulesOpen = true"
          class="px-3 py-2 rounded-lg bg-gray-800 hover:bg-gray-700 text-sm"
        >
          Rules
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

    <div class="relative mb-4">
      <input
        v-model="search"
        type="text"
        placeholder="Search title, artist, or album..."
        @keyup.enter="searchNow"
        class="w-full px-4 py-2 rounded-lg bg-gray-900 border border-gray-800 focus:outline-none focus:border-spotify"
      />
      <span
        v-if="searching"
        class="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-gray-500"
      >
        Searching…
      </span>
    </div>

    <div class="rounded-lg overflow-hidden border border-gray-800">
      <table class="w-full text-sm">
        <thead class="bg-gray-900 text-gray-400 text-left">
          <tr>
            <th class="py-3 px-2 w-16"></th>
            <th class="py-3 px-2">Title</th>
            <th class="py-3 px-2 hidden sm:table-cell">Artist</th>
            <th class="py-3 px-2 hidden md:table-cell">Album</th>
            <th class="py-3 px-2 w-24 text-right">Include</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="t in tracks"
            :key="t.uri"
            class="border-t border-gray-800 hover:bg-gray-900/50 group"
            :class="{ 'opacity-40': isArtistBlocked(t) }"
          >
            <td class="p-2">
              <img :src="t.image_url" class="w-12 h-12 rounded object-cover" loading="lazy" />
            </td>
            <td class="p-2">
              <div class="font-medium">{{ t.title }}</div>
              <div class="text-xs text-gray-500 sm:hidden flex items-center gap-2 mt-0.5">
                <span>{{ t.artist_name }}</span>
                <span
                  v-if="isArtistBlocked(t)"
                  class="text-[10px] uppercase tracking-wide text-red-400 bg-red-400/10 px-1.5 py-0.5 rounded"
                >
                  Blocked
                </span>
                <button v-else @click="blockArtist(t)" class="underline hover:text-red-400">
                  Block
                </button>
              </div>
            </td>
            <td class="p-2 hidden sm:table-cell">
              <div class="flex items-center gap-2">
                <span class="text-left">{{ t.artist_name }}</span>
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
                  class="text-xs text-gray-500 hover:text-red-400 underline shrink-0"
                >
                  Block
                </button>
              </div>
            </td>
            <td class="p-2 hidden md:table-cell text-gray-400">{{ t.album_name }}</td>
            <td class="p-2 text-right">
              <button
                @click="toggleVisibility(t)"
                :disabled="isArtistBlocked(t)"
                :title="isArtistBlocked(t) ? 'Artist is blocked — this toggle has no effect' : ''"
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
      <p v-if="!tracks.length" class="p-6 text-center text-gray-500">No tracks found.</p>
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
          <li v-if="!blockedArtists.length" class="text-xs text-gray-500">
            None yet — use the "Block" button next to an artist in the table.
          </li>
        </ul>

        <h3 class="text-sm text-gray-400 mb-2">Blocked genres</h3>
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

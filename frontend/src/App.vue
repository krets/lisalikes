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
let pollInterval = null;

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

async function loadTracks() {
  const q = search.value ? `?q=${encodeURIComponent(search.value)}` : "";
  tracks.value = await apiFetch(`/api/tracks${q}`);
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
  await apiFetch("/api/rules/blocked-artists", {
    method: "POST",
    body: JSON.stringify({ artist_id: track.artist_id, name: track.artist_name }),
  });
  await loadRules();
  await loadTracks();
}

async function unblockArtist(artistId) {
  await apiFetch(`/api/rules/blocked-artists/${artistId}`, { method: "DELETE" });
  await loadRules();
  await loadTracks();
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

    <input
      v-model="search"
      type="text"
      placeholder="Search title, artist, or album..."
      class="w-full mb-4 px-4 py-2 rounded-lg bg-gray-900 border border-gray-800 focus:outline-none focus:border-spotify"
    />

    <div class="rounded-lg overflow-hidden border border-gray-800">
      <table class="w-full text-sm">
        <thead class="bg-gray-900 text-gray-400 text-left">
          <tr>
            <th class="p-3 w-16"></th>
            <th class="p-3">Title</th>
            <th class="p-3 hidden sm:table-cell">Artist</th>
            <th class="p-3 hidden md:table-cell">Album</th>
            <th class="p-3 w-24 text-right">Include</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="t in tracks"
            :key="t.uri"
            class="border-t border-gray-800 hover:bg-gray-900/50 group"
          >
            <td class="p-2">
              <img :src="t.image_url" class="w-12 h-12 rounded object-cover" loading="lazy" />
            </td>
            <td class="p-2">
              <div class="font-medium">{{ t.title }}</div>
              <div class="text-xs text-gray-500 sm:hidden">{{ t.artist_name }}</div>
            </td>
            <td class="p-2 hidden sm:table-cell">
              <button
                class="hover:text-red-400 hover:underline"
                title="Block this artist"
                @click="blockArtist(t)"
              >
                {{ t.artist_name }}
              </button>
            </td>
            <td class="p-2 hidden md:table-cell text-gray-400">{{ t.album_name }}</td>
            <td class="p-2 text-right">
              <button
                @click="toggleVisibility(t)"
                class="w-11 h-6 rounded-full relative transition-colors"
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
            None yet — click an artist name in the table to block them.
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
  </div>
</template>

<script setup>
// Каркас: верхняя строка состояния и вкладки. Состояние опрашивается раз в 3 с и
// передаётся вкладкам; вкладка запоминается в адресе (#calls) для обновления страницы.
import { computed, onMounted, onUnmounted, ref } from "vue";
import { get } from "./api.js";
import Overview from "./views/Overview.vue";
import Checks from "./views/Checks.vue";
import Logs from "./views/Logs.vue";
import Calls from "./views/Calls.vue";
import Metrics from "./views/Metrics.vue";

const tabs = [
  { id: "overview", title: "Обзор", view: Overview },
  { id: "checks", title: "Проверки", view: Checks },
  { id: "logs", title: "Журналы", view: Logs },
  { id: "calls", title: "Звонки", view: Calls },
  { id: "metrics", title: "Метрики", view: Metrics },
];
const tab = ref(tabs.find((t) => `#${t.id}` === location.hash)?.id || "overview");
const status = ref(null);
const error = ref("");
let timer;

async function refresh() {
  try {
    status.value = await get("/api/status");
    error.value = "";
  } catch (e) {
    error.value = `нет связи с панелью (${e.message})`;
  }
}

function open(id) {
  tab.value = id;
  history.replaceState(null, "", `#${id}`);
}

// Группа «работает», если все её контейнеры запущены (и не unhealthy).
function groupState(group) {
  const items = (status.value?.containers || []).filter((c) => c.group === group);
  if (!items.length) return { cls: "", text: "нет" };
  const up = items.filter((c) => c.state === "running" && c.health !== "unhealthy").length;
  if (up === items.length) return { cls: "good", text: "работает" };
  return { cls: up ? "warn" : "bad", text: `${up}/${items.length}` };
}

const radio = computed(() => {
  const kinds = (status.value?.radio || []).map((p) => p.kind);
  if (kinds.includes("gnb")) return { cls: "good", text: "gNB SDR" };
  if (kinds.includes("rfsim-gnb")) return { cls: "good", text: `rfsim, UE: ${kinds.filter((k) => k === "rfsim-ue").length}` };
  if (kinds.includes("foreign")) return { cls: "warn", text: "чужой gNB" };
  return { cls: "bad", text: "выключено" };
});

onMounted(() => {
  refresh();
  timer = setInterval(refresh, 3000);
});
onUnmounted(() => clearInterval(timer));
</script>

<template>
  <header>
    <strong>Стенд 5G</strong>
    <template v-if="status">
      <span class="mono">PLMN {{ status.plmn }}</span>
      <span><i class="dot" :class="groupState('core').cls" />ядро {{ groupState("core").text }}</span>
      <span><i class="dot" :class="groupState('ims').cls" />IMS {{ groupState("ims").text }}</span>
      <span><i class="dot" :class="groupState('ai').cls" />AI {{ groupState("ai").text }}</span>
      <span><i class="dot" :class="radio.cls" />радио: {{ radio.text }}</span>
      <span><i class="dot" :class="status.sipcap ? 'good' : 'bad'" />захват SIP</span>
      <span v-if="status.job" class="warn">выполняется: {{ status.job.name }}</span>
    </template>
    <span v-if="error" class="bad">{{ error }}</span>
  </header>
  <nav>
    <button v-for="t in tabs" :key="t.id" :class="{ active: tab === t.id }" @click="open(t.id)">
      {{ t.title }}
    </button>
  </nav>
  <main>
    <KeepAlive>
      <component :is="tabs.find((t) => t.id === tab).view" :status="status" @refresh="refresh" />
    </KeepAlive>
  </main>
</template>

<style scoped>
header {
  display: flex; gap: 16px; flex-wrap: wrap; align-items: center; padding: 10px 16px;
  background: var(--panel); border-bottom: 1px solid var(--line);
}
nav { display: flex; gap: 4px; padding: 8px 16px 0; flex-wrap: wrap; }
nav button { border-radius: 6px 6px 0 0; border-bottom: none; }
nav button.active { background: var(--accent); color: #fff; border-color: var(--accent); }
main { padding: 14px 16px 40px; max-width: 1500px; }
</style>

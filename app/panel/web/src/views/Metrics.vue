<script setup>
// Метрики за выбранный период: ресурсы контейнеров и хоста, SIP за 10 с, задержки AI.
// Ряды в памяти панели (24 ч); перезапуск панели их обнуляет.
import { computed, onActivated, onDeactivated, ref } from "vue";
import { get } from "../api.js";
import Chart from "./Chart.vue";

const ranges = [
  { title: "15 мин", seconds: 900 },
  { title: "1 ч", seconds: 3600 },
  { title: "6 ч", seconds: 21600 },
  { title: "24 ч", seconds: 86400 },
];
const range = ref(900);
const names = ref([]);
const data = ref({});
const TOP = 8;
let timer;

function pick(prefix) {
  return names.value.filter((n) => n.startsWith(prefix));
}

// Контейнеры с наибольшей последней загрузкой: иначе график из 25 линий не читается.
function busiest(prefix) {
  const last = (n) => data.value[n]?.at(-1)?.[1] ?? 0;
  return Object.fromEntries(pick(prefix).sort((a, b) => last(b) - last(a)).slice(0, TOP).map((n) => [n, data.value[n]]));
}

function only(list) {
  return Object.fromEntries(list.filter((n) => data.value[n]).map((n) => [n, data.value[n]]));
}

const ai = computed(() => only(names.value.filter((n) => /^(ai|llm|voice):.*_ms$/.test(n))));
const audio = computed(() => only(names.value.filter((n) => /^(ai|voice):.*_seconds$/.test(n))));

async function load() {
  names.value = (await get("/api/metrics/series")).series;
  const since = Date.now() / 1000 - range.value;
  const body = await get(`/api/metrics?since=${since}&series=${encodeURIComponent(names.value.join(","))}`);
  data.value = body.series;
}

function setRange(seconds) {
  range.value = seconds;
  load();
}

onActivated(() => {
  load();
  timer = setInterval(load, 10000);
});
onDeactivated(() => clearInterval(timer));
</script>

<template>
  <div class="row" style="margin-bottom: 10px">
    <button v-for="r in ranges" :key="r.seconds" :class="{ primary: range === r.seconds }" @click="setRange(r.seconds)">{{ r.title }}</button>
    <span class="muted">опрос каждые 10 с; история в памяти панели</span>
  </div>
  <p v-if="!names.length" class="muted">Данных пока нет: первая точка появится через 10 с после запуска панели.</p>
  <div class="charts">
    <Chart title="CPU контейнеров" unit="%" :series="busiest('cpu:')" />
    <Chart title="Память контейнеров" unit="МиБ" :series="busiest('mem:')" />
    <Chart title="SIP за 10 с" unit="шт" :series="only(['sip:register', 'sip:invite', 'sip:bye', 'sip:fail'])" />
    <Chart title="Хост" unit="" :series="only(['host:load1'])" />
    <Chart title="Задержки AI (каждое событие)" unit="мс" :series="ai" points />
    <Chart title="Длина фраз" unit="с" :series="audio" points />
  </div>
</template>

<style scoped>
.charts { display: grid; gap: 12px; grid-template-columns: repeat(auto-fill, minmax(460px, 1fr)); }
@media (max-width: 520px) { .charts { grid-template-columns: 1fr; } }
</style>

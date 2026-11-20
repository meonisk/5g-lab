<script setup>
// Журналы: выбор источников, фильтр по подстроке/регулярному выражению, пауза.
// Буфер — последние 3000 строк; на паузе строки продолжают копиться, но не рисуются.
import { computed, onActivated, onDeactivated, ref } from "vue";
import { get, lineClass, listen, post } from "../api.js";

const sources = ref([]);
const chosen = ref(["oai-amf", "lab-pcscf", "lab-scscf", "lab-sip-as"]);
const filter = ref("");
const paused = ref(false);
const lines = ref([]);
const shown = ref([]);
const message = ref("");
const box = ref(null);
let close = null;
let drawTimer;

const matcher = computed(() => {
  if (!filter.value) return null;
  try {
    return new RegExp(filter.value, "i");
  } catch {
    return { test: (s) => s.toLowerCase().includes(filter.value.toLowerCase()) };
  }
});

function connect() {
  close?.();
  lines.value = [];
  const names = chosen.value.filter((n) => sources.value.some((s) => s.name === n));
  if (!names.length) return;
  close = listen(`/api/logs/stream?tail=200&sources=${encodeURIComponent(names.join(","))}`, (d) => {
    lines.value.push(d);
    if (lines.value.length > 3000) lines.value.splice(0, lines.value.length - 3000);
  });
}

// Перерисовка не чаще 4 раз в секунду: журналы ядра бывают очень частыми.
function draw() {
  if (paused.value) return;
  const m = matcher.value;
  shown.value = m ? lines.value.filter((l) => m.test(l.line) || m.test(l.source)) : lines.value.slice();
  const el = box.value;
  if (el && el.scrollTop + el.clientHeight >= el.scrollHeight - 40) requestAnimationFrame(() => (el.scrollTop = el.scrollHeight));
}

function toggle(name) {
  chosen.value = chosen.value.includes(name) ? chosen.value.filter((n) => n !== name) : [...chosen.value, name];
  connect();
}

async function collect() {
  try {
    await post("/api/actions/collect");
    message.value = "собираю журналы в local/evidence/ — результат во вкладке «Проверки»";
  } catch (e) {
    message.value = e.message;
  }
}

function color(source) {
  let hash = 0;
  for (const ch of source) hash = (hash * 31 + ch.charCodeAt(0)) % 360;
  return `hsl(${hash} 55% 55%)`;
}

// Вкладка в KeepAlive: при уходе поток закрывается, чтобы не держать docker logs зря.
onActivated(async () => {
  sources.value = (await get("/api/logs/sources")).sources;
  connect();
  drawTimer = setInterval(draw, 250);
});
onDeactivated(() => {
  close?.();
  close = null;
  clearInterval(drawTimer);
});
</script>

<template>
  <div class="row">
    <span v-for="s in sources" :key="s.name">
      <label class="mono"><input type="checkbox" :checked="chosen.includes(s.name)" @change="toggle(s.name)" /> {{ s.name }}</label>
    </span>
  </div>
  <div class="row" style="margin: 10px 0">
    <input v-model="filter" placeholder="фильтр: INVITE|REGISTER, IMSI, reject…" style="min-width: 320px" />
    <button @click="paused = !paused">{{ paused ? "Продолжить" : "Пауза" }}</button>
    <button @click="lines = []">Очистить</button>
    <button @click="collect">Собрать журналы</button>
    <span class="muted">{{ shown.length }} строк; строки с ключами скрыты</span>
  </div>
  <p v-if="message" class="muted">{{ message }}</p>
  <pre ref="box" class="output" style="height: 70vh"><span v-for="(l, i) in shown" :key="i" :class="lineClass(l.line)"><b :style="{ color: color(l.source) }">{{ l.source.padEnd(16) }}</b> {{ l.line }}
</span></pre>
</template>

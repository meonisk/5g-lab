<script setup>
// Лестничная диаграмма SIP: колонки — узлы (контейнер по IP или адрес телефона),
// строки — сообщения по времени. Клик по стрелке — выбрать сообщение.
import { computed } from "vue";

const props = defineProps({ messages: Array, selected: Number });
const emit = defineEmits(["select"]);
const ORDER = ["lab-pcscf", "lab-icscf", "lab-scscf", "lab-sip-as", "lab-voice-agent", "lab-rtpengine"];
const COLUMN = 150;
const ROW = 30;
const TOP = 46;

function node(name, address) {
  return name || address.replace(/:\d+$/, "");
}

const columns = computed(() => {
  const seen = [];
  for (const m of props.messages) {
    for (const n of [node(m.src_name, m.src), node(m.dst_name, m.dst)]) if (!seen.includes(n)) seen.push(n);
  }
  // Телефоны и прочие неизвестные узлы — слева, затем узлы IMS в порядке цепочки.
  const rank = (n) => (ORDER.includes(n) ? ORDER.indexOf(n) + 1 : 0);
  return seen.sort((a, b) => rank(a) - rank(b));
});

const rows = computed(() =>
  props.messages.map((m, i) => {
    const from = columns.value.indexOf(node(m.src_name, m.src));
    const to = columns.value.indexOf(node(m.dst_name, m.dst));
    return { m, i, x1: x(from), x2: x(to), y: TOP + 20 + i * ROW, self: from === to };
  }),
);

function x(index) {
  return 120 + index * COLUMN;
}

// Подпись не шире стрелки (≈7 px на символ); полный текст — во всплывающей подсказке.
function label(r) {
  const full = r.m.label + (r.m.method ? "" : ` (${r.m.cseq})`);
  const room = Math.max(14, Math.floor(Math.abs(r.x2 - r.x1) / 7));
  return full.length > room ? `${full.slice(0, room - 1)}…` : full;
}

function color(m) {
  if (m.method) return "var(--accent)";
  if (m.status >= 400) return "var(--bad)";
  if (m.status >= 200) return "var(--good)";
  return "var(--muted)";
}

const width = computed(() => 200 + (columns.value.length - 1) * COLUMN);
const height = computed(() => TOP + 40 + props.messages.length * ROW);
const start = computed(() => props.messages[0]?.t || 0);
</script>

<template>
  <div style="overflow: auto; max-height: 75vh">
    <svg :width="width" :height="height" class="mono" style="font-size: 11.5px">
      <defs>
        <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M0,0 L10,5 L0,10 z" fill="context-stroke" />
        </marker>
      </defs>
      <g v-for="(c, i) in columns" :key="c">
        <text :x="x(i)" y="18" text-anchor="middle" fill="var(--text)" font-weight="600">{{ c }}</text>
        <line :x1="x(i)" :x2="x(i)" y1="28" :y2="height - 8" stroke="var(--line)" stroke-dasharray="3 3" />
      </g>
      <g v-for="r in rows" :key="r.m.seq" style="cursor: pointer" @click="emit('select', r.i)">
        <rect :x="0" :y="r.y - ROW / 2 - 2" :width="width" :height="ROW" :fill="selected === r.i ? 'color-mix(in srgb, var(--accent) 14%, transparent)' : 'transparent'" />
        <text x="4" :y="r.y + 4" fill="var(--muted)" font-size="10">+{{ (r.m.t - start).toFixed(2) }}</text>
        <path v-if="r.self" :d="`M${r.x1},${r.y - 6} h24 v12 h-24`" fill="none" :stroke="color(r.m)" marker-end="url(#arrow)" />
        <line v-else :x1="r.x1" :x2="r.x2" :y1="r.y" :y2="r.y" :stroke="color(r.m)" stroke-width="1.6" marker-end="url(#arrow)" />
        <text :x="(r.x1 + r.x2) / 2 + (r.self ? 40 : 0)" :y="r.y - 5" text-anchor="middle" :fill="color(r.m)">
          {{ label(r) }}
        </text>
        <title>{{ r.m.label }} — {{ r.m.src }} → {{ r.m.dst }}</title>
      </g>
    </svg>
  </div>
</template>

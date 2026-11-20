<script setup>
// График uPlot для нескольких рядов [[время, значение], ...]. Ряды выравниваются по
// общему набору моментов времени; пропуски — null. Ширина следует за контейнером.
import { onMounted, onUnmounted, ref, watch } from "vue";
import uPlot from "uplot";

const props = defineProps({ title: String, series: Object, unit: String, points: Boolean });
const box = ref(null);
let plot = null;
let observer = null;
const PALETTE = ["#2f6fdb", "#e0703a", "#1f8a4c", "#a24bd1", "#c8372d", "#1594a8", "#b7791f", "#d0479b", "#5d6b7a", "#6b8e23"];

function aligned() {
  const names = Object.keys(props.series || {}).filter((n) => props.series[n].length);
  const times = [...new Set(names.flatMap((n) => props.series[n].map((p) => p[0])))].sort((a, b) => a - b);
  const index = new Map(times.map((t, i) => [t, i]));
  const columns = names.map((n) => {
    const column = new Array(times.length).fill(null);
    for (const [t, v] of props.series[n]) column[index.get(t)] = v;
    return column;
  });
  return { names, data: [times, ...columns] };
}

function draw() {
  const { names, data } = aligned();
  const style = getComputedStyle(document.documentElement);
  const muted = style.getPropertyValue("--muted").trim();
  const grid = style.getPropertyValue("--line").trim();
  const axis = { stroke: muted, grid: { stroke: grid, width: 1 }, ticks: { stroke: grid } };
  plot?.destroy();
  plot = new uPlot(
    {
      width: box.value.clientWidth || 600,
      height: 220,
      legend: { live: true },
      scales: { x: { time: true } },
      axes: [axis, { ...axis, label: props.unit, size: 60 }],
      series: [
        {},
        ...names.map((n, i) => ({
          label: n.replace(/^(cpu|mem|sip|host|ai|voice|llm):/, ""),
          stroke: PALETTE[i % PALETTE.length],
          width: 1.5,
          spanGaps: !props.points,
          points: { show: props.points, size: 5 },
        })),
      ],
    },
    data,
    box.value,
  );
}

watch(() => props.series, draw, { deep: false });
onMounted(() => {
  draw();
  observer = new ResizeObserver(() => plot?.setSize({ width: box.value.clientWidth, height: 220 }));
  observer.observe(box.value);
});
onUnmounted(() => {
  observer?.disconnect();
  plot?.destroy();
});
</script>

<template>
  <div class="card">
    <strong>{{ title }}</strong>
    <div ref="box" />
  </div>
</template>

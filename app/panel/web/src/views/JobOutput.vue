<script setup>
// Живой вывод задания (SSE). При смене задания старый поток закрывается.
import { nextTick, onUnmounted, ref, watch } from "vue";
import { lineClass, listen } from "../api.js";

const props = defineProps({ job: Object });
const emit = defineEmits(["done"]);
const lines = ref([]);
const result = ref(null);
const box = ref(null);
let close = null;

watch(
  () => props.job?.id,
  (id) => {
    close?.();
    lines.value = [];
    result.value = null;
    if (!id) return;
    close = listen(
      `/api/jobs/${encodeURIComponent(id)}/stream`,
      (data) => {
        lines.value.push(data.line);
        if (lines.value.length > 5000) lines.value.shift();
        const el = box.value;
        const atEnd = el && el.scrollTop + el.clientHeight >= el.scrollHeight - 30;
        if (atEnd) nextTick(() => (el.scrollTop = el.scrollHeight));
      },
      (info) => {
        result.value = info;
        emit("done", info);
      },
    );
  },
  { immediate: true },
);
onUnmounted(() => close?.());
</script>

<template>
  <div v-if="job">
    <div class="row" style="margin-bottom: 6px">
      <strong>{{ job.name }}</strong>
      <span class="mono muted">{{ job.command }}</span>
      <span v-if="!result" class="warn">выполняется…</span>
      <span v-else :class="result.code === 0 ? 'good' : 'bad'">код {{ result.code }}</span>
      <span class="muted mono">{{ job.log }}</span>
    </div>
    <pre ref="box" class="output" style="max-height: 60vh"><span
      v-for="(line, i) in lines" :key="i" :class="lineClass(line)">{{ line }}
</span></pre>
  </div>
</template>

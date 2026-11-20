<script setup>
// Проверки: запуск, живой вывод, история заданий (вывод любого прошлого задания).
import { onActivated, ref } from "vue";
import { clock, get, post } from "../api.js";
import JobOutput from "./JobOutput.vue";

const props = defineProps({ status: Object });
const emit = defineEmits(["refresh"]);
const checks = [
  { name: "stand-check", title: "Готовность к телефону", note: "stand_check.py: контейнеры, PLMN, SIM, самотест AI" },
  { name: "verify-all", title: "Все проверки", note: "verify-all.sh: 15–40 минут, перезапускает S-CSCF" },
  { name: "verify:verify-ims", title: "IMS", note: "DNS, HSS, регистрация" },
  { name: "verify:verify-ims-call", title: "Звонок", note: "обычный звонок через SIP AS" },
  { name: "verify:verify-voice-agent", title: "Voice Agent", note: "номер услуги" },
  { name: "verify:verify-translation", title: "Перевод 1003", note: "русская речь — английский" },
  { name: "verify:verify-transcription", title: "Запись 1004", note: "запись и расшифровка" },
];
const jobs = ref([]);
const job = ref(null);
const message = ref("");

async function load() {
  jobs.value = (await get("/api/jobs")).jobs;
}

async function run(check) {
  message.value = "";
  if (check.name === "verify-all" && !confirm("verify-all перезапускает S-CSCF: телефоны перерегистрируются. Запустить?")) return;
  try {
    job.value = await post(`/api/actions/${encodeURIComponent(check.name)}`);
    emit("refresh");
    load();
  } catch (e) {
    message.value = e.message;
  }
}

function duration(j) {
  return j.ended ? `${Math.round(j.ended - j.started)} с` : "идёт";
}

onActivated(load);
load();
</script>

<template>
  <h2>Запустить</h2>
  <div class="grid">
    <div v-for="c in checks" :key="c.name" class="card">
      <div class="row" style="justify-content: space-between">
        <strong>{{ c.title }}</strong>
        <button class="primary" :disabled="Boolean(props.status?.job)" @click="run(c)">Запуск</button>
      </div>
      <div class="muted">{{ c.note }}</div>
    </div>
  </div>
  <p v-if="message" class="bad">{{ message }}</p>

  <template v-if="job">
    <h2>Вывод</h2>
    <JobOutput :job="job" @done="load(); emit('refresh')" />
  </template>

  <h2>История <button @click="load">обновить</button></h2>
  <table>
    <tr><th>Начало</th><th>Задание</th><th>Длительность</th><th>Код</th></tr>
    <tr v-for="j in jobs" :key="j.id" class="pick" :class="{ active: job?.id === j.id }" @click="job = j">
      <td>{{ clock(j.started) }}</td>
      <td class="mono">{{ j.name }}</td>
      <td>{{ duration(j) }}</td>
      <td :class="j.code === 0 ? 'good' : j.code === null ? 'warn' : 'bad'">{{ j.code ?? "…" }}</td>
    </tr>
  </table>
</template>

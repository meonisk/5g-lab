<script setup>
// Обзор: кнопки стенда и радио, карточки контейнеров с перезапуском, вывод задания.
import { computed, ref } from "vue";
import { post } from "../api.js";
import JobOutput from "./JobOutput.vue";

const props = defineProps({ status: Object });
const emit = defineEmits(["refresh"]);
const job = ref(null);
const message = ref("");

const groups = [
  { id: "core", title: "Ядро 5G (OAI)" },
  { id: "ims", title: "IMS" },
  { id: "ai", title: "AI" },
  { id: "panel", title: "Панель" },
  { id: "init", title: "Подготовка (однократно)" },
];
const buttons = [
  { name: "stand-up", title: "Включить стенд", cls: "primary" },
  { name: "stand-down", title: "Выключить стенд", cls: "danger", confirm: "Выключить весь стенд: радио, IMS, AI и ядро?" },
  { name: "gnb-up", title: "gNB SDR: включить" },
  { name: "gnb-down", title: "gNB SDR: выключить", cls: "danger", confirm: "Остановить gNB? Телефоны потеряют сеть." },
  { name: "rfsim-up", title: "rfsim: включить" },
  { name: "rfsim-down", title: "rfsim: выключить", cls: "danger" },
  { name: "phones", title: "Телефоны в IMS" },
  { name: "sims", title: "SIM в UDR и PyHSS" },
  { name: "core-check", title: "Настройка ядра" },
];
const sudoNeeded = new Set(["stand-up", "stand-down", "gnb-up", "gnb-down", "rfsim-up", "rfsim-down"]);
const busy = computed(() => Boolean(props.status?.job));

async function run(action) {
  if (action.confirm && !confirm(action.confirm)) return;
  message.value = "";
  try {
    job.value = await post(`/api/actions/${encodeURIComponent(action.name)}`);
    emit("refresh");
  } catch (e) {
    message.value = e.message;
  }
}

function restart(name) {
  run({ name: `restart:${name}`, confirm: `Перезапустить ${name}?` });
}

function dot(c) {
  if (c.state !== "running") return c.group === "init" && c.status.startsWith("Exited (0)") ? "good" : "bad";
  return c.health === "unhealthy" ? "bad" : c.health === "starting" ? "warn" : "good";
}

function radioText(p) {
  return { gnb: "gNB SDR (наш)", "rfsim-gnb": "gNB rfsim", "rfsim-ue": "UE rfsim", foreign: "чужой nr-softmodem" }[p.kind];
}
</script>

<template>
  <div v-if="!status" class="muted">Загрузка…</div>
  <template v-else>
    <h2>Управление</h2>
    <div class="row">
      <button
        v-for="b in buttons"
        :key="b.name"
        :class="b.cls"
        :disabled="busy && !['phones', 'sims', 'core-check'].includes(b.name)"
        :title="sudoNeeded.has(b.name) && !status.sudo ? 'нужен sudo без пароля: scripts/panel.sh sudoers' : ''"
        @click="run(b)"
      >
        {{ b.title }}<span v-if="sudoNeeded.has(b.name) && !status.sudo" class="warn"> · нужен sudo</span>
      </button>
    </div>
    <p v-if="!status.sudo" class="muted">
      sudo без пароля не настроен: радио и включение стенда из панели не сработают. Правило:
      <span class="mono">scripts/panel.sh sudoers</span>; или в терминале на сервере:
      <span class="mono">scripts/stand.sh up</span>.
    </p>
    <p v-if="message" class="bad">{{ message }}</p>

    <h2>Радио</h2>
    <div class="row">
      <span v-if="!status.radio.length" class="muted">nr-softmodem не запущен</span>
      <span v-for="p in status.radio" :key="p.pid" class="card mono">{{ radioText(p) }} · PID {{ p.pid }}</span>
      <span class="muted">хост: нагрузка {{ status.host.load?.toFixed(2) }}, память
        {{ status.host.mem_used_mib }} / {{ status.host.mem_total_mib }} МиБ</span>
    </div>

    <template v-for="g in groups" :key="g.id">
      <template v-if="status.containers.some((c) => c.group === g.id)">
        <h2>{{ g.title }}</h2>
        <div class="grid">
          <div v-for="c in status.containers.filter((c) => c.group === g.id)" :key="c.name" class="card">
            <div class="row" style="justify-content: space-between">
              <span><i class="dot" :class="dot(c)" /><strong>{{ c.name }}</strong></span>
              <button v-if="c.state === 'running' && g.id !== 'init'" :disabled="busy" @click="restart(c.name)">↻</button>
            </div>
            <div class="muted">{{ c.status }}</div>
          </div>
        </div>
      </template>
    </template>

    <template v-if="job">
      <h2>Задание</h2>
      <JobOutput :job="job" @done="emit('refresh')" />
    </template>
  </template>
</template>

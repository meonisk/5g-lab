<script setup>
// Звонки: диалоги SIP из захвата, лестничная диаграмма и текст выбранного сообщения.
// «Следить» — автоматически открывать самый новый диалог.
import { onActivated, onDeactivated, ref } from "vue";
import { clock, get } from "../api.js";
import Ladder from "./Ladder.vue";

const kind = ref("calls");
const calls = ref([]);
const online = ref(true);
const dialog = ref(null);
const selected = ref(null);
const follow = ref(false);
const openId = ref("");
let timer;

async function load() {
  const body = await get(`/api/calls?kind=${kind.value}`);
  calls.value = body.calls;
  online.value = body.online;
  if (follow.value && calls.value[0] && calls.value[0].call_id !== openId.value) open(calls.value[0].call_id);
  else if (openId.value) open(openId.value, true);
}

async function open(callId, keepSelection = false) {
  openId.value = callId;
  try {
    dialog.value = await get(`/api/calls/${encodeURIComponent(callId)}`);
    if (!keepSelection) selected.value = null;
  } catch {
    dialog.value = null;
  }
}

function result(c) {
  if (!c.final) return { cls: "warn", text: "…" };
  return { cls: c.final < 300 ? "good" : "bad", text: c.final };
}

onActivated(() => {
  load();
  timer = setInterval(load, 2000);
});
onDeactivated(() => clearInterval(timer));
</script>

<template>
  <p v-if="!online" class="bad">
    Захват SIP не отвечает: <span class="mono">scripts/panel.sh status</span> (контейнер lab-panel-sipcap).
  </p>
  <div class="row">
    <select v-model="kind" @change="load">
      <option value="calls">звонки (INVITE)</option>
      <option value="register">регистрации</option>
      <option value="other">прочее</option>
      <option value="all">всё</option>
    </select>
    <label><input v-model="follow" type="checkbox" /> следить за новыми</label>
    <span class="muted">трафик телефона внутри IPsec не виден; nonce и ключи скрыты</span>
  </div>
  <div class="layout">
    <div class="card list">
      <table>
        <tr><th>Время</th><th>Метод</th><th>От</th><th>Кому</th><th>Итог</th></tr>
        <tr v-for="c in calls" :key="c.call_id" class="pick" :class="{ active: c.call_id === openId }" @click="open(c.call_id)">
          <td>{{ clock(c.start) }}</td>
          <td class="mono">{{ c.method }}</td>
          <td class="mono">{{ c.from }}</td>
          <td class="mono">{{ c.to }}</td>
          <td :class="result(c).cls">{{ result(c).text }}<span v-if="c.bye" class="muted"> BYE</span></td>
        </tr>
        <tr v-if="!calls.length"><td colspan="5" class="muted">пока пусто — позвоните или зарегистрируйте телефон</td></tr>
      </table>
    </div>
    <div v-if="dialog" class="card detail">
      <div class="row muted mono">Call-ID {{ dialog.summary.call_id }} · {{ dialog.summary.count }} сообщений</div>
      <Ladder :messages="dialog.messages" :selected="selected" @select="selected = $event" />
      <template v-if="selected !== null">
        <div class="row mono muted" style="margin-top: 8px">
          {{ dialog.messages[selected].src }} ({{ dialog.messages[selected].src_name || "?" }}) →
          {{ dialog.messages[selected].dst }} ({{ dialog.messages[selected].dst_name || "?" }})
        </div>
        <pre class="output" style="max-height: 40vh">{{ dialog.messages[selected].text }}</pre>
      </template>
    </div>
  </div>
</template>

<style scoped>
.layout { display: grid; grid-template-columns: minmax(320px, 1fr) 2fr; gap: 12px; margin-top: 10px; align-items: start; }
.list { max-height: 80vh; overflow: auto; padding: 4px; }
.detail { min-width: 0; }
@media (max-width: 1000px) { .layout { grid-template-columns: 1fr; } }
</style>

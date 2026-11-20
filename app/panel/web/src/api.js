// Обращения к API панели. Изменяющие запросы несут X-Panel: сервер без него отказывает.
export async function get(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`${response.status} ${path}`);
  return response.json();
}

export async function post(path) {
  const response = await fetch(path, { method: "POST", headers: { "X-Panel": "1" } });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.error || `${response.status}`);
  return body;
}

// Поток SSE; onEnd — событие «end» (задание завершилось). Возвращает функцию закрытия.
export function listen(path, onData, onEnd) {
  const source = new EventSource(path);
  source.onmessage = (event) => onData(JSON.parse(event.data));
  source.addEventListener("end", (event) => {
    source.close();
    onEnd?.(JSON.parse(event.data));
  });
  return () => source.close();
}

export function clock(seconds) {
  return seconds ? new Date(seconds * 1000).toLocaleTimeString("ru-RU") : "—";
}

// Строки результатов проверок: PASS/OK — зелёные, FAIL/ERROR — красные, SKIP/WARN — жёлтые.
export function lineClass(line) {
  if (/\b(FAIL|ERROR)\b|\[FAIL/.test(line)) return "bad";
  if (/\b(WARN|SKIP)\b/.test(line)) return "warn";
  if (/\bPASS\b|\[OK|ГОТОВ/.test(line)) return "good";
  return "";
}

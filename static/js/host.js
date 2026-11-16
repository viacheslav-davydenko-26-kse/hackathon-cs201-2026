// Екран ведучого: лобі + QR, раунд, reveal, лідерборд.
// Власник: Андрій.
//
// Як працює (docs/contract.md §5):
//   1. roomCreate() → {code, host_key, qr_svg}. host_key живе лише в sessionStorage цієї вкладки.
//   2. pollRoom() раз на секунду → RoomState → малюємо екран за state.status.
//   3. Кнопки «Старт» і «Далі» викликають roomStart / roomNext, відповідь одразу малюємо.
//   Сервер сам переводить round → reveal, але лише коли його опитують, тому poll іде весь час.
//
// Щоб екран не мерехтів, бічна панель перебудовується лише коли змінився «ключ» стану
// (статус, раунд, кількість підказок/гравців). Таймер і «відповіли N/M» оновлюються окремо.

import {
  getRegions, getGeo, roomCreate, roomStart, roomNext, pollRoom, ApiError, HEAT_COLORS,
} from './api.js';
import { createMap } from './map.js';
import { renderCard } from './card.js';

/** @typedef {import('./types.js').RoomState} RoomState */
/** @typedef {import('./types.js').RoomCreated} RoomCreated */

const SESSION_KEY = 'dece_host';
const ANSWER_COLOR = '#1e8449';
const CATEGORY_LABELS = { war: 'Війна', demography: 'Демографія', cars: 'Авто', education: 'Освіта' };
const LOW_TIME = 5; // с, коли таймер стає червоним

const $ = (id) => document.getElementById(id);
const ui = {
  roomCode: $('room-code'),
  roundNo: $('round-no'),
  qrStage: $('qr-stage'),
  qr: $('qr'),
  joinUrl: $('join-url'),
  map: $('map'),
  stageLoading: $('stage-loading'),
  side: $('side'),
};

// ---------------------------------------------------------------- стан
/** @type {{code: string, host_key: string, join_url: string, qr_svg: string}|null} */
let room = null;
/** @type {RoomState|null} */
let state = null;
let clockOffset = 0;        // server_now − локальний час, с
let sideKey = '';           // ключ останнього рендеру бічної панелі
let mapKey = '';            // ключ останнього рендеру карти
let map;
let regionsById = new Map();
let stopPoll = null;
let cardView = null;
let busy = false;

/** Живі елементи поточного екрана, які оновлює тік таймера / poll. */
let live = {};

// ---------------------------------------------------------------- утиліти
/** Створює елемент: h('div', {class: 'x'}, 'текст', child) */
function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') el.className = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v);
  }
  el.append(...children.filter((c) => c != null));
  return el;
}

const nowServer = () => Date.now() / 1000 + clockOffset;
const secondsLeft = (at) => (at == null ? null : Math.max(0, Math.ceil(at - nowServer())));
const regionName = (id) => regionsById.get(id)?.short_uk ?? id;

function saveRoom(r) {
  try { sessionStorage.setItem(SESSION_KEY, JSON.stringify(r)); } catch { /* приватний режим */ }
}

function loadRoom() {
  try { return JSON.parse(sessionStorage.getItem(SESSION_KEY) ?? 'null'); } catch { return null; }
}

function forgetRoom() {
  try { sessionStorage.removeItem(SESSION_KEY); } catch { /* ігноруємо */ }
}

// ---------------------------------------------------------------- спільні шматки UI
function panel(title, ...children) {
  return h('section', { class: 'panel' }, title ? h('h2', { class: 'panel__title' }, title) : null, ...children);
}

function hintsList(hints, total = 5) {
  const items = [];
  for (let i = 0; i < total; i++) {
    const hint = hints[i];
    if (hint) {
      items.push(h('li', { class: 'hint' },
        h('span', { class: 'hint__num' }, String(i + 1)),
        h('span', { class: 'hint__body' },
          h('span', {}, hint.text),
          h('span', { class: 'hint__tag' }, CATEGORY_LABELS[hint.category] ?? hint.category))));
    } else {
      items.push(h('li', { class: 'hint hint--locked' },
        h('span', { class: 'hint__num' }, String(i + 1)),
        h('span', { class: 'hint__body' }, 'Ще не відкрита')));
    }
  }
  // Остання відкрита підказка з'являється з анімацією.
  const last = items[hints.length - 1];
  last?.classList.add('hint--new');
  return h('ol', { class: 'hints' }, ...items);
}

function leaderboard(rows, { showDelta = false, limit = 10 } = {}) {
  return h('ol', { class: 'leaderboard' },
    ...rows.slice(0, limit).map((r, i) => h('li', { class: 'lb-row' },
      h('span', { class: 'lb-row__place' }, String(i + 1)),
      h('span', { class: 'lb-row__name' }, r.name),
      h('span', { class: 'lb-row__delta' }, showDelta && r.delta > 0 ? `+${r.delta}` : ''),
      h('span', { class: 'lb-row__score' }, String(r.score)))));
}

function answeredBlock() {
  const label = h('span', { class: 'stat__value' });
  const bar = h('div', { class: 'progress__bar' });
  live.answered = { label, bar };
  return panel('Відповіли',
    h('div', { class: 'stat' }, label),
    h('div', { class: 'progress' }, bar));
}

function button(text, onclick, primary = true) {
  return h('button', { class: `btn btn--block${primary ? ' btn--primary' : ''}`, type: 'button', onclick }, text);
}

// ---------------------------------------------------------------- екрани (бічна панель)
function sideLobby(s) {
  const players = s.players.length
    ? h('ul', { class: 'chips' }, ...s.players.map((p) => h('li', { class: 'chip' }, p.name)))
    : h('p', { class: 'muted' }, 'Поки нікого. Скануйте QR!');
  return [
    panel(`Гравці: ${s.players.length}`, players),
    button('Старт', onStart),
  ];
}

function sideRound(s) {
  const timer = h('div', { class: 'timer' });
  const nextHint = h('p', { class: 'muted' });
  live.timer = timer;
  live.nextHint = nextHint;
  return [
    panel('До кінця раунду', timer, nextHint),
    answeredBlock(),
    panel('Підказки', hintsList(s.hints)),
    button('Завершити раунд', onNext, false),
  ];
}

function sideReveal(s) {
  const r = s.reveal;
  const last = s.round_no >= s.total_rounds;
  const answer = regionsById.get(r.answer_region_id)?.name_uk ?? r.answer_region_id;
  const correct = r.guesses.filter((g) => g.region_id === r.answer_region_id).length;

  const card = h('section', { class: 'panel', hidden: '' });
  showCard(card, r.card);

  return [
    h('section', { class: 'panel result result--win' },
      h('h2', { class: 'result__title' }, answer),
      h('p', {}, `Вгадали ${correct} з ${s.total}`)),
    panel('Лідерборд', leaderboard(s.leaderboard, { showDelta: true })),
    button(last ? 'Підсумки' : 'Наступний раунд', onNext),
    card,
  ];
}

function sideFinished(s) {
  const winner = s.leaderboard[0];
  return [
    h('section', { class: 'panel result result--win' },
      h('h2', { class: 'final-title' }, winner ? `🏆 ${winner.name}` : 'Гру завершено'),
      winner ? h('p', {}, `${winner.score} балів`) : null),
    panel('Фінальний лідерборд', leaderboard(s.leaderboard)),
    button('Нова гра', onNewRoom, false),
  ];
}

function sideError(message) {
  return [
    panel('Помилка', h('p', { class: 'error' }, message)),
    button('Нова кімната', onNewRoom),
  ];
}

// ---------------------------------------------------------------- картка Матвія
function showCard(container, card) {
  cardView?.destroy();
  cardView = null;
  if (!card) return;
  try {
    cardView = renderCard(container, card);
    container.hidden = false;
  } catch (e) {
    // card.js ще може бути не готовий — reveal від цього не ламається.
    console.warn('card:', e);
  }
}

// ---------------------------------------------------------------- рендер
function renderStage(s) {
  const lobby = s.status === 'lobby';
  ui.stageLoading.hidden = true;
  ui.qrStage.hidden = !lobby;
  ui.map.hidden = lobby;

  const key = `${s.status}:${s.round_no}`;
  if (key === mapKey) return;
  mapKey = key;
  map.reset();

  if (s.status === 'reveal' || (s.status === 'finished' && s.reveal)) {
    const r = s.reveal;
    // Де шукала зала: інтенсивність ∝ кількості відповідей, лінії від кожної відповіді до правильної.
    map.choropleth(r.distribution);
    for (const g of r.guesses) {
      if (g.region_id !== r.answer_region_id) {
        map.drawLine(g.region_id, r.answer_region_id, HEAT_COLORS[g.heat]);
      }
    }
    map.colorRegion(r.answer_region_id, ANSWER_COLOR);
    map.select(r.answer_region_id);
  }
}

function renderSide(s) {
  const key = [s.status, s.round_no, s.hints.length, s.players.length].join(':');
  if (key === sideKey) return;
  sideKey = key;
  live = {};
  const build = { lobby: sideLobby, round: sideRound, reveal: sideReveal, finished: sideFinished }[s.status];
  ui.side.replaceChildren(...(build ? build(s) : []));
}

function renderLive() {
  if (!state) return;
  if (live.answered) {
    const { answered, total } = state;
    live.answered.label.textContent = `${answered} / ${total}`;
    live.answered.bar.style.width = total ? `${(answered / total) * 100}%` : '0%';
  }
  if (live.timer) {
    const left = secondsLeft(state.ends_at);
    live.timer.textContent = left == null ? '—' : `${left} с`;
    live.timer.classList.toggle('timer--low', left != null && left <= LOW_TIME);
  }
  if (live.nextHint) {
    const next = secondsLeft(state.next_hint_at);
    live.nextHint.textContent = next == null ? 'Усі підказки відкрито' : `Наступна підказка через ${next} с`;
  }
}

/** @param {RoomState} s */
function applyState(s) {
  state = s;
  clockOffset = s.server_now - Date.now() / 1000;
  ui.roundNo.textContent = s.round_no ? `${s.round_no} / ${s.total_rounds}` : '—';
  renderStage(s);
  renderSide(s);
  renderLive();
}

function showFatal(message) {
  stopPoll?.();
  sideKey = '';
  ui.side.replaceChildren(...sideError(message));
}

// ---------------------------------------------------------------- дії хоста
async function hostAction(fn) {
  if (busy || !room) return;
  busy = true;
  try {
    applyState(await fn(room.code, room.host_key));
  } catch (e) {
    handleError(e);
  } finally {
    busy = false;
  }
}

const onStart = () => hostAction(roomStart);
const onNext = () => hostAction(roomNext);

function onNewRoom() {
  forgetRoom();
  location.reload();
}

/** Розгалуження лише за error.code (docs/contract.md §2). */
function handleError(e) {
  if (!(e instanceof ApiError)) {
    console.error(e);
    return; // мережа моргнула — наступний poll спробує знову
  }
  switch (e.code) {
    case 'bad_host_key':
      showFatal('Сесію ведучого втрачено.');
      break;
    case 'room_not_found':
      // Сервер перезапустився і кімнати вже нема — створюємо нову.
      forgetRoom();
      stopPoll?.();
      openRoom(true);
      break;
    case 'invalid_state':
      break; // наступний poll виправить екран
    default:
      console.error(e);
  }
}

// ---------------------------------------------------------------- старт
async function openRoom(forceNew = false) {
  room = forceNew ? null : loadRoom();
  if (!room) {
    /** @type {RoomCreated} */
    const created = await roomCreate();
    room = created;
    saveRoom(room);
  }
  ui.roomCode.textContent = room.code;
  ui.roomCode.hidden = false;
  ui.qr.innerHTML = room.qr_svg; // SVG від нашого ж сервера (segno), контракт дозволяє innerHTML
  ui.joinUrl.textContent = room.join_url;

  sideKey = '';
  mapKey = '';
  stopPoll = pollRoom(room.code, null, applyState, handleError);
}

async function init() {
  const [regions, geo] = await Promise.all([getRegions(), getGeo()]);
  regionsById = new Map(regions.map((r) => [r.id, r]));
  map = createMap(ui.map, geo, { interactive: false, labels: true });

  const params = new URLSearchParams(location.search);
  await openRoom(params.has('new'));

  // Таймер тікає локально між poll-ами; кожен новий state його синхронізує.
  setInterval(renderLive, 250);
}

init().catch((e) => {
  console.error(e);
  showFatal('Не вдалося створити кімнату. Перевір, що сервер запущено.');
});

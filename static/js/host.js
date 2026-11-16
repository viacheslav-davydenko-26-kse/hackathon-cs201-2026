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
  getConfig, getRegions, getGeo, roomCreate, roomStart, roomNext, pollRoom, ApiError, HEAT_COLORS,
} from './api.js';
import { createMap } from './map.js';
import { renderCard } from './card.js';
import { icon, hydrateIcons } from './icons.js';
import { confetti, playSound, createSoundToggle } from './fx.js';

/** @typedef {import('./types.js').RoomState} RoomState */
/** @typedef {import('./types.js').RoomCreated} RoomCreated */

const SESSION_KEY = 'dece_host';
const ANSWER_COLOR = '#12804a';
const CATEGORIES = {
  war: { label: 'Війна', icon: 'siren' },
  demography: { label: 'Демографія', icon: 'users' },
  cars: { label: 'Авто', icon: 'car' },
  education: { label: 'Освіта', icon: 'graduation-cap' },
};
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
let roundSeconds = 35;      // з /api/config, для смужки часу
let clockOffset = 0;        // server_now − локальний час, с
let sideKey = '';           // ключ останнього рендеру бічної панелі
let mapKey = '';            // ключ останнього рендеру карти
let hintKey = '';           // раунд:кількість підказок — коли змінюється, показуємо нову підказку великою
let flashTimer = null;
let map;
let regionsById = new Map();
let stopPoll = null;
let cardView = null;
let busy = false;

/** Живі елементи поточного екрана, які оновлює тік таймера / poll. */
let live = {};

// ---------------------------------------------------------------- утиліти
/** Створює елемент: h('div', {class: 'x', onclick: fn}, 'текст', child) */
function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v);
  }
  el.append(...children.filter((c) => c != null));
  return el;
}

const nowServer = () => Date.now() / 1000 + clockOffset;
const secondsLeft = (at) => (at == null ? null : Math.max(0, Math.ceil(at - nowServer())));

/** 1 бал, 2 бали, 5 балів, 11 балів, 21 бал. */
function pointsWord(n) {
  const d10 = n % 10;
  const d100 = n % 100;
  if (d10 === 1 && d100 !== 11) return 'бал';
  if (d10 >= 2 && d10 <= 4 && (d100 < 12 || d100 > 14)) return 'бали';
  return 'балів';
}

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
function panel(title, iconName, extra, ...children) {
  const head = title
    ? h('div', { class: 'panel__head' },
      h('h2', { class: 'panel__title' }, iconName ? icon(iconName) : null, title), extra)
    : null;
  return h('section', { class: 'panel' }, head, ...children);
}

function hintsList(hints, total = 5) {
  const items = [];
  for (let i = 0; i < total; i++) {
    const hint = hints[i];
    if (hint) {
      const cat = CATEGORIES[hint.category] ?? { label: hint.category, icon: 'lightbulb' };
      items.push(h('li', { class: 'hint' },
        h('span', { class: 'hint__num' }, String(i + 1)),
        h('span', { class: 'hint__body' },
          h('span', {}, hint.text),
          h('span', { class: 'hint__tag' }, icon(cat.icon), cat.label))));
    } else {
      items.push(h('li', { class: 'hint hint--locked' },
        h('span', { class: 'hint__num' }, icon('lock')),
        h('span', {}, 'Ще не відкрита')));
    }
  }
  // Остання відкрита підказка спалахує жовтим, щоб зала її помітила.
  items[hints.length - 1]?.classList.add('hint--pop');
  return h('ol', { class: 'hints' }, ...items);
}

function leaderboard(rows, { showDelta = false, limit = 10 } = {}) {
  return h('ol', { class: 'leaderboard' },
    ...rows.slice(0, limit).map((r, i) => h('li', { class: `lb-row${i === 0 ? ' lb-row--first' : ''}` },
      h('span', { class: 'lb-row__place' }, i === 0 ? icon('crown') : String(i + 1)),
      h('span', { class: 'lb-row__name' }, r.name),
      h('span', { class: 'lb-row__delta' }, showDelta && r.delta > 0 ? `+${r.delta}` : ''),
      h('span', { class: 'lb-row__score' }, String(r.score)))));
}

function button(text, iconName, onclick, primary = true) {
  return h('button', { class: `btn btn--block${primary ? ' btn--primary' : ''}`, type: 'button', onclick },
    icon(iconName), text);
}

function resultPanel(kind, iconName, title, sub) {
  return h('section', { class: `panel result result--${kind}` },
    h('div', { class: 'result__head' },
      h('span', { class: 'result__icon' }, icon(iconName, 'icon--lg')),
      h('div', {},
        h('h2', { class: 'result__title' }, title),
        sub ? h('p', { class: 'result__sub' }, sub) : null)));
}

// ---------------------------------------------------------------- екрани (бічна панель)
function sideLobby(s) {
  const players = s.players.length
    ? h('ul', { class: 'chips' }, ...s.players.map((p) => h('li', { class: 'chip' }, icon('user'), p.name)))
    : h('p', { class: 'empty' }, icon('users'), 'Поки нікого. Скануйте QR!');
  const start = button('Почати гру', 'play', onStart);
  if (!s.players.length) start.disabled = true;
  const steps = [
    ['Відскануйте QR телефоном', 'user'],
    ['Читайте підказки з відкритих даних', 'lightbulb'],
    ['Тапніть область на карті — що раніше, то більше балів', 'map-pin'],
  ];
  return [
    panel('Гравці', 'users', h('span', { class: 'pill pill--accent' }, String(s.players.length)), players),
    start,
    panel('Як грати', 'target', null,
      h('ol', { class: 'hints' }, ...steps.map(([text], i) => h('li', { class: 'hint' },
        h('span', { class: 'hint__num' }, String(i + 1)),
        h('span', { class: 'hint__body' }, text))))),
  ];
}

function sideRound(s) {
  const timer = h('span', { class: 'timer' });
  const nextHint = h('span', { class: 'muted' });
  const timeBar = h('div', { class: 'progress__bar' });
  const answered = h('span', { class: 'big-num' });
  const answeredBar = h('div', { class: 'progress__bar' });
  live = { timer, nextHint, timeBar, answered, answeredBar };

  return [
    panel('До кінця раунду', 'timer', null,
      h('div', { class: 'timer-row' }, timer, nextHint),
      h('div', { class: 'progress' }, timeBar)),
    panel('Відповіли', 'users', answered,
      h('div', { class: 'progress' }, answeredBar)),
    panel('Підказки', 'lightbulb', h('span', { class: 'pill pill--accent' }, `${s.hints.length} / 5`),
      hintsList(s.hints)),
    button('Завершити раунд', 'flag', onNext, false),
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
    resultPanel('info', 'map-pin', answer, `Вгадали ${correct} з ${s.total}`),
    panel('Лідерборд', 'trophy', null, leaderboard(s.leaderboard, { showDelta: true })),
    button(last ? 'Підсумки' : 'Наступний раунд', last ? 'flag' : 'skip-forward', onNext),
    card,
  ];
}

function sideFinished(s) {
  const winner = s.leaderboard[0];
  return [
    winner
      ? resultPanel('win', 'trophy', winner.name, `Переможець · ${winner.score} ${pointsWord(winner.score)}`)
      : resultPanel('info', 'flag', 'Гру завершено'),
    panel('Фінальний лідерборд', 'trophy', null, leaderboard(s.leaderboard)),
    button('Нова гра', 'rotate-ccw', onNewRoom, false),
  ];
}

function sideError(message) {
  return [
    resultPanel('lose', 'circle-x', 'Помилка', message),
    button('Нова кімната', 'rotate-ccw', onNewRoom),
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
  hideHintFlash();

  // Ефекти на зміну статусу (один раз на раунд).
  if (s.status === 'reveal') {
    const anyCorrect = s.reveal?.guesses.some((g) => g.region_id === s.reveal.answer_region_id);
    if (anyCorrect) confetti();
    playSound(anyCorrect ? 'success' : 'fail');
  } else if (s.status === 'finished') {
    confetti({ big: true });
    playSound('fanfare');
  }

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
    live.answered.textContent = `${answered} / ${total}`;
    live.answeredBar.style.width = total ? `${(answered / total) * 100}%` : '0%';
  }
  if (live.timer) {
    const left = secondsLeft(state.ends_at);
    const low = left != null && left <= LOW_TIME;
    live.timer.textContent = left == null ? '—' : `${left} с`;
    live.timer.classList.toggle('timer--low', low);
    live.timeBar.style.width = left == null ? '0%' : `${Math.min(100, (left / roundSeconds) * 100)}%`;
    live.timeBar.classList.toggle('progress__bar--low', low);
  }
  if (live.nextHint) {
    const next = secondsLeft(state.next_hint_at);
    live.nextHint.textContent = next == null ? 'Усі підказки відкрито' : `наступна підказка через ${next} с`;
  }
}

// ---------------------------------------------------------------- нова підказка великою
/** Велика картка з текстом підказки поверх карти на ~4.5 с. */
function showHintFlash(hint, index, total = 5) {
  hideHintFlash();
  const el = h('div', { class: 'hint-flash', role: 'status' },
    h('span', { class: 'hint-flash__label' }, icon('lightbulb'), `Підказка ${index + 1} / ${total}`),
    h('p', { class: 'hint-flash__text' }, hint.text));
  ui.map.parentElement.append(el);
  playSound('hint');
  flashTimer = setTimeout(() => {
    el.classList.add('hint-flash--out');
    flashTimer = setTimeout(() => el.remove(), 400);
  }, 4500);
}

function hideHintFlash() {
  clearTimeout(flashTimer);
  document.querySelectorAll('.hint-flash').forEach((n) => n.remove());
}

function checkNewHint(s) {
  if (s.status !== 'round') {
    hintKey = '';
    return;
  }
  const key = `${s.round_no}:${s.hints.length}`;
  if (key === hintKey) return;
  hintKey = key;
  const last = s.hints[s.hints.length - 1];
  if (last) showHintFlash(last, s.hints.length - 1);
}

/** @param {RoomState} s */
function applyState(s) {
  state = s;
  clockOffset = s.server_now - Date.now() / 1000;
  ui.roundNo.hidden = !s.round_no;
  ui.roundNo.textContent = `Раунд ${s.round_no} / ${s.total_rounds}`;
  renderStage(s);
  renderSide(s);
  checkNewHint(s);
  renderLive();
}

function showFatal(message) {
  stopPoll?.();
  sideKey = '';
  ui.stageLoading.hidden = true;
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
      openRoom(true).catch(onInitError);
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
  ui.roomCode.replaceChildren(icon('users'), room.code);
  ui.roomCode.hidden = false;
  ui.qr.innerHTML = room.qr_svg; // SVG від нашого ж сервера (segno), контракт дозволяє innerHTML
  ui.joinUrl.textContent = room.join_url;

  sideKey = '';
  mapKey = '';
  stopPoll = pollRoom(room.code, null, applyState, handleError);
}

function onInitError(e) {
  console.error(e);
  showFatal('Не вдалося створити кімнату. Перевір, що сервер запущено.');
}

async function init() {
  hydrateIcons();
  document.querySelector('.topbar__right').append(createSoundToggle());
  const [config, regions, geo] = await Promise.all([getConfig(), getRegions(), getGeo()]);
  roundSeconds = config.round_seconds;
  regionsById = new Map(regions.map((r) => [r.id, r]));
  map = createMap(ui.map, geo, { interactive: false, labels: true });

  const params = new URLSearchParams(location.search);
  await openRoom(params.has('new'));

  // Таймер тікає локально між poll-ами; кожен новий state його синхронізує.
  setInterval(renderLive, 250);
}

init().catch(onInitError);

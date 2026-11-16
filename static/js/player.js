// Екран гравця на телефоні: ім'я, підказки, міні-карта, відповідь.
// Власник: Андрій (раніше Вадім).
//
// Потік (docs/contract.md §5):
//   play.html?room=K7QF → ім'я → roomJoin() → {player_id} у localStorage
//   → pollRoom(code, player_id) раз на секунду → екран за state.status:
//     lobby    «Чекаємо на старт»
//     round    підказки + карта → тап по області → «Відповісти: X» → roomGuess() → «Чекаємо інших»
//     reveal   правильна відповідь, мої бали за раунд, місце
//     finished місце і бали
// Після перезавантаження сторінки гравець продовжує без повторного join (player_id з localStorage).

import { getRegions, getGeo, roomJoin, roomGuess, pollRoom, ApiError, HEAT_COLORS } from './api.js?v=2';
import { createMap } from './map.js?v=2';
import { icon, hydrateIcons } from './icons.js?v=2';
import { confetti, playSound, animateNumber, buttonBusy } from './fx.js?v=2';

/** @typedef {import('./types.js').RoomState} RoomState */

const STORE_KEY = 'dece_player';
const ANSWER_COLOR = '#12804a';
const SELECT_COLOR = '#0057b8';
const LOW_TIME = 5;
const CATEGORIES = {
  war: { label: 'Війна', icon: 'siren' },
  demography: { label: 'Демографія', icon: 'users' },
  cars: { label: 'Авто', icon: 'car' },
  education: { label: 'Освіта', icon: 'graduation-cap' },
};
const HEAT_LABELS = { hot: 'Гаряче', warm: 'Тепло', cool: 'Прохолодно', cold: 'Холодно' };

const $ = (id) => document.getElementById(id);
const screens = ['loading', 'join', 'lobby', 'round', 'waiting', 'reveal', 'finished'];
const ui = Object.fromEntries(screens.map((s) => [s, $(`screen-${s}`)]));
Object.assign(ui, {
  roomPill: $('room-pill'), scorePill: $('score-pill'), score: $('score'),
  codeField: $('code-field'), codeInput: $('code-input'), nameInput: $('name-input'),
  joinError: $('join-error'), joinBtn: $('join-btn'),
  lobbyName: $('lobby-name'), lobbyPlayers: $('lobby-players'),
  roundNo: $('round-no'), timer: $('timer'), timerBar: $('timer-bar'),
  hintLatest: $('hint-latest'), hintsPrev: $('hints-prev'), hintsPrevPanel: $('hints-prev-panel'),
  hintsCount: $('hints-count'), nextHint: $('next-hint'), joinRoom: $('join-room'),
  mapPanel: $('map-panel'), map: $('map'), slotRound: $('map-slot-round'), slotReveal: $('map-slot-reveal'),
  waitingGuess: $('waiting-guess'), waitingAnswered: $('waiting-answered'),
  revealIcon: $('reveal-icon'), revealTitle: $('reveal-title'), revealSub: $('reveal-sub'),
  revealPoints: $('reveal-points'), revealPlace: $('reveal-place'),
  finalTitle: $('final-title'), finalPlace: $('final-place'), finalScore: $('final-score'),
  actionBar: $('action-bar'), guessBtn: $('guess-btn'), guessLabel: $('guess-label'),
  error: $('error'),
});

// ---------------------------------------------------------------- стан
/** @type {{room: string, player_id: string, name: string}|null} */
let me = null;
/** @type {RoomState|null} */
let state = null;
let regionsById = new Map();
let map = null;
let geo = null;
let stopPoll = null;
let clockOffset = 0;
let roundSeconds = 35;
let selected = null;        // область, обрана тапом, але ще не відправлена
let busy = false;
let screenKey = '';         // щоб не перемальовувати екран щосекунди
let mapKey = '';
let hintsKey = '';

// ---------------------------------------------------------------- утиліти
function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  el.append(...children.filter((c) => c != null));
  return el;
}

const nowServer = () => Date.now() / 1000 + clockOffset;
const secondsLeft = (at) => (at == null ? null : Math.max(0, Math.ceil(at - nowServer())));
const regionName = (id) => regionsById.get(id)?.short_uk ?? id;

function pointsWord(n) {
  const d10 = n % 10;
  const d100 = n % 100;
  if (d10 === 1 && d100 !== 11) return 'бал';
  if (d10 >= 2 && d10 <= 4 && (d100 < 12 || d100 > 14)) return 'бали';
  return 'балів';
}

function loadMe() {
  try { return JSON.parse(localStorage.getItem(STORE_KEY) ?? 'null'); } catch { return null; }
}

function saveMe(value) {
  try {
    if (value) localStorage.setItem(STORE_KEY, JSON.stringify(value));
    else localStorage.removeItem(STORE_KEY);
  } catch { /* приватний режим — працюємо без збереження */ }
}

function showError(message) {
  ui.error.replaceChildren(...(message ? [icon('circle-x'), message] : []));
  ui.error.hidden = !message;
}

/** Показує один «екран» (секцію), решту ховає. Нова секція з'являється плавно. */
function show(...names) {
  for (const s of screens) {
    const visible = names.includes(s);
    if (visible && ui[s].hidden) {
      ui[s].hidden = false;
      ui[s].classList.remove('rise-in');
      void ui[s].offsetWidth;
      ui[s].classList.add('rise-in');
    } else if (!visible) {
      ui[s].hidden = true;
    }
  }
}

// ---------------------------------------------------------------- приєднання
function showJoin(message = '', { askCode = false } = {}) {
  stopPoll?.();
  stopPoll = null;
  ui.mapPanel.hidden = true;
  ui.actionBar.hidden = true;
  ui.scorePill.hidden = true;
  show('join');
  ui.codeField.hidden = !askCode;
  ui.joinRoom.hidden = askCode || !roomFromUrl();
  ui.joinRoom.textContent = `Кімната ${roomFromUrl()}`;
  ui.joinError.replaceChildren(...(message ? [icon('circle-x'), message] : []));
  ui.joinError.hidden = !message;
  (askCode ? ui.codeInput : ui.nameInput).focus();
}

async function onJoin(e) {
  e.preventDefault();
  if (busy) return;
  const code = (ui.codeField.hidden ? roomFromUrl() : ui.codeInput.value).trim().toUpperCase();
  const name = ui.nameInput.value.trim();
  if (!/^[A-Z0-9]{4}$/.test(code)) {
    showJoin('Код кімнати — 4 символи з екрана ведучого.', { askCode: true });
    return;
  }
  if (!name || name.length > 20) {
    showJoin('Введи ім’я (до 20 символів).', { askCode: !ui.codeField.hidden });
    ui.nameInput.focus();
    return;
  }

  busy = true;
  const done = buttonBusy(ui.joinBtn);
  try {
    const { player_id } = await roomJoin(code, name);
    me = { room: code, player_id, name };
    saveMe(me);
    if (!roomFromUrl()) history.replaceState(null, '', `?room=${code}`);
    startPolling();
  } catch (err) {
    const askCode = !ui.codeField.hidden;
    switch (err instanceof ApiError ? err.code : '') {
      case 'room_not_found': showJoin('Кімнату не знайдено. Перевір код на великому екрані.', { askCode: true }); break;
      case 'name_taken': showJoin('Це ім’я вже зайняте — обери інше.', { askCode }); break;
      case 'invalid_name': showJoin('Ім’я має бути від 1 до 20 символів.', { askCode }); break;
      case 'invalid_state': showJoin('Ця гра вже завершилась. Відскануй QR нової кімнати.', { askCode: true }); break;
      default: showJoin('Не вдалося підключитися. Спробуй ще раз.', { askCode }); console.error(err);
    }
  } finally {
    done();
    busy = false;
  }
}

const roomFromUrl = () => (new URLSearchParams(location.search).get('room') ?? '').trim().toUpperCase();

// ---------------------------------------------------------------- рендер за статусом
function renderLobby(s) {
  show('lobby');
  ui.lobbyName.textContent = me.name;
  ui.lobbyPlayers.replaceChildren(...s.players.map((p) => h('li', { class: `chip${p.id === me.player_id ? ' chip--me' : ''}` },
    icon('user'), p.name)));
}

function renderHints(s) {
  const key = `${s.round_no}:${s.hints.length}`;
  if (key === hintsKey) return;
  const isNew = hintsKey.startsWith(`${s.round_no}:`) || hintsKey === '';
  hintsKey = key;
  const item = (hint, cls) => {
    const cat = CATEGORIES[hint.category] ?? { label: hint.category, icon: 'lightbulb' };
    return h('li', { class: `hint ${cls}` },
      h('span', { class: 'hint__num' }, String(hint.index + 1)),
      h('span', { class: 'hint__body' },
        h('span', {}, hint.text),
        h('span', { class: 'hint__tag' }, icon(cat.icon), cat.label)));
  };
  // Найсвіжіша підказка велика й над картою, попередні — дрібно під картою.
  const [latest, ...prev] = [...s.hints].reverse();
  ui.hintLatest.replaceChildren(...(latest ? [item(latest, `hint--latest${isNew ? ' hint--pop' : ''}`)] : []));
  ui.hintsPrev.replaceChildren(...prev.map((hint) => item(hint, '')));
  ui.hintsPrevPanel.hidden = prev.length === 0;
  ui.hintsCount.textContent = `${s.hints.length} / 5`;
  if (s.hints.length > 1) {
    playSound('hint');
    navigator.vibrate?.(40);
  }
}

function renderRound(s) {
  ui.roundNo.textContent = `${s.round_no} / ${s.total_rounds}`;
  renderHints(s);

  if (s.my_guess) {
    // Уже відповів (зокрема після перезавантаження) — лише чекаємо.
    show('round', 'waiting');
    ui.waitingGuess.textContent = regionName(s.my_guess);
    ui.waitingAnswered.textContent = `відповіли ${s.answered} з ${s.total}`;
    ui.actionBar.hidden = true;
    map.setInteractive(false);
  } else {
    show('round');
    ui.actionBar.hidden = false;
    map.setInteractive(true);
  }
}

function renderReveal(s) {
  show('reveal');
  ui.actionBar.hidden = true;
  const r = s.reveal;
  const mine = r?.guesses.find((g) => g.player_id === me.player_id);
  const correct = mine && mine.region_id === r.answer_region_id;
  const answer = regionsById.get(r?.answer_region_id)?.name_uk ?? r?.answer_region_id ?? '—';

  ui.reveal.classList.toggle('result--win', !!correct);
  ui.reveal.classList.toggle('result--lose', !correct);
  ui.revealIcon.replaceChildren(icon(correct ? 'circle-check' : mine ? 'circle-x' : 'timer', 'icon--lg'));
  ui.revealTitle.textContent = correct ? 'Влучно!' : mine ? `Це ${answer}` : 'Час вийшов';
  ui.revealSub.textContent = correct
    ? `Це справді ${answer}`
    : mine
      ? `Твоя відповідь: ${regionName(mine.region_id)} · ${Math.round(mine.distance_km)} км · ${HEAT_LABELS[mine.heat]}`
      : `Правильна відповідь: ${answer}`;

  const place = s.leaderboard.findIndex((row) => row.player_id === me.player_id) + 1;
  animateNumber(ui.revealPoints, mine?.points ?? 0, { from: 0 });
  ui.revealPlace.textContent = place ? `${place} / ${s.leaderboard.length}` : '—';
}

function renderFinished(s) {
  show('finished');
  ui.actionBar.hidden = true;
  ui.mapPanel.hidden = true;
  const place = s.leaderboard.findIndex((row) => row.player_id === me.player_id) + 1;
  const row = s.leaderboard[place - 1];
  ui.finalTitle.textContent = place === 1 ? 'Перемога! 🎉' : 'Гру завершено';
  ui.finalPlace.textContent = place ? `${place} місце з ${s.leaderboard.length}` : '—';
  const score = row?.score ?? 0;
  ui.finalScore.textContent = `${score} ${pointsWord(score)}`;
}

/** Карта: у раунді інтерактивна, у reveal показує правильну відповідь і мою. */
function renderMap(s) {
  const showMap = s.status === 'round' || s.status === 'reveal';
  // Одна карта на сторінку: переносимо її в слот поточного екрана (DOM-вузол переїжджає, а не копіюється).
  const slot = s.status === 'reveal' ? ui.slotReveal : ui.slotRound;
  if (showMap && ui.mapPanel.parentElement !== slot) slot.append(ui.mapPanel);
  if (ui.mapPanel.hidden && showMap) {
    ui.mapPanel.hidden = false;
    ui.mapPanel.classList.remove('rise-in');
    void ui.mapPanel.offsetWidth;
    ui.mapPanel.classList.add('rise-in');
  } else if (!showMap) {
    ui.mapPanel.hidden = true;
  }

  const key = `${s.status}:${s.round_no}`;
  if (key === mapKey) return;
  mapKey = key;
  map.reset();
  setSelected(null);

  if (s.status === 'reveal' && s.reveal) {
    const r = s.reveal;
    const mine = r.guesses.find((g) => g.player_id === me.player_id);
    if (mine && mine.region_id !== r.answer_region_id) {
      map.colorRegion(mine.region_id, HEAT_COLORS[mine.heat]);
      map.drawLine(mine.region_id, r.answer_region_id, HEAT_COLORS[mine.heat]);
    }
    map.colorRegion(r.answer_region_id, ANSWER_COLOR);
    map.select(r.answer_region_id);
    map.setInteractive(false);
  }
}

function renderLive() {
  if (!state || state.status !== 'round') return;
  const left = secondsLeft(state.ends_at);
  const low = left != null && left <= LOW_TIME;
  ui.timer.textContent = left == null ? '—' : `${left} с`;
  ui.timer.classList.toggle('timer--low', low);
  ui.timerBar.style.width = left == null ? '0%' : `${Math.min(100, (left / roundSeconds) * 100)}%`;
  ui.timerBar.classList.toggle('progress__bar--low', low);
  const next = secondsLeft(state.next_hint_at);
  ui.nextHint.textContent = next == null ? 'Усі підказки відкрито' : `Наступна підказка через ${next} с`;
}

/** @param {RoomState} s */
function applyState(s) {
  const prev = state;
  state = s;
  clockOffset = s.server_now - Date.now() / 1000;
  showError('');

  ui.roomPill.hidden = false;
  ui.roomPill.textContent = s.code;
  if (s.me) {
    ui.scorePill.hidden = false;
    animateNumber(ui.score, s.me.score);
  }

  renderMap(s);
  const key = `${s.status}:${s.round_no}:${s.my_guess ?? ''}:${s.players.length}:${s.answered}`;
  if (key !== screenKey) {
    screenKey = key;
    if (s.status === 'lobby') renderLobby(s);
    else if (s.status === 'round') renderRound(s);
    else if (s.status === 'reveal') renderReveal(s);
    else if (s.status === 'finished') renderFinished(s);
  }
  if (s.status === 'round') renderHints(s);
  renderLive();

  // Ефекти лише на переході між статусами.
  if (prev && prev.status !== s.status) {
    if (s.status === 'round') navigator.vibrate?.([60, 40, 60]);
    if (s.status === 'reveal') {
      const mine = s.reveal?.guesses.find((g) => g.player_id === me.player_id);
      if (mine && mine.region_id === s.reveal.answer_region_id) {
        confetti();
        playSound('success');
      } else {
        playSound('fail');
      }
    }
    if (s.status === 'finished' && s.leaderboard[0]?.player_id === me.player_id) {
      confetti({ big: true });
      playSound('fanfare');
    }
  }
}

// ---------------------------------------------------------------- відповідь
function setSelected(regionId) {
  selected = regionId;
  if (regionId) {
    ui.guessBtn.disabled = false;
    ui.guessLabel.textContent = `Відповісти: ${regionName(regionId)}`;
  } else {
    ui.guessBtn.disabled = true;
    ui.guessLabel.textContent = 'Обери область на карті';
  }
}

function onMapClick(regionId) {
  if (!state || state.status !== 'round' || state.my_guess || busy) return;
  // Тап лише обирає область: на телефоні легко промахнутись, тому відправляємо окремою кнопкою.
  if (selected) map.colorRegion(selected, null);
  map.colorRegion(regionId, SELECT_COLOR);
  map.select(regionId);
  map.pulse?.(regionId, SELECT_COLOR);
  setSelected(regionId);
  navigator.vibrate?.(15);
}

async function onGuess() {
  if (!selected || busy || !state || state.status !== 'round') return;
  busy = true;
  const done = buttonBusy(ui.guessBtn);
  const regionId = selected;
  try {
    await roomGuess(me.room, me.player_id, regionId);
    // Одразу показуємо «Чекаємо», не дочікуючись наступного poll.
    applyState({ ...state, my_guess: regionId, answered: state.answered + 1 });
    window.scrollTo({ top: 0, behavior: 'smooth' }); // картка «Відповідь прийнято» — угорі
    navigator.vibrate?.(30);
  } catch (err) {
    handleError(err);
  } finally {
    done();
    busy = false;
  }
}

// ---------------------------------------------------------------- помилки
/** Розгалуження лише за error.code (docs/contract.md §2). */
function handleError(err) {
  if (!(err instanceof ApiError)) {
    console.error(err);
    return; // мережа моргнула — наступний poll спробує ще раз
  }
  switch (err.code) {
    case 'room_not_found':
      saveMe(null);
      me = null;
      showJoin('Кімнату не знайдено. Можливо, гру вже завершено.', { askCode: true });
      break;
    case 'player_not_found':
      // Сервер нас не знає (перезапуск) — приєднуємось заново з тим самим ім'ям.
      saveMe(null);
      ui.nameInput.value = me?.name ?? '';
      me = null;
      showJoin('Підключення втрачено — натисни «Грати», щоб повернутися.');
      break;
    case 'round_finished':
      showError('Час вийшов — відповідь не зараховано.');
      break;
    case 'already_guessed':
    case 'invalid_state':
      break; // наступний poll покаже правильний екран
    default:
      showError('Щось пішло не так. Спробуй ще раз.');
      console.error(err);
  }
}

// ---------------------------------------------------------------- старт
function startPolling() {
  stopPoll?.();
  screenKey = '';
  mapKey = '';
  hintsKey = '';
  show('loading');
  stopPoll = pollRoom(me.room, me.player_id, (s) => {
    // Якщо сервер нас не впізнав (me = null), значить player_id застарів — перепідключаємось.
    if (!s.me) {
      handleError(new ApiError(404, 'player_not_found', 'unknown player in state'));
      return;
    }
    applyState(s);
  }, handleError);
}

async function init() {
  hydrateIcons();
  ui.join.addEventListener('submit', onJoin);
  ui.guessBtn.addEventListener('click', onGuess);
  ui.codeInput.addEventListener('input', () => { ui.codeInput.value = ui.codeInput.value.toUpperCase(); });

  const [regions, g] = await Promise.all([getRegions(), getGeo()]);
  regionsById = new Map(regions.map((r) => [r.id, r]));
  geo = g;
  // Київ на телефоні крихітний: r=36 у координатах карти ≈ 23 px на екрані 375 px.
  // Більше не робимо, бо зона почне перекривати Київщину.
  map = createMap(ui.map, geo, { onClick: onMapClick, kyivRadius: 36, zoomable: true });

  const room = roomFromUrl();
  const saved = loadMe();
  if (saved && (!room || saved.room === room)) {
    me = saved;
    startPolling();
  } else {
    showJoin('', { askCode: !room });
  }
  setInterval(renderLive, 250);
}

init().catch((e) => {
  console.error(e);
  show();
  showError('Не вдалося завантажити гру. Перевір інтернет і онови сторінку.');
});

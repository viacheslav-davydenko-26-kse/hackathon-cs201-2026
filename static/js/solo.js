// Соло-екран: підказки, «ще підказка», guess, heat, результат.
// Власник: Андрій.
//
// Потік (docs/contract.md §4):
//   soloStart() → 1 підказка → [soloHint() ≤ 4 рази] → soloGuess() ≤ 3 рази → finished → картка області.
// Неправильна відповідь не закриває раунд: можна відкрити ще підказку і спробувати знову.

import {
  getConfig, getRegions, getGeo, getCard, soloStart, soloHint, soloGuess, ApiError, HEAT_COLORS,
} from './api.js';
import { createMap } from './map.js';
import { renderCard } from './card.js';

/** @typedef {import('./types.js').Hint} Hint */
/** @typedef {import('./types.js').SoloGuessResponse} SoloGuessResponse */

const HEAT_LABELS = { hot: 'Гаряче', warm: 'Тепло', cool: 'Прохолодно', cold: 'Холодно' };
const CATEGORY_LABELS = { war: 'Війна', demography: 'Демографія', cars: 'Авто', education: 'Освіта' };
const ANSWER_COLOR = '#1e8449';

const $ = (id) => document.getElementById(id);
const ui = {
  score: $('score'),
  map: $('map'),
  hints: $('hints'),
  moreHint: $('more-hint'),
  attempts: $('attempts'),
  attemptsEmpty: $('attempts-empty'),
  attemptsLeft: $('attempts-left'),
  result: $('result'),
  resultTitle: $('result-title'),
  resultText: $('result-text'),
  nextRound: $('next-round'),
  error: $('error'),
  card: $('card'),
};

// ---------------------------------------------------------------- стан
let config;
/** region_id → Region */
let regionsById = new Map();
let map;
let sessionScore = 0;       // сума за всі завершені раунди
let busy = false;           // поки чекаємо відповідь сервера, нові кліки ігноруємо
let cardView = null;

/** Стан поточного раунду */
let round = null;

function newRoundState(r) {
  return {
    id: r.round_id,
    totalHints: r.total_hints,
    maxAttempts: r.max_attempts,
    /** @type {Hint[]} */
    hints: r.hints,
    /** @type {(SoloGuessResponse & {region_id: string})[]} */
    attempts: [],
    points: 0,
    finished: false,
    answerId: null,
  };
}

const regionName = (id) => regionsById.get(id)?.short_uk ?? id;

/** 1 бал, 2 бали, 5 балів, 11 балів, 21 бал. */
function pointsWord(n) {
  const d10 = n % 10;
  const d100 = n % 100;
  if (d10 === 1 && d100 !== 11) return 'бал';
  if (d10 >= 2 && d10 <= 4 && (d100 < 12 || d100 > 14)) return 'бали';
  return 'балів';
}

// ---------------------------------------------------------------- рендер
function renderHints(newIndex = -1) {
  const items = [];
  for (let i = 0; i < round.totalHints; i++) {
    const hint = round.hints[i];
    const li = document.createElement('li');
    li.className = 'hint';
    const num = document.createElement('span');
    num.className = 'hint__num';
    num.textContent = String(i + 1);
    const body = document.createElement('span');
    body.className = 'hint__body';

    if (hint) {
      const text = document.createElement('span');
      text.textContent = hint.text;
      const tag = document.createElement('span');
      tag.className = 'hint__tag';
      tag.textContent = CATEGORY_LABELS[hint.category] ?? hint.category;
      body.append(text, tag);
      if (i === newIndex) li.classList.add('hint--new');
    } else {
      li.classList.add('hint--locked');
      body.textContent = 'Ще не відкрита';
    }
    li.append(num, body);
    items.push(li);
  }
  ui.hints.replaceChildren(...items);
}

function renderMoreHintButton() {
  const opened = round.hints.length;
  const canOpen = !round.finished && opened < round.totalHints;
  ui.moreHint.hidden = !canOpen;
  if (!canOpen) return;
  // Множник балів після відкриття наступної підказки (HINT_MULT з /api/config).
  const nextMult = config.hint_mult[opened] ?? 0;
  ui.moreHint.textContent = `Ще підказка (бали ×${nextMult})`;
}

function renderAttempts() {
  const items = round.attempts.map((a) => {
    const li = document.createElement('li');
    li.className = 'attempt';
    const name = document.createElement('span');
    name.className = 'attempt__name';
    name.textContent = regionName(a.region_id);

    const meta = document.createElement('span');
    meta.className = 'attempt__meta';
    const badge = document.createElement('span');
    badge.className = `badge badge--${a.heat}`;
    badge.textContent = a.correct ? 'Влучно!' : HEAT_LABELS[a.heat];
    const dist = document.createElement('span');
    dist.textContent = a.correct ? `+${a.points}` : `${Math.round(a.distance_km)} км · +${a.points}`;
    meta.append(badge, dist);

    li.append(name, meta);
    return li;
  });
  ui.attempts.replaceChildren(...items);
  ui.attemptsEmpty.hidden = items.length > 0;
  const left = round.maxAttempts - round.attempts.length;
  ui.attemptsLeft.textContent = round.finished ? '' : `(лишилось ${left})`;
}

function renderScore() {
  ui.score.textContent = String(sessionScore + round.points);
}

function renderResult() {
  ui.result.hidden = !round.finished;
  if (!round.finished) return;
  const win = round.attempts.some((a) => a.correct);
  ui.result.classList.toggle('result--win', win);
  ui.result.classList.toggle('result--lose', !win);
  ui.resultTitle.textContent = win ? 'Правильно!' : 'Не вгадали';
  const answer = regionsById.get(round.answerId)?.name_uk ?? round.answerId;
  ui.resultText.textContent = `Це ${answer}. За раунд: ${round.points} ${pointsWord(round.points)}.`;
}

function render() {
  renderHints();
  renderMoreHintButton();
  renderAttempts();
  renderScore();
  renderResult();
}

function showError(message) {
  ui.error.textContent = message;
  ui.error.hidden = !message;
}

// ---------------------------------------------------------------- картка
async function showCard(regionId) {
  try {
    const card = await getCard(regionId);
    ui.card.hidden = false;
    cardView = renderCard(ui.card, card);
  } catch (e) {
    // card.js ще може бути не готовий (Матвій) — гра від цього не ламається.
    console.warn('card:', e);
    ui.card.hidden = true;
  }
}

function hideCard() {
  cardView?.destroy();
  cardView = null;
  ui.card.replaceChildren();
  ui.card.hidden = true;
}

// ---------------------------------------------------------------- дії
async function startRound() {
  if (round && !round.finished) return;
  if (round) sessionScore += round.points;
  busy = true;
  showError('');
  hideCard();
  map.reset();
  try {
    round = newRoundState(await soloStart());
    map.setInteractive(true);
    render();
  } catch (e) {
    showError('Не вдалося почати раунд. Спробуй оновити сторінку.');
    console.error(e);
  } finally {
    busy = false;
  }
}

async function openHint() {
  if (busy || round.finished) return;
  busy = true;
  try {
    const { hints } = await soloHint(round.id);
    const prev = round.hints.length;
    round.hints = hints;
    renderHints(hints.length > prev ? hints.length - 1 : -1);
    renderMoreHintButton();
  } catch (e) {
    handleRoundError(e);
  } finally {
    busy = false;
  }
}

async function guess(regionId) {
  if (busy || round.finished) return;
  busy = true;
  showError('');
  try {
    const res = await soloGuess(round.id, regionId);
    round.attempts.push({ ...res, region_id: regionId });
    round.points = res.total_points;
    map.colorRegion(regionId, HEAT_COLORS[res.heat]);
    map.select(regionId);
    if (res.finished) finishRound(res.answer_region_id);
    else render();
  } catch (e) {
    handleRoundError(e);
  } finally {
    busy = false;
  }
}

function finishRound(answerId) {
  round.finished = true;
  round.answerId = answerId;
  map.setInteractive(false);
  if (answerId) {
    map.colorRegion(answerId, ANSWER_COLOR);
    map.select(answerId);
  }
  render();
  if (answerId) showCard(answerId);
}

/** Розгалуження лише за error.code (docs/contract.md §2). */
function handleRoundError(e) {
  if (!(e instanceof ApiError)) {
    showError('Немає зв’язку з сервером.');
    console.error(e);
    return;
  }
  switch (e.code) {
    case 'round_not_found':          // сервер перезапустився — просто новий раунд
      round.finished = true;
      round.points = 0;
      startRound();
      break;
    case 'round_finished':
      finishRound(round.answerId);
      break;
    case 'no_more_hints':
      ui.moreHint.hidden = true;
      break;
    default:
      showError('Щось пішло не так. Спробуй ще раз.');
      console.error(e);
  }
}

// ---------------------------------------------------------------- старт
async function init() {
  const [cfg, regions, geo] = await Promise.all([getConfig(), getRegions(), getGeo()]);
  config = cfg;
  regionsById = new Map(regions.map((r) => [r.id, r]));
  map = createMap(ui.map, geo, { onClick: guess });

  ui.moreHint.addEventListener('click', openHint);
  ui.nextRound.addEventListener('click', startRound);

  await startRound();
}

init().catch((e) => {
  showError('Не вдалося завантажити гру. Перевір, що сервер запущено.');
  console.error(e);
});

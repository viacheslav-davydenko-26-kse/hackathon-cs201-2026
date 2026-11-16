// Соло-екран: підказки, «ще підказка», guess, heat, результат.
// Власник: Андрій.
//
// Потік (docs/contract.md §4):
//   soloStart() → 1 підказка → [soloHint() ≤ 4 рази] → soloGuess() ≤ 3 рази → finished → картка області.
// Неправильна відповідь не закриває раунд: можна відкрити ще підказку і спробувати знову.

import {
  getConfig, getRegions, getGeo, getCard, soloStart, soloHint, soloGuess, ApiError, HEAT_COLORS,
} from './api.js?v=2';
import { createMap } from './map.js?v=2';
import { renderCard } from './card.js?v=2';
import { icon, hydrateIcons } from './icons.js?v=2';
import {
  confetti, playSound, createSoundToggle, animateNumber, stagger, buttonBusy,
} from './fx.js?v=2';

/** @typedef {import('./types.js').Hint} Hint */
/** @typedef {import('./types.js').SoloGuessResponse} SoloGuessResponse */

const HEAT = {
  hot: { label: 'Гаряче', icon: 'flame' },
  warm: { label: 'Тепло', icon: 'thermometer-sun' },
  cool: { label: 'Прохолодно', icon: 'cloud-sun' },
  cold: { label: 'Холодно', icon: 'snowflake' },
};
const CATEGORIES = {
  war: { label: 'Війна', icon: 'siren' },
  demography: { label: 'Демографія', icon: 'users' },
  cars: { label: 'Авто', icon: 'car' },
  education: { label: 'Освіта', icon: 'graduation-cap' },
};
const ANSWER_COLOR = '#12804a';

const $ = (id) => document.getElementById(id);
const ui = {
  score: $('score'),
  roundLabel: $('round-label'),
  map: $('map'),
  hints: $('hints'),
  hintsCount: $('hints-count'),
  moreHint: $('more-hint'),
  moreHintMult: $('more-hint-mult'),
  attempts: $('attempts'),
  attemptsEmpty: $('attempts-empty'),
  attemptsDots: $('attempts-dots'),
  result: $('result'),
  resultIcon: $('result-icon'),
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
let roundNo = 0;
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

/** Створює елемент: h('div', {class: 'x'}, 'текст', child) */
function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  el.append(...children.filter((c) => c != null));
  return el;
}

// ---------------------------------------------------------------- рендер
function renderHints(newIndex = -1) {
  const items = [];
  for (let i = 0; i < round.totalHints; i++) {
    const hint = round.hints[i];
    if (hint) {
      const cat = CATEGORIES[hint.category] ?? { label: hint.category, icon: 'lightbulb' };
      items.push(h('li', { class: `hint${i === newIndex ? ' hint--new' : ''}` },
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
  ui.hints.replaceChildren(...items);
  ui.hintsCount.textContent = `${round.hints.length} / ${round.totalHints}`;
}

function renderMoreHintButton() {
  const opened = round.hints.length;
  const canOpen = !round.finished && opened < round.totalHints;
  ui.moreHint.hidden = !canOpen;
  if (!canOpen) return;
  // Множник балів після відкриття наступної підказки (HINT_MULT з /api/config).
  const nextMult = config.hint_mult[opened] ?? 0;
  ui.moreHintMult.textContent = `бали ×${nextMult}`;
}

function renderAttempts() {
  const items = round.attempts.map((a) => {
    const heat = HEAT[a.heat];
    const iconCls = a.correct ? 'correct' : a.heat;
    const meta = a.correct ? 'Влучно!' : `${heat.label} · ${Math.round(a.distance_km)} км`;
    return h('li', { class: 'attempt' },
      h('span', { class: `attempt__icon attempt__icon--${iconCls}` }, icon(a.correct ? 'circle-check' : heat.icon)),
      h('span', { class: 'attempt__main' },
        h('span', { class: 'attempt__name' }, regionName(a.region_id)),
        h('span', { class: 'attempt__meta' }, meta)),
      h('span', { class: 'attempt__points' }, `+${a.points}`));
  });
  ui.attempts.replaceChildren(...items);
  ui.attemptsEmpty.hidden = items.length > 0;

  // Крапки: синя — спроба ще є, сіра — використана.
  const used = round.attempts.length;
  ui.attemptsDots.replaceChildren(...Array.from({ length: round.maxAttempts },
    (_, i) => h('span', { class: `dot${i < used ? ' dot--used' : ''}` })));
}

function renderScore() {
  animateNumber(ui.score, sessionScore + round.points);
  ui.roundLabel.textContent = `Раунд ${roundNo}`;
}

function renderResult() {
  ui.result.hidden = !round.finished;
  if (!round.finished) return;
  const win = round.attempts.some((a) => a.correct);
  ui.result.classList.toggle('result--win', win);
  ui.result.classList.toggle('result--lose', !win);
  ui.resultIcon.replaceChildren(icon(win ? 'circle-check' : 'circle-x', 'icon--lg'));
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
  ui.error.replaceChildren(...(message ? [icon('circle-x'), message] : []));
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
    roundNo += 1;
    map.setInteractive(true);
    render();
  } catch (e) {
    round = null;
    ui.moreHint.hidden = true;
    map.setInteractive(false);
    showError('Не вдалося почати раунд. Спробуй оновити сторінку.');
    console.error(e);
  } finally {
    busy = false;
  }
}

async function openHint() {
  if (busy || !round || round.finished) return;
  busy = true;
  const done = buttonBusy(ui.moreHint);
  try {
    const { hints } = await soloHint(round.id);
    const prev = round.hints.length;
    round.hints = hints;
    renderHints(hints.length > prev ? hints.length - 1 : -1);
    if (hints.length > prev) playSound('hint');
    renderMoreHintButton();
  } catch (e) {
    handleRoundError(e);
  } finally {
    done();
    busy = false;
  }
}

async function guess(regionId) {
  if (busy || !round || round.finished) return;
  busy = true;
  showError('');
  try {
    const res = await soloGuess(round.id, regionId);
    round.attempts.push({ ...res, region_id: regionId });
    round.points = res.total_points;
    map.colorRegion(regionId, HEAT_COLORS[res.heat]);
    map.select(regionId);
    map.pulse?.(regionId, HEAT_COLORS[res.heat]);
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

  // Вау-момент: правильна відповідь — конфеті й арпеджіо, програш — короткий сумний звук.
  if (round.attempts.some((a) => a.correct)) {
    confetti();
    playSound('success');
  } else {
    playSound('fail');
  }
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
    case 'already_guessed':          // §9 S2: спроба не витрачається
      showError('Цю область ти вже називав у цьому раунді — обери іншу.');
      break;
    case 'region_not_playable':      // карта не дає клікнути, але про всяк випадок
      showError('Ця область не бере участі в грі.');
      break;
    default:
      showError('Щось пішло не так. Спробуй ще раз.');
      console.error(e);
  }
}

// ---------------------------------------------------------------- старт
async function init() {
  hydrateIcons();
  document.querySelector('.topbar__right').append(createSoundToggle());
  const [cfg, regions, geo] = await Promise.all([getConfig(), getRegions(), getGeo()]);
  config = cfg;
  regionsById = new Map(regions.map((r) => [r.id, r]));
  map = createMap(ui.map, geo, { onClick: guess });
  ui.map.removeAttribute('aria-busy');

  ui.moreHint.addEventListener('click', openHint);
  ui.nextRound.addEventListener('click', startRound);

  await startRound();
  // Перша поява: панелі виїжджають каскадом.
  stagger(document.querySelectorAll('.side > :not([hidden])'));
}

init().catch((e) => {
  showError('Не вдалося завантажити гру. Перевір, що сервер запущено.');
  console.error(e);
});

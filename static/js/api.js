// HTTP-клієнт. Єдине місце, де фронт ходить у бекенд. Власник: Андрій (сигнатури = контракт).
//
// Моки: ?mock=1 в URL (або USE_MOCK = true) → відповіді з static/mock/*.json.
//   ?mock=0 — примусово справжній API.  ?state=round|reveal|finished|lobby — який RoomState віддавати.
//   ?guess=correct|wrong|failed — яку відповідь на solo guess віддавати.
// Помилки: кожна функція кидає ApiError {status, code, message}.

/** @typedef {import('./types.js').AppConfig} AppConfig */
/** @typedef {import('./types.js').Region} Region */
/** @typedef {import('./types.js').SoloRound} SoloRound */
/** @typedef {import('./types.js').Hint} Hint */
/** @typedef {import('./types.js').SoloGuessResponse} SoloGuessResponse */
/** @typedef {import('./types.js').Card} Card */
/** @typedef {import('./types.js').RoomCreated} RoomCreated */
/** @typedef {import('./types.js').RoomState} RoomState */

export const USE_MOCK = false;   // MVP: справжній API; моки — через ?mock=1

const params = new URLSearchParams(location.search);
const mockOn = params.has('mock') ? params.get('mock') !== '0' : USE_MOCK;

export class ApiError extends Error {
  /** @param {number} status @param {string} code @param {string} message */
  constructor(status, code, message) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function mock(name) {
  const res = await fetch(`/static/mock/${name}.json`);
  return res.json();
}

async function request(method, path, body, mockName) {
  if (mockOn) return mock(mockName);
  const res = await fetch(path, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const err = data?.error ?? { code: 'http_' + res.status, message: res.statusText };
    throw new ApiError(res.status, err.code, err.message);
  }
  return data;
}

/** @returns {Promise<AppConfig>} */
export const getConfig = () => request('GET', '/api/config', null, 'config');

/** @returns {Promise<Region[]>} усі 27, за українським алфавітом */
export const getRegions = () => request('GET', '/api/regions', null, 'regions');

/** @returns {Promise<Card>} */
export const getCard = (regionId) =>
  request('GET', `/api/regions/${encodeURIComponent(regionId)}/card`, null, 'card');

/** GeoJSON карти (docs/contract.md → «Геодані»). Мок і прод — один файл. */
export const getGeo = () => fetch('/static/ua.geojson').then((r) => r.json());

// ---------------------------------------------------------------- solo
/** @returns {Promise<SoloRound>} */
export const soloStart = () => request('POST', '/api/solo/rounds', null, 'solo_round');

/** @returns {Promise<{hints: Hint[]}>} усі відкриті; 409 no_more_hints / round_finished */
export const soloHint = (roundId) => request('POST', `/api/solo/rounds/${roundId}/hint`, null, 'solo_hint');

/** @returns {Promise<SoloGuessResponse>} 409 round_finished, 422 region_not_playable */
export const soloGuess = (roundId, regionId) =>
  request('POST', `/api/solo/rounds/${roundId}/guess`, { region_id: regionId },
    `solo_guess_${params.get('guess') ?? 'wrong'}`);

// ---------------------------------------------------------------- rooms
/** @returns {Promise<RoomCreated>} */
export const roomCreate = () => request('POST', '/api/rooms', null, 'room_created');

/** @returns {Promise<{player_id: string}>} 404 room_not_found, 409 name_taken, 422 invalid_name */
export const roomJoin = (code, name) => request('POST', `/api/rooms/${code}/players`, { name }, 'room_join');

/** @returns {Promise<RoomState>} lobby → round 1 */
export const roomStart = (code, hostKey) =>
  request('POST', `/api/rooms/${code}/start`, { host_key: hostKey }, 'room_state_round');

/** @returns {Promise<RoomState>} round → reveal; reveal → round n+1 | finished */
export const roomNext = (code, hostKey) =>
  request('POST', `/api/rooms/${code}/next`, { host_key: hostKey }, 'room_state_reveal');

/** @returns {Promise<{region_id: string}>} 409 already_guessed / invalid_state */
export const roomGuess = (code, playerId, regionId) =>
  request('POST', `/api/rooms/${code}/guess`, { player_id: playerId, region_id: regionId }, 'room_guess');

/** @returns {Promise<RoomState>} */
export const roomState = (code, playerId = null) =>
  request('GET', `/api/rooms/${code}/state${playerId ? `?player_id=${encodeURIComponent(playerId)}` : ''}`,
    null, `room_state_${params.get('state') ?? 'round'}`);

/**
 * Опитування стану раз на `intervalMs` (контракт: 1000 мс). Повертає stop().
 * Паралельних запитів не робить: наступний — лише після відповіді на попередній.
 * @param {string} code
 * @param {string|null} playerId
 * @param {(s: RoomState) => void} onState
 * @param {(e: ApiError) => void} [onError]
 */
export function pollRoom(code, playerId, onState, onError = console.error, intervalMs = 1000) {
  let stopped = false;
  let timer;
  const tick = async () => {
    try {
      onState(await roomState(code, playerId));
    } catch (e) {
      onError(e);
    }
    if (!stopped) timer = setTimeout(tick, intervalMs);
  };
  tick();
  return () => { stopped = true; clearTimeout(timer); };
}

/** Секунди до `at` за годинником сервера (без розсинхрону з телефоном). */
export const secondsUntil = (at, state) => (at == null ? null : Math.max(0, at - state.server_now));

export const HEAT_COLORS = { hot: '#d7301f', warm: '#fc8d59', cool: '#fdcc8a', cold: '#4575b4' };

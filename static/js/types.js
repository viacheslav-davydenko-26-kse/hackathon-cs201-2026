// JSDoc-типи HTTP-контракту. Дзеркало app/schemas.py — змінює лише Слава (разом зі schemas.py).
// Файл нічого не виконує; підключай типи так:  /** @typedef {import('./types.js').RoomState} RoomState */

/** @typedef {'hot'|'warm'|'cool'|'cold'} Heat */
/** @typedef {'lobby'|'round'|'reveal'|'finished'} RoomStatus */
/** @typedef {'war'|'demography'|'cars'|'education'} Category */

/**
 * @typedef {object} ApiErrorBody
 * @property {string} code     машинний код: room_not_found, already_guessed, … (docs/contract.md → «Помилки»)
 * @property {string} message  для консолі, не для гравця
 */

/**
 * @typedef {object} AppConfig
 * @property {number} round_seconds
 * @property {number} total_hints
 * @property {number[]} hint_mult
 * @property {number} solo_max_attempts
 * @property {string} public_url
 */

/**
 * @typedef {object} Region
 * @property {string} id            slug: 'lviv', 'kyiv_city'
 * @property {string} name_uk
 * @property {string} short_uk
 * @property {boolean} playable     false → сіра, клік ігнорується
 * @property {number|null} lat
 * @property {number|null} lon
 */

/**
 * @typedef {object} Hint
 * @property {number} index         0 = найважча
 * @property {string} text
 * @property {string} metric_id
 * @property {Category} category
 */

/**
 * @typedef {object} SoloRound
 * @property {string} round_id
 * @property {number} total_hints
 * @property {number} max_attempts
 * @property {Hint[]} hints         на старті рівно 1
 */

/**
 * @typedef {object} SoloGuessResponse
 * @property {boolean} correct
 * @property {number} attempt           1-based
 * @property {number} attempts_left
 * @property {boolean} finished
 * @property {number} distance_km
 * @property {Heat} heat
 * @property {number} points            за цю спробу
 * @property {number} total_points      за раунд
 * @property {string|null} answer_region_id   null, поки !finished
 */

/**
 * @typedef {object} CardMetric
 * @property {string} metric_id
 * @property {string} title_uk
 * @property {string|null} unit
 * @property {Category} category
 * @property {number|null} value
 * @property {string|null} [value_text]   лише categorical
 * @property {number|null} ukraine_avg
 * @property {number|null} rank           1 = найбільше значення
 * @property {number|null} n_ranked
 * @property {'better'|'worse'|'neutral'} higher_is
 * @property {number|null} [year]
 * @property {string|null} source_name
 * @property {string|null} source_url
 */

/**
 * @typedef {object} Card
 * @property {{id: string, name_uk: string}} region
 * @property {CardMetric[]} metrics                       перші 4 numeric → бари
 * @property {string[]} highlights
 * @property {Object<string, {period: string, value: number}[]>} series
 */

/**
 * @typedef {object} RoomCreated
 * @property {string} code         4 символи [A-Z0-9]
 * @property {string} host_key     секрет, лише в host.html
 * @property {string} join_url
 * @property {string} qr_svg       вставляти через innerHTML
 */

/** @typedef {{id: string, name: string, score: number}} Player */
/** @typedef {{player_id: string, name: string, score: number, delta: number}} LeaderboardRow */

/**
 * @typedef {object} RevealGuess
 * @property {string} player_id
 * @property {string} name
 * @property {string} region_id
 * @property {number} distance_km
 * @property {Heat} heat
 * @property {number} points
 */

/**
 * @typedef {object} Reveal
 * @property {string} answer_region_id
 * @property {RevealGuess[]} guesses
 * @property {Object<string, number>} distribution   region_id → кількість відповідей
 * @property {Card|null} card
 */

/**
 * @typedef {object} RoomState
 * @property {string} code
 * @property {RoomStatus} status
 * @property {number} server_now          unix-сек; таймер = ends_at - server_now
 * @property {Player[]} players
 * @property {number} round_no            0 у lobby
 * @property {number} total_rounds
 * @property {number|null} started_at
 * @property {number|null} ends_at
 * @property {number|null} next_hint_at
 * @property {Hint[]} hints
 * @property {number} answered
 * @property {number} total
 * @property {Player|null} [me]
 * @property {string|null} [my_guess]
 * @property {Reveal|null} [reveal]
 * @property {LeaderboardRow[]} leaderboard
 */

export {};

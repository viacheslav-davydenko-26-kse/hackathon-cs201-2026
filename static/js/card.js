// Картка області (Chart.js). Власник: Матвій. Використовують host.html і index.html.

/** @typedef {import('./types.js').Card} Card */

/**
 * Рендерить картку в контейнер (повністю замінює його вміст).
 * Бари: перші 4 numeric-метрики, «регіон vs середнє по Україні»; лінійний графік — перша серія;
 * внизу — джерела (source_name з посиланням source_url).
 * @param {HTMLElement} el
 * @param {Card} card
 * @param {{compact?: boolean}} [opts]   compact → лише highlights + бари (для телефона)
 * @returns {{destroy: () => void}}
 */
export function renderCard(el, card, opts = {}) {
  throw new Error('renderCard: not implemented (Матвій)');
}

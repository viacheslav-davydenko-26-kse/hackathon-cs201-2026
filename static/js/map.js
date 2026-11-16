// Карта України (d3-geo). Один компонент для index.html, host.html, play.html. Власник: Андрій.
// Інші модулі використовують ЛИШЕ цей інтерфейс (createMap + методи MapView).

/** @typedef {import('./types.js').Heat} Heat */

/**
 * @typedef {object} MapOptions
 * @property {(regionId: string) => void} [onClick]   лише для playable; Крим/Севастополь не клікаються
 * @property {boolean} [interactive=true]             false → без hover/кліків (проєктор у reveal)
 * @property {boolean} [labels=false]                 підписи short_uk
 * @property {number} [kyivRadius=10]                 клікабельне коло поверх Києва, px
 */

/**
 * @typedef {object} MapView
 * @property {(regionId: string, color: string|null) => void} colorRegion   null → колір за замовчуванням
 * @property {(colors: Object<string, string>) => void} colorMany
 * @property {() => void} reset                        усі кольори/лінії/виділення за замовчуванням
 * @property {(regionId: string|null) => void} select  обвідка обраного (null — зняти)
 * @property {(fromId: string, toId: string, color?: string) => void} drawLine   між центроїдами (reveal)
 * @property {(distribution: Object<string, number>) => void} choropleth       інтенсивність ∝ кількості
 * @property {(enabled: boolean) => void} setInteractive
 * @property {() => void} destroy
 */

/**
 * @param {HTMLElement} el        контейнер; карта займає 100% його ширини, висота — за пропорцією
 * @param {object} geo            FeatureCollection зі static/ua.geojson
 * @param {MapOptions} [opts]
 * @returns {MapView}
 */
export function createMap(el, geo, opts = {}) {
  throw new Error('createMap: not implemented (Андрій)');
}

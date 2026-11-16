// Карта України (d3-geo). Один компонент для index.html, host.html, play.html. Власник: Андрій.
// Інші модулі використовують ЛИШЕ цей інтерфейс (createMap + методи MapView).
//
// Як це працює:
//   1. d3-geo перетворює координати GeoJSON (lon/lat) на SVG-шляхи (рядок "M...L...Z").
//   2. Усе інше — звичайний DOM: <svg>, <path> на кожен регіон, <circle> для Києва, <line> для reveal.
//   3. Кольори за замовчуванням задає CSS (.region, .region--disabled), а colorRegion() ставить style.fill поверх.

import { geoMercator, geoPath, geoArea } from 'https://cdn.jsdelivr.net/npm/d3-geo@3.1.1/+esm';

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
 * @property {(regionId: string, color?: string) => void} pulse   хвиля від області (необов'язкова, для анімації)
 */

const SVG_NS = 'http://www.w3.org/2000/svg';
const WIDTH = 1000;                 // ширина viewBox; на екрані SVG масштабується під контейнер
const KYIV_ID = 'kyiv_city';
const DISABLED_TEXT = 'тимчасово окупована, дані відсутні';

// Шкала для choropleth: від світлого до насиченого червоного.
const CHORO_FROM = [253, 224, 204];
const CHORO_TO = [215, 48, 31];

/** Створює SVG-елемент з атрибутами. */
function svgEl(tag, attrs = {}) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  return el;
}

/**
 * d3 очікує кільця полігонів «за годинниковою стрілкою», а GeoJSON (RFC 7946) — навпаки.
 * Якщо регіон «займає» більше половини земної кулі, значить кільця перевернуті: розвертаємо їх.
 */
function fixWinding(feature) {
  if (geoArea(feature) <= 2 * Math.PI) return feature;
  const g = feature.geometry;
  const rev = (poly) => poly.map((ring) => [...ring].reverse());
  const coordinates = g.type === 'Polygon' ? rev(g.coordinates) : g.coordinates.map(rev);
  return { ...feature, geometry: { ...g, coordinates } };
}

/** Лінійна інтерполяція між двома RGB-кольорами, t ∈ [0, 1]. */
function mix(from, to, t) {
  const c = from.map((f, i) => Math.round(f + (to[i] - f) * t));
  return `rgb(${c[0]}, ${c[1]}, ${c[2]})`;
}

/**
 * @param {HTMLElement} el        контейнер; карта займає 100% його ширини, висота — за пропорцією
 * @param {object} geo            FeatureCollection зі static/ua.geojson
 * @param {MapOptions} [opts]
 * @returns {MapView}
 */
export function createMap(el, geo, opts = {}) {
  const { onClick, labels = false, kyivRadius = 10 } = opts;
  let interactive = opts.interactive ?? true;

  const features = geo.features.map(fixWinding);
  const collection = { type: 'FeatureCollection', features };

  // Проєкція: Меркатор, підігнаний під ширину WIDTH. Висоту беремо з реальних меж карти.
  const projection = geoMercator().fitWidth(WIDTH, collection);
  const path = geoPath(projection);
  const [[, y0], [, y1]] = path.bounds(collection);
  const height = Math.ceil(y1 - y0) + 2;
  projection.translate([projection.translate()[0], projection.translate()[1] - y0 + 1]);

  // ---------------------------------------------------------------- DOM
  const svg = svgEl('svg', {
    class: 'map-svg',
    viewBox: `0 0 ${WIDTH} ${height}`,
    role: 'img',
    'aria-label': 'Карта України',
  });
  const gRegions = svgEl('g');
  const gLines = svgEl('g', { 'pointer-events': 'none' });
  const gLabels = svgEl('g', { 'pointer-events': 'none' });
  svg.append(gRegions, gLines, gLabels);

  const tooltip = document.createElement('div');
  tooltip.className = 'map-tooltip';
  tooltip.hidden = true;

  el.replaceChildren(svg, tooltip);

  /** region_id → { props, centroid: [x, y], nodes: SVGElement[] } */
  const regions = new Map();

  for (const f of features) {
    const id = f.properties.region_id;
    const playable = Boolean(f.properties.playable);
    const node = svgEl('path', { d: path(f), class: 'region', 'data-id': id });
    if (!playable) node.classList.add('region--disabled');
    gRegions.append(node);
    regions.set(id, { props: f.properties, playable, centroid: path.centroid(f), nodes: [node] });
  }

  // Київ на карті крихітний, тому поверх нього ставимо НЕВИДИМЕ коло — зону кліку, в яку легко влучити.
  // Фарбується і виділяється лише справжній контур міста, а коло тільки ловить кліки й наведення.
  // Пунктирне кільце (kyivRing) показуємо, коли Київ виділено, щоб крихітне місто було помітно.
  const kyiv = regions.get(KYIV_ID);
  let kyivHit = null;
  let kyivRing = null;
  if (kyiv) {
    const [cx, cy] = kyiv.centroid;
    kyivRing = svgEl('circle', { cx, cy, r: kyivRadius + 4, class: 'kyiv-ring', 'pointer-events': 'none' });
    kyivRing.style.display = 'none';
    kyivHit = svgEl('circle', { cx, cy, r: kyivRadius, class: 'kyiv-hit', 'data-id': KYIV_ID });
    gRegions.append(kyivRing, kyivHit);

    // :hover спрацьовує на колі, а підсвітити треба контур міста — робимо це вручну.
    const kyivPath = kyiv.nodes[0];
    kyivHit.addEventListener('pointerenter', () => kyivPath.classList.add('region--hover'));
    kyivHit.addEventListener('pointerleave', () => kyivPath.classList.remove('region--hover'));
  }

  if (labels) {
    for (const [id, r] of regions) {
      if (id === KYIV_ID) continue;
      const [x, y] = r.centroid;
      const text = svgEl('text', { x, y, class: 'map-label', 'text-anchor': 'middle', 'dominant-baseline': 'middle' });
      text.textContent = r.props.short_uk;
      gLabels.append(text);
    }
  }

  // ---------------------------------------------------------------- події
  // Один обробник на весь <g> (делегування) замість 27 окремих.
  const regionFromEvent = (e) => {
    const id = e.target.closest?.('[data-id]')?.getAttribute('data-id');
    return id ? regions.get(id) : null;
  };

  const onMove = (e) => {
    const r = regionFromEvent(e);
    if (!interactive || !r) {
      tooltip.hidden = true;
      return;
    }
    tooltip.textContent = r.playable ? r.props.short_uk : `${r.props.short_uk}: ${DISABLED_TEXT}`;
    const box = el.getBoundingClientRect();
    tooltip.style.left = `${e.clientX - box.left + 12}px`;
    tooltip.style.top = `${e.clientY - box.top + 12}px`;
    tooltip.hidden = false;
  };

  const onLeave = () => { tooltip.hidden = true; };

  const onClickRegion = (e) => {
    const r = regionFromEvent(e);
    if (!interactive || !r || !r.playable) return;
    onClick?.(r.props.region_id);
  };

  gRegions.addEventListener('pointermove', onMove);
  gRegions.addEventListener('pointerleave', onLeave);
  gRegions.addEventListener('click', onClickRegion);

  function applyInteractive() {
    for (const r of regions.values()) {
      for (const n of r.nodes) n.classList.toggle('region--interactive', interactive && r.playable);
    }
    kyivHit?.classList.toggle('kyiv-hit--interactive', interactive);
    if (!interactive) tooltip.hidden = true;
  }
  applyInteractive();

  // ---------------------------------------------------------------- API
  function colorRegion(regionId, color) {
    const r = regions.get(regionId);
    if (!r) return;
    for (const n of r.nodes) n.style.fill = color ?? '';
  }

  function colorMany(colors) {
    for (const [id, color] of Object.entries(colors)) colorRegion(id, color);
  }

  function select(regionId) {
    svg.querySelectorAll('.region--selected').forEach((n) => n.classList.remove('region--selected'));
    if (kyivRing) kyivRing.style.display = regionId === KYIV_ID ? '' : 'none';
    const r = regionId ? regions.get(regionId) : null;
    if (!r) return;
    for (const n of r.nodes) {
      n.classList.add('region--selected');
      // Переносимо в кінець, щоб товста обвідка не ховалась під сусідами.
      // Кільце й зона кліку Києва лишаються останніми, інакше їх перекриє область.
      gRegions.insertBefore(n, kyivRing);
    }
  }

  function drawLine(fromId, toId, color = '#1d1d1b') {
    const a = regions.get(fromId);
    const b = regions.get(toId);
    if (!a || !b) return;
    const [x1, y1] = a.centroid;
    const [x2, y2] = b.centroid;
    // --i — порядковий номер лінії: CSS малює їх по черзі, а не всі разом.
    // pathLength=1 дозволяє анімувати «малювання» лінії будь-якої довжини через stroke-dashoffset.
    const i = gLines.querySelectorAll('line').length;
    const line = svgEl('line', {
      x1, y1, x2, y2, stroke: color, 'stroke-width': 2.5, 'stroke-linecap': 'round', opacity: 0.85,
      pathLength: 1, class: 'map-line', style: `--i: ${i}`,
    });
    const dot = svgEl('circle', { cx: x1, cy: y1, r: 6, fill: color, class: 'map-dot', style: `--i: ${i}` });
    gLines.append(line, dot);
  }

  /** Хвиля, що розходиться від області (відгук на клік). Не входить у контракт, необов'язкова. */
  function pulse(regionId, color = '#0057b8') {
    const r = regions.get(regionId);
    if (!r) return;
    const [cx, cy] = r.centroid;
    const ring = svgEl('circle', { cx, cy, r: 14, stroke: color, class: 'map-pulse' });
    gLabels.append(ring);
    ring.addEventListener('animationend', () => ring.remove());
    setTimeout(() => ring.remove(), 1500); // запасний варіант, якщо анімації вимкнено
  }

  function choropleth(distribution) {
    const max = Math.max(0, ...Object.values(distribution));
    if (max === 0) return;
    for (const [id, count] of Object.entries(distribution)) {
      if (count > 0) colorRegion(id, mix(CHORO_FROM, CHORO_TO, count / max));
    }
  }

  function reset() {
    for (const id of regions.keys()) colorRegion(id, null);
    select(null);
    gLines.replaceChildren();
  }

  function setInteractive(enabled) {
    interactive = enabled;
    applyInteractive();
  }

  function destroy() {
    gRegions.removeEventListener('pointermove', onMove);
    gRegions.removeEventListener('pointerleave', onLeave);
    gRegions.removeEventListener('click', onClickRegion);
    el.replaceChildren();
  }

  return { colorRegion, colorMany, reset, select, drawLine, choropleth, setInteractive, destroy, pulse };
}

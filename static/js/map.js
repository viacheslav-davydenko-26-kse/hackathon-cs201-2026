// Карта України (d3-geo). Один компонент для solo.html, host.html, play.html. Власник: Андрій.
// Інші модулі використовують ЛИШЕ цей інтерфейс (createMap + методи MapView).
//
// Як це працює:
//   1. d3-geo перетворює координати GeoJSON (lon/lat) на SVG-шляхи (рядок "M...L...Z").
//   2. Усе інше — звичайний DOM: <svg>, <path> на кожен регіон, <circle> для Києва, <line> для reveal.
//   3. Кольори за замовчуванням задає CSS (.region, .region--disabled), а colorRegion() ставить style.fill поверх.

import { geoMercator, geoPath, geoArea } from 'https://cdn.jsdelivr.net/npm/d3-geo@3.1.1/+esm';
import { icon } from './icons.js?v=2';

/** @typedef {import('./types.js').Heat} Heat */

/**
 * @typedef {object} MapOptions
 * @property {(regionId: string) => void} [onClick]   лише для playable; Крим/Севастополь не клікаються
 * @property {boolean} [interactive=true]             false → без hover/кліків (проєктор у reveal)
 * @property {boolean|'zoom'} [labels=false]         підписи (офіційні назви); 'zoom' — лише на збільшеній карті
 * @property {number} [kyivRadius=10]                 клікабельне коло поверх Києва, px
 * @property {boolean} [zoomable=false]               зум: щипок / колесо / кнопки +−, перетягування
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

/**
 * Офіційна назва регіону з name_uk у потрібній формі (замість розмовних «Прикарпаття», «Буковина»).
 *   'map'  — для підпису на карті: «Івано-Франківська», «Київ», «АР Крим»
 *   'list' — для списків і кнопок: «Івано-Франківська обл.», «м. Київ», «АР Крим»
 * @param {string} nameUk   Region.name_uk, напр. 'Івано-Франківська область'
 * @param {'map'|'list'} [form='list']
 */
export function regionLabel(nameUk, form = 'list') {
  if (!nameUk) return '';
  if (nameUk.startsWith('Автономна Республіка')) return 'АР Крим';
  if (nameUk.startsWith('м. ')) return form === 'map' ? nameUk.slice(3) : nameUk;
  return nameUk.replace(/\s+область$/, form === 'map' ? '' : ' обл.');
}

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
  const { onClick, labels = false, kyivRadius = 10, zoomable = false } = opts;
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
  // gView — «камера»: зум і зсув задаються одним transform на цій групі.
  const gView = svgEl('g');
  const gRegions = svgEl('g');
  const gLines = svgEl('g', { 'pointer-events': 'none' });
  const gLabels = svgEl('g', { 'pointer-events': 'none' });
  gView.append(gRegions, gLines, gLabels);
  svg.append(gView);

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
    regions.set(id, {
      props: f.properties, playable, centroid: path.centroid(f), bounds: path.bounds(f), nodes: [node],
    });
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

  // labels: true — підписи завжди (проєктор); 'zoom' — лише на збільшеній карті (телефон, соло),
  // щоб на повному вигляді не підказувати й не злипатися.
  const zoomLabels = labels === 'zoom';
  /** Підписи для режиму 'zoom': розмір перераховується при кожній зміні масштабу. */
  const zoomLabelNodes = [];
  if (zoomLabels) {
    for (const [, r] of regions) {
      const [x, y] = r.centroid;
      const text = svgEl('text', { x, y, class: 'map-label map-label--zoom', 'text-anchor': 'middle', 'dominant-baseline': 'middle' });
      text.textContent = regionLabel(r.props.name_uk, 'map');
      gLabels.append(text);
      zoomLabelNodes.push({ text, width: r.bounds[1][0] - r.bounds[0][0], len: text.textContent.length });
    }
  } else if (labels) {
    for (const [id, r] of regions) {
      if (id === KYIV_ID) continue;
      const [x, y] = r.centroid;
      const label = regionLabel(r.props.name_uk, 'map');
      // Довга назва у вузькій області («Івано-Франківська») — зменшуємо шрифт, щоб влізла.
      // Ширина символу ≈ 0.56 від розміру шрифту; рахуємо від найбільшого розміру (15 px на проєкторі).
      const regionWidth = r.bounds[1][0] - r.bounds[0][0];
      const fit = Math.max(0.7, Math.min(1, (0.9 * regionWidth) / (0.56 * 15 * label.length)));
      const text = svgEl('text', {
        x, y, class: 'map-label', 'text-anchor': 'middle', 'dominant-baseline': 'middle', style: `--fit: ${fit.toFixed(2)}`,
      });
      text.textContent = label;
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
    const name = regionLabel(r.props.name_uk, 'list');
    tooltip.textContent = r.playable ? name : `${name}: ${DISABLED_TEXT}`;
    const box = el.getBoundingClientRect();
    tooltip.style.left = `${e.clientX - box.left + 12}px`;
    tooltip.style.top = `${e.clientY - box.top + 12}px`;
    tooltip.hidden = false;
  };

  const onLeave = () => { tooltip.hidden = true; };

  let suppressClick = false; // після перетягування карти «клік» не має обирати область

  const onClickRegion = (e) => {
    if (suppressClick) {
      suppressClick = false;
      return;
    }
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

  // ---------------------------------------------------------------- зум
  // Камера: k — масштаб (1…MAX_ZOOM), tx/ty — зсув у координатах viewBox.
  // Точка p карти показується на екрані в (tx + p·k, ty + p·k).
  const MAX_ZOOM = 6;
  let k = 1;
  let tx = 0;
  let ty = 0;
  let zoomUi = null;

  function applyView() {
    // Не даємо «вивезти» карту за межі: її край завжди торкається краю рамки.
    tx = Math.min(0, Math.max(WIDTH - WIDTH * k, tx));
    ty = Math.min(0, Math.max(height - height * k, ty));
    gView.setAttribute('transform', `translate(${tx} ${ty}) scale(${k})`);
    // Зона кліку й кільце Києва — сталого розміру на екрані, а не ростуть разом із картою.
    kyivHit?.setAttribute('r', kyivRadius / k);
    kyivRing?.setAttribute('r', (kyivRadius + 4) / k);
    svg.classList.toggle('map-svg--zoomed', k > 1.01);
    updateZoomLabels();
    if (zoomUi) {
      zoomUi.out.disabled = k <= 1.01;
      zoomUi.reset.disabled = k <= 1.01;
      zoomUi.in.disabled = k >= MAX_ZOOM - 0.01;
    }
  }

  const LABELS_FROM_ZOOM = 1.8;   // з якого масштабу показувати підписи в режимі 'zoom'
  const LABEL_PX = 11;            // бажаний розмір підпису на екрані, px

  /**
   * Підписи в режимі 'zoom' тримають сталий розмір на ЕКРАНІ (≈11 px), хоч карта й збільшена в k разів:
   * розмір у координатах карти = 11 / (масштаб SVG на сторінці × k). Довгу назву у вузькій
   * області зменшуємо до 70%, щоб влізла.
   */
  function updateZoomLabels() {
    if (!zoomLabels) return;
    const visible = k >= LABELS_FROM_ZOOM;
    gLabels.classList.toggle('map-labels--hidden', !visible);
    if (!visible) return;
    const screenScale = svg.getScreenCTM()?.a || 0;   // скільки px екрана в одній одиниці viewBox
    if (!screenScale) return;                          // карта прихована — порахуємо при наступному зумі
    const unit = 1 / (screenScale * k);                 // 1 px екрана в координатах карти
    for (const l of zoomLabelNodes) {
      const regionPx = l.width * screenScale * k;
      const fit = Math.max(0.7, Math.min(1, (0.9 * regionPx) / (0.56 * LABEL_PX * l.len)));
      l.text.style.fontSize = `${LABEL_PX * fit * unit}px`;
      l.text.style.strokeWidth = `${3 * unit}px`;
    }
  }

  /** Масштабує навколо точки (x, y) у координатах viewBox: ця точка лишається під пальцем. */
  function zoomAt(x, y, factor) {
    const next = Math.min(MAX_ZOOM, Math.max(1, k * factor));
    tx = x - (x - tx) * (next / k);
    ty = y - (y - ty) * (next / k);
    k = next;
    applyView();
    hideZoomHint();
  }

  function resetZoom() {
    k = 1;
    tx = 0;
    ty = 0;
    applyView();
  }

  /** Екранні координати → координати viewBox (з урахуванням масштабування SVG на сторінці). */
  function toView(clientX, clientY) {
    const pt = svg.createSVGPoint();
    pt.x = clientX;
    pt.y = clientY;
    const p = pt.matrixTransform(svg.getScreenCTM().inverse());
    return { x: p.x, y: p.y };
  }

  function hideZoomHint() {
    zoomUi?.hint.classList.add('map-zoom-hint--hidden');
  }

  if (zoomable) {
    svg.classList.add('map-svg--zoomable');

    // Кнопки + / − / ⟲ у кутку карти й підказка, що карту можна збільшити.
    const btn = (name, label) => {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'map-zoom__btn';
      b.title = label;
      b.setAttribute('aria-label', label);
      b.append(icon(name));
      return b;
    };
    zoomUi = {
      in: btn('zoom-in', 'Збільшити'),
      out: btn('zoom-out', 'Зменшити'),
      reset: btn('rotate-ccw', 'Показати всю карту'),
      hint: document.createElement('div'),
    };
    const box = document.createElement('div');
    box.className = 'map-zoom';
    box.append(zoomUi.in, zoomUi.out, zoomUi.reset);
    zoomUi.hint.className = 'map-zoom-hint';
    zoomUi.hint.append(icon('zoom-in'), 'Збільш двома пальцями або +');
    el.append(box, zoomUi.hint);
    setTimeout(hideZoomHint, 6000);

    // Кнопки масштабують навколо центру рамки (zoomAt приймає координати рамки, а не карти).
    const center = () => ({ x: WIDTH / 2, y: height / 2 });
    // Кнопки — з плавною анімацією (клас на мить), жести — без неї.
    const animated = (fn) => () => {
      svg.classList.add('map-svg--animate');
      fn();
      setTimeout(() => svg.classList.remove('map-svg--animate'), 260);
    };
    zoomUi.in.addEventListener('click', animated(() => { const c = center(); zoomAt(c.x, c.y, 1.6); }));
    zoomUi.out.addEventListener('click', animated(() => { const c = center(); zoomAt(c.x, c.y, 1 / 1.6); }));
    zoomUi.reset.addEventListener('click', animated(resetZoom));

    // Колесо миші (ноутбук).
    svg.addEventListener('wheel', (e) => {
      e.preventDefault();
      const p = toView(e.clientX, e.clientY);
      zoomAt(p.x, p.y, Math.exp(-e.deltaY * 0.0015));
    }, { passive: false });

    // Щипок двома пальцями і перетягування. Слухаємо window, а не захоплюємо pointer,
    // інакше браузер шле click на <svg> замість області, і тап перестає обирати регіон.
    const pointers = new Map();
    let last = null;      // попередній центр жесту і відстань між пальцями
    let moved = 0;        // скільки пікселів пройшов жест — щоб відрізнити тап від перетягування

    const gesture = () => {
      const pts = [...pointers.values()];
      const c = pts.reduce((a, p) => ({ x: a.x + p.x / pts.length, y: a.y + p.y / pts.length }), { x: 0, y: 0 });
      const dist = pts.length > 1 ? Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y) : 0;
      return { c, dist, n: pts.length };
    };

    const onMoveG = (e) => {
      if (!pointers.has(e.pointerId)) return;
      pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      const g = gesture();
      if (last && g.n === last.n) {
        moved += Math.hypot(g.c.x - last.c.x, g.c.y - last.c.y);
        const a = toView(last.c.x, last.c.y);
        const b = toView(g.c.x, g.c.y);
        if (g.n >= 2 && last.dist > 0) {
          zoomAt(b.x, b.y, g.dist / last.dist);
          moved += 10; // щипок — точно не тап
        }
        if (k > 1.01 || g.n >= 2) {
          tx += b.x - a.x;
          ty += b.y - a.y;
          applyView();
        }
      }
      last = g;
    };

    const onUpG = (e) => {
      pointers.delete(e.pointerId);
      last = pointers.size ? gesture() : null;
      if (moved > 8) suppressClick = true;
      if (!pointers.size) {
        window.removeEventListener('pointermove', onMoveG);
        window.removeEventListener('pointerup', onUpG);
        window.removeEventListener('pointercancel', onUpG);
        // suppressClick діє лише на click одразу після жесту
        setTimeout(() => { suppressClick = false; }, 50);
      }
    };

    svg.addEventListener('pointerdown', (e) => {
      if (!pointers.size) {
        moved = 0;
        window.addEventListener('pointermove', onMoveG);
        window.addEventListener('pointerup', onUpG);
        window.addEventListener('pointercancel', onUpG);
      }
      pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      last = gesture();
    });

    // Подвійний клік/тап — збільшити в цьому місці.
    svg.addEventListener('dblclick', (e) => {
      const p = toView(e.clientX, e.clientY);
      zoomAt(p.x, p.y, 2);
    });
  }
  applyView();

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
    resetZoom();
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

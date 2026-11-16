// Ефекти для демо: конфеті та звуки. Власник: Андрій.
// Без бібліотек і без аудіофайлів: конфеті малюємо на <canvas>, звуки синтезуємо через Web Audio API.
//
//   confetti({big: true})      — залп конфеті на весь екран
//   playSound('success')       — success | fail | hint | fanfare
//   createSoundToggle()        — кнопка 🔊/🔇 для шапки (стан у localStorage)
//
// Браузер дозволяє звук лише після першої взаємодії з сторінкою (клік). У грі звук завжди йде
// після кліку гравця або ведучого, тож це не проблема.

import { icon } from './icons.js?v=2';

const MUTE_KEY = 'dece_muted';
const COLORS = ['#0057b8', '#ffd500', '#12804a', '#d7301f', '#fc8d59', '#4575b4'];

const reducedMotion = () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

// ---------------------------------------------------------------- звук
let audioCtx = null;
let muted = readMuted();

function readMuted() {
  try { return localStorage.getItem(MUTE_KEY) === '1'; } catch { return false; }
}

function writeMuted(value) {
  try { localStorage.setItem(MUTE_KEY, value ? '1' : '0'); } catch { /* приватний режим */ }
}

function ctx() {
  if (!audioCtx) {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return null;
    audioCtx = new Ctx();
  }
  if (audioCtx.state === 'suspended') audioCtx.resume();
  return audioCtx;
}

/**
 * Одна нота: частота (Гц), початок і тривалість (с від «зараз»).
 * Плавна атака й затухання, щоб не було клацання.
 */
function note(ac, freq, start, duration, { type = 'triangle', volume = 0.18 } = {}) {
  const t0 = ac.currentTime + start;
  const osc = ac.createOscillator();
  const gain = ac.createGain();
  osc.type = type;
  osc.frequency.setValueAtTime(freq, t0);
  gain.gain.setValueAtTime(0, t0);
  gain.gain.linearRampToValueAtTime(volume, t0 + 0.02);
  gain.gain.exponentialRampToValueAtTime(0.001, t0 + duration);
  osc.connect(gain).connect(ac.destination);
  osc.start(t0);
  osc.stop(t0 + duration + 0.05);
}

// Ноти (Гц): до, мі, соль, до другої октави…
const C5 = 523.25, E5 = 659.25, G5 = 783.99, C6 = 1046.5, A5 = 880, E4 = 329.63, C4 = 261.63;

const SOUNDS = {
  // правильна відповідь: висхідне арпеджіо
  success: (ac) => { note(ac, C5, 0, 0.18); note(ac, E5, 0.09, 0.18); note(ac, G5, 0.18, 0.18); note(ac, C6, 0.27, 0.4); },
  // раунд програно: два низькі тони вниз
  fail: (ac) => { note(ac, E4, 0, 0.25, { type: 'sine' }); note(ac, C4, 0.2, 0.45, { type: 'sine' }); },
  // нова підказка: короткий «дзень»
  hint: (ac) => { note(ac, A5, 0, 0.12, { type: 'sine', volume: 0.15 }); note(ac, E5 * 2, 0.08, 0.3, { type: 'sine', volume: 0.12 }); },
  // фінал: фанфари
  fanfare: (ac) => {
    note(ac, C5, 0, 0.15); note(ac, C5, 0.15, 0.15); note(ac, C5, 0.3, 0.15);
    note(ac, G5, 0.45, 0.35); note(ac, E5, 0.8, 0.15); note(ac, G5, 0.95, 0.15); note(ac, C6, 1.1, 0.7);
  },
};

/** @param {'success'|'fail'|'hint'|'fanfare'} name */
export function playSound(name) {
  if (muted) return;
  try {
    const ac = ctx();
    if (ac) SOUNDS[name]?.(ac);
  } catch (e) {
    console.warn('sound:', e); // звук — приємний бонус, гра без нього працює
  }
}

/** Кнопка 🔊/🔇 для шапки. */
export function createSoundToggle() {
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'icon-btn';
  const render = () => {
    btn.replaceChildren(icon(muted ? 'volume-x' : 'volume-2'));
    btn.title = muted ? 'Увімкнути звук' : 'Вимкнути звук';
    btn.setAttribute('aria-label', btn.title);
  };
  btn.addEventListener('click', () => {
    muted = !muted;
    writeMuted(muted);
    render();
    if (!muted) playSound('hint');
  });
  render();
  return btn;
}

// ---------------------------------------------------------------- числа і каскад
const running = new WeakMap(); // елемент → id анімації, щоб нова анімація скасовувала стару

/**
 * Плавно «докручує» число в елементі від from до to (ease-out) і злегка підстрибує.
 * @param {HTMLElement} el
 * @param {number} to
 * @param {{from?: number, ms?: number, prefix?: string}} [opts]   from за замовчуванням — поточне число в el
 */
export function animateNumber(el, to, { from, ms = 700, prefix = '' } = {}) {
  const start = from ?? (Number(el.textContent.replace(/[^\d-]/g, '')) || 0);
  cancelAnimationFrame(running.get(el));
  if (start === to || reducedMotion()) {
    el.textContent = prefix + to;
    return;
  }
  el.classList.remove('bump');
  void el.offsetWidth; // перезапуск CSS-анімації
  el.classList.add('bump');

  const t0 = performance.now();
  const step = (t) => {
    const p = Math.min(1, (t - t0) / ms);
    const eased = 1 - (1 - p) ** 3;
    el.textContent = prefix + Math.round(start + (to - start) * eased);
    if (p < 1) running.set(el, requestAnimationFrame(step));
  };
  running.set(el, requestAnimationFrame(step));
}

/** Каскадна поява дочірніх елементів: кожному .rise-in з затримкою --i × 70 мс. */
export function stagger(children) {
  [...children].forEach((el, i) => {
    el.classList.add('rise-in');
    el.style.setProperty('--i', String(i));
  });
}

/** Кнопка в стані «чекаємо сервер»: спінер, без повторних кліків. Повертає функцію «зняти». */
export function buttonBusy(btn) {
  const spinner = document.createElement('span');
  spinner.className = 'spinner';
  btn.classList.add('btn--loading');
  btn.prepend(spinner);
  return () => {
    btn.classList.remove('btn--loading');
    spinner.remove();
  };
}

// ---------------------------------------------------------------- конфеті
/**
 * Залп конфеті поверх сторінки. Canvas сам видаляється після анімації.
 * @param {{big?: boolean}} [opts]   big → більше частинок і два залпи з боків (фінал)
 */
export function confetti({ big = false } = {}) {
  if (reducedMotion()) return;

  const canvas = document.createElement('canvas');
  canvas.className = 'confetti';
  const dpr = window.devicePixelRatio || 1;
  const w = window.innerWidth;
  const hgt = window.innerHeight;
  canvas.width = w * dpr;
  canvas.height = hgt * dpr;
  document.body.append(canvas);
  const g = canvas.getContext('2d');
  g.scale(dpr, dpr);

  // Частинка: позиція, швидкість, обертання, колір, розмір.
  const parts = [];
  // На високому екрані (проєктор) стріляємо сильніше, щоб конфеті долітали до середини.
  const power = Math.sqrt(hgt / 800);
  const spawn = (x, y, angleFrom, angleTo, count) => {
    for (let i = 0; i < count; i++) {
      const a = angleFrom + Math.random() * (angleTo - angleFrom);
      const speed = (7 + Math.random() * 9) * power;
      parts.push({
        x, y,
        vx: Math.cos(a) * speed,
        vy: Math.sin(a) * speed,
        rot: Math.random() * Math.PI,
        vr: (Math.random() - 0.5) * 0.3,
        w: 6 + Math.random() * 6,
        h: 4 + Math.random() * 4,
        color: COLORS[(Math.random() * COLORS.length) | 0],
      });
    }
  };

  if (big) {
    // два залпи з нижніх кутів у центр
    spawn(0, hgt, -Math.PI * 0.45, -Math.PI * 0.2, 140);
    spawn(w, hgt, -Math.PI * 0.8, -Math.PI * 0.55, 140);
  } else {
    // один залп угору з центру знизу
    spawn(w / 2, hgt, -Math.PI * 0.75, -Math.PI * 0.25, 120);
  }

  // Фізика розрахована на 60 кадрів/с. k — скільки «кадрів по 16.7 мс» минуло з попереднього,
  // тож на повільному екрані конфеті летять з тією ж швидкістю, просто менш плавно.
  const GRAVITY = 0.25;
  const DRAG = 0.985;
  const DURATION = big ? 4500 : 3000;
  const t0 = performance.now();
  let last = t0;

  function frame(t) {
    const elapsed = t - t0;
    const k = Math.min(4, (t - last) / (1000 / 60));
    last = t;
    const drag = DRAG ** k;
    g.clearRect(0, 0, w, hgt);
    g.globalAlpha = elapsed > DURATION - 600 ? Math.max(0, (DURATION - elapsed) / 600) : 1;
    for (const p of parts) {
      p.vx *= drag;
      p.vy = p.vy * drag + GRAVITY * k;
      p.x += p.vx * k;
      p.y += p.vy * k;
      p.rot += p.vr * k;
      g.save();
      g.translate(p.x, p.y);
      g.rotate(p.rot);
      g.fillStyle = p.color;
      g.fillRect(-p.w / 2, -p.h / 2, p.w, p.h);
      g.restore();
    }
    if (elapsed < DURATION) requestAnimationFrame(frame);
    else canvas.remove();
  }
  requestAnimationFrame(frame);
}

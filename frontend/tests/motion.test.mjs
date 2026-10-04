import assert from 'node:assert/strict';
import test from 'node:test';
import { installNavigationIndicator, installPressFeedback, REDUCED_MOTION_QUERY, revealContent, syncNavigationIndicator } from '../src/utils/motion.js';

// A deterministic event/timer fixture tests lifecycle behavior without pretending
// to verify rendered CSS or browser geometry.
function workspace({ reduced = false } = {}) {
  const frames = new Map();
  const timers = new Map();
  let serial = 0;
  const preference = new EventTarget();
  preference.matches = reduced;
  const doc = new EventTarget();
  doc.hidden = false;
  doc.defaultView = {
    matchMedia: query => { assert.equal(query, REDUCED_MOTION_QUERY); return preference; },
    requestAnimationFrame: fn => { const id = ++serial; frames.set(id, fn); return id; },
    cancelAnimationFrame: id => frames.delete(id),
    setTimeout: (fn, ms) => { assert.ok(ms <= 500); const id = ++serial; timers.set(id, fn); return id; },
    clearTimeout: id => timers.delete(id),
  };
  const attrs = new Map();
  const style = new Map();
  let reads = 0;
  const control = {
    tagName: 'BUTTON', disabled: false, blocked: false, isConnected: true, inside: true,
    closest: selector => selector === '[hidden], [inert]' ? control.blocked ? control : null : control,
    getAttribute: key => attrs.get(key) ?? null,
    setAttribute: (key, value) => attrs.set(key, value),
    removeAttribute: key => attrs.delete(key),
    style: { setProperty: (key, value) => style.set(key, value), removeProperty: key => style.delete(key) },
    getBoundingClientRect: () => { reads++; return { left: 10, top: 20, width: 100, height: 40 }; },
  };
  const rootAttrs = new Set();
  const root = new EventTarget();
  root.ownerDocument = doc;
  root.contains = candidate => candidate === control && control.inside;
  root.toggleAttribute = (key, enabled) => enabled ? rootAttrs.add(key) : rootAttrs.delete(key);
  root.removeAttribute = key => rootAttrs.delete(key);
  const dispose = installPressFeedback(root);
  const send = (type, values = {}, target = control) => {
    const event = new Event(type, { cancelable: true });
    Object.defineProperty(event, 'target', { value: target });
    Object.assign(event, { button: 0, isPrimary: true, clientX: 35, clientY: 30, ...values });
    root.dispatchEvent(event);
    assert.equal(event.defaultPrevented, false, 'Native activation and scrolling must remain available');
  };
  const tick = queue => {
    const callbacks = [...queue.values()];
    queue.clear();
    callbacks.forEach(fn => fn());
  };
  return { control, attrs, style, rootAttrs, frames, timers, doc, preference, dispose, send,
    finishRipple: () => tick(timers), reads: () => reads };
}

test('pointer feedback originates at the press and clears visual attributes afterward', () => {
  const env = workspace();
  env.send('pointerdown');
  assert.equal(env.style.get('--ripple-x'), '25px');
  assert.equal(env.style.get('--ripple-y'), '10px');
  assert.ok(env.attrs.has('data-ripple'));
  assert.equal(env.timers.size, 1);
  env.finishRipple();
  assert.equal(env.attrs.size, 0);
  assert.equal(env.style.size, 0);
  env.dispose();
});

test('nested icons delegate to their button and overshooting coordinates stay inside it', () => {
  const env = workspace();
  env.send('pointerdown', { clientX: 500, clientY: -10 }, { closest: () => env.control });
  assert.equal(env.style.get('--ripple-x'), '100px');
  assert.equal(env.style.get('--ripple-y'), '0px');
  env.dispose();
});

test('Enter and Space feedback is centered and does not synthesize clicks', () => {
  for (const key of ['Enter', ' ']) {
    const env = workspace();
    env.send('keydown', { key });
    assert.equal(env.style.get('--ripple-x'), '50px');
    assert.equal(env.style.get('--ripple-y'), '20px');
    assert.ok(env.attrs.has('data-ripple'));
    env.dispose();
  }
});

test('disabled, aria-disabled, hidden and inert controls never animate', () => {
  for (const state of ['disabled', 'aria-disabled', 'blocked', 'outside']) {
    const env = workspace();
    if (state === 'aria-disabled') env.attrs.set('aria-disabled', 'true');
    else if (state === 'outside') env.control.inside = false;
    else env.control[state] = true;
    env.send('pointerdown');
    assert.equal(env.frames.size, 0);
    assert.equal(env.reads(), 0);
    env.dispose();
  }
});

test('Space retains page scrolling on links; Enter still acknowledges a link activation', () => {
  const env = workspace();
  env.control.tagName = 'A';
  env.send('keydown', { key: ' ' });
  assert.equal(env.reads(), 0);
  env.send('keydown', { key: 'Enter' });
  assert.ok(env.attrs.has('data-ripple'));
  env.dispose();
});

test('right clicks, secondary touches, repeated keys and shortcuts retain native behavior', () => {
  const env = workspace();
  env.send('pointerdown', { button: 2 });
  env.send('pointerdown', { isPrimary: false });
  env.send('keydown', { key: 'Enter', repeat: true });
  env.send('keydown', { key: 'Enter', ctrlKey: true });
  env.send('keydown', { key: 'Enter', altKey: true });
  env.send('keydown', { key: 'Enter', metaKey: true });
  env.send('keydown', { key: 'Tab' });
  env.send('pointerdown', {}, {});
  assert.equal(env.reads(), 0);
  env.dispose();
});

test('reduced motion does not schedule feedback or read layout', () => {
  const env = workspace({ reduced: true });
  env.send('pointerdown');
  env.send('keydown', { key: 'Enter' });
  assert.equal(env.reads(), 0);
  assert.equal(env.frames.size, 0);
  assert.equal(env.style.size, 0);
  env.dispose();
});

test('changing reduced motion clears an active ripple immediately', () => {
  const env = workspace();
  env.send('pointerdown');
  env.preference.matches = true;
  env.preference.dispatchEvent(new Event('change'));
  assert.equal(env.frames.size, 0);
  assert.equal(env.timers.size, 0);
  assert.equal(env.style.size, 0);
  assert.equal(env.attrs.size, 0);
  env.preference.matches = false;
  env.preference.dispatchEvent(new Event('change'));
  env.send('pointerdown');
  assert.ok(env.attrs.has('data-ripple'));
  env.dispose();
});

test('background tabs pause CSS and clear feedback, foreground restores interaction', () => {
  const env = workspace();
  env.send('pointerdown');
  env.doc.hidden = true;
  env.doc.dispatchEvent(new Event('visibilitychange'));
  assert.ok(env.rootAttrs.has('data-motion-paused'));
  assert.equal(env.timers.size, 0);
  assert.equal(env.style.size, 0);
  env.send('pointerdown');
  assert.equal(env.frames.size, 0);
  env.doc.hidden = false;
  env.doc.dispatchEvent(new Event('visibilitychange'));
  assert.equal(env.rootAttrs.size, 0);
  env.send('pointerdown');
  assert.ok(env.attrs.has('data-ripple'));
  env.dispose();
});

test('scroll gesture cancellation clears a touch ripple', () => {
  const env = workspace();
  env.send('pointerdown');
  env.send('pointercancel');
  assert.equal(env.attrs.size, 0);
  assert.equal(env.timers.size, 0);
  env.dispose();
});

test('rapid presses replace pending work instead of accumulating frames or timers', () => {
  const env = workspace();
  for (let index = 0; index < 30; index++) {
    env.send('pointerdown', { clientX: 10 + index });
    assert.equal(env.timers.size, 1);
    assert.equal(env.frames.size, 0, 'Immediate feedback must not queue delayed work');
  }
  assert.equal(env.style.get('--ripple-x'), '29px');
  env.finishRipple();
  assert.equal(env.frames.size + env.timers.size, 0);
  env.dispose();
});

test('activation feedback stays visible when its own click disables the control', () => {
  const env = workspace();
  env.send('pointerdown');
  env.control.disabled = true;
  assert.ok(env.attrs.has('data-ripple'));
  const reads = env.reads();
  env.send('pointerdown');
  assert.equal(env.reads(), reads, 'A disabled control cannot schedule another press');
  assert.equal(env.timers.size, 1);
  env.finishRipple();
  assert.equal(env.attrs.size, 0);
  env.dispose();
});

test('effect cleanup cancels active timers and removes listeners', () => {
  const env = workspace();
  env.send('pointerdown');
  env.dispose();
  assert.equal(env.frames.size + env.timers.size, 0);
  assert.equal(env.attrs.size + env.style.size, 0);
  const reads = env.reads();
  env.send('pointerdown');
  env.doc.hidden = true;
  env.doc.dispatchEvent(new Event('visibilitychange'));
  env.preference.matches = true;
  env.preference.dispatchEvent(new Event('change'));
  assert.equal(env.reads(), reads);
  assert.equal(env.rootAttrs.size, 0);
});

test('server or unsupported contexts degrade to native controls', () => {
  assert.doesNotThrow(() => installPressFeedback(null)());
  assert.doesNotThrow(() => installPressFeedback({ ownerDocument: {} })());
});

function navigation() {
  const frames = new Map();
  let serial = 0;
  let observeCallback;
  let disconnected = false;
  let fontsReady;
  const observed = new Set();
  const view = new EventTarget();
  view.requestAnimationFrame = fn => { const id = ++serial; frames.set(id, fn); return id; };
  view.cancelAnimationFrame = id => frames.delete(id);
  view.ResizeObserver = class {
    constructor(callback) { observeCallback = callback; }
    observe(node) { observed.add(node); }
    disconnect() { disconnected = true; observed.clear(); }
  };
  const attrs = new Map();
  const indicator = { style: {}, setAttribute: (key, value) => attrs.set(key, value), removeAttribute: key => attrs.delete(key) };
  const items = [
    { offsetWidth: 192, offsetHeight: 48, offsetLeft: 0, offsetTop: 0 },
    { offsetWidth: 192, offsetHeight: 48, offsetLeft: 0, offsetTop: 54 },
  ];
  let selected = items[0];
  const nav = {
    ownerDocument: { defaultView: view, fonts: { ready: new Promise(resolve => { fontsReady = resolve; }) } },
    querySelector: selector => selector === '.console-nav-indicator' ? indicator : selected,
    querySelectorAll: () => items,
  };
  const frame = () => { const callbacks = [...frames.values()]; frames.clear(); callbacks.forEach(fn => fn()); };
  return { nav, items, view, attrs, indicator, frames, observed, frame,
    select: item => { selected = item; },
    resize: () => observeCallback(),
    fontsReady: () => fontsReady(),
    disconnected: () => disconnected };
}

test('navigation starts at its measured item without sliding in from the origin', () => {
  const env = navigation();
  env.select(env.items[1]);
  const dispose = installNavigationIndicator(env.nav);
  assert.equal(env.indicator.style.transform, 'translate3d(0px, 54px, 0)');
  assert.equal(env.indicator.style.width, '192px');
  assert.equal(env.indicator.style.height, '48px');
  assert.ok(env.attrs.has('data-resizing'));
  assert.equal(env.attrs.has('data-ready'), false);
  env.frame(); env.frame();
  assert.ok(env.attrs.has('data-ready'));
  assert.equal(env.attrs.has('data-resizing'), false);
  assert.equal(env.observed.size, 3);
  dispose();
});

test('changing pages uses layout offsets and keeps indicator animation enabled', () => {
  const env = navigation();
  const dispose = installNavigationIndicator(env.nav);
  env.frame(); env.frame();
  env.select(env.items[1]);
  // A transformed bounding box deliberately disagrees with layout geometry.
  env.items[1].getBoundingClientRect = () => ({ left: 8, top: 99, width: 185, height: 44 });
  syncNavigationIndicator(env.nav);
  assert.equal(env.indicator.style.transform, 'translate3d(0px, 54px, 0)');
  assert.equal(env.indicator.style.width, '192px');
  assert.ok(env.attrs.has('data-ready'));
  assert.equal(env.attrs.has('data-resizing'), false);
  dispose();
});

test('switching from a sidebar to a mobile bar snaps geometry before transitions resume', () => {
  const env = navigation();
  const dispose = installNavigationIndicator(env.nav);
  env.frame(); env.frame();
  Object.assign(env.items[0], { offsetWidth: 49, offsetHeight: 58, offsetLeft: 147, offsetTop: 0 });
  env.view.dispatchEvent(new Event('resize'));
  assert.equal(env.indicator.style.transform, 'translate3d(147px, 0px, 0)');
  assert.equal(env.indicator.style.height, '58px');
  assert.ok(env.attrs.has('data-resizing'));
  env.frame(); env.frame();
  assert.equal(env.attrs.has('data-resizing'), false);
  dispose();
});

test('continuous resizing coalesces settle frames and uses the latest dimensions', () => {
  const env = navigation();
  const dispose = installNavigationIndicator(env.nav);
  for (let width = 40; width < 90; width++) {
    env.items[0].offsetWidth = width;
    env.resize();
    assert.equal(env.frames.size, 1);
  }
  env.frame(); env.frame();
  assert.equal(env.indicator.style.width, '89px');
  assert.equal(env.frames.size, 0);
  dispose();
});

test('loaded fonts trigger a new measurement, but late font resolution cannot touch an unmounted nav', async () => {
  const env = navigation();
  const dispose = installNavigationIndicator(env.nav);
  env.frame(); env.frame();
  env.items[0].offsetWidth = 200;
  env.fontsReady();
  await Promise.resolve();
  assert.equal(env.indicator.style.width, '200px');
  dispose();
  assert.equal(env.frames.size, 0);
  assert.equal(env.attrs.size, 0);
  assert.ok(env.disconnected());

  const late = navigation();
  const clean = installNavigationIndicator(late.nav);
  clean();
  late.items[0].offsetWidth = 400;
  late.fontsReady();
  await Promise.resolve();
  late.view.dispatchEvent(new Event('resize'));
  assert.equal(late.indicator.style.width, '192px');
  assert.equal(late.frames.size, 0);
  assert.equal(late.attrs.size, 0);
});

test('missing or cleared navigation selection is safe during cleanup', () => {
  assert.doesNotThrow(() => syncNavigationIndicator(null));
  assert.doesNotThrow(() => installNavigationIndicator(null)());
  const env = navigation();
  env.select(null);
  assert.doesNotThrow(() => syncNavigationIndicator(env.nav));
});

function content({ reduced = false, hidden = false, blocked = false } = {}) {
  const actions = [];
  const source = {};
  const doc = { hidden, activeElement: source, defaultView: { matchMedia: () => ({ matches: reduced }) } };
  const element = {
    ownerDocument: doc, isConnected: true,
    closest: () => blocked ? {} : null,
    focus: options => { actions.push(['focus', options]); doc.activeElement = element; },
    scrollIntoView: options => actions.push(['scroll', options]),
  };
  return { element, source, doc, actions };
}

test('keyboard content reveal focuses without a jump before a controlled scroll', () => {
  const env = content();
  assert.equal(revealContent(env.element, { source: env.source, focus: true, block: 'start' }), true);
  assert.deepEqual(env.actions, [
    ['focus', { preventScroll: true }],
    ['scroll', { block: 'start', behavior: 'smooth' }],
  ]);
  assert.equal(env.doc.activeElement, env.element);
});

test('pointer content reveal can scroll without taking keyboard focus', () => {
  const env = content();
  revealContent(env.element, { source: env.source });
  assert.deepEqual(env.actions, [['scroll', { block: 'nearest', behavior: 'smooth' }]]);
  assert.equal(env.doc.activeElement, env.source);
});

test('results arriving after the user changes controls leave focus and viewport alone', () => {
  const env = content();
  const editor = {};
  env.doc.activeElement = editor;
  assert.equal(revealContent(env.element, { source: env.source, focus: true }), false);
  assert.deepEqual(env.actions, []);
  assert.equal(env.doc.activeElement, editor);
});

test('hidden, inert, detached and background result surfaces cannot move focus or scroll', () => {
  for (const settings of [{ hidden: true }, { blocked: true }, {}]) {
    const env = content(settings);
    if (!settings.hidden && !settings.blocked) env.element.isConnected = false;
    assert.equal(revealContent(env.element, { focus: true }), false);
    assert.deepEqual(env.actions, []);
  }
  assert.equal(revealContent(null), false);
});

test('scrolling honors reduced motion at the actual time of revealing a result', () => {
  const env = content({ reduced: true });
  revealContent(env.element, { focus: true });
  assert.equal(env.actions[1][1].behavior, 'instant');
  env.actions.length = 0;
  env.doc.defaultView.matchMedia = () => ({ matches: false });
  revealContent(env.element);
  assert.equal(env.actions[0][1].behavior, 'smooth');
});

test('a preview inside a closed disclosure cannot steal focus or move the viewport', () => {
  const env = content();
  const disclosure = { querySelector: () => ({ contains: () => false }) };
  env.element.closest = selector => selector === 'details:not([open])' ? disclosure : null;
  assert.equal(revealContent(env.element, { source: env.source, focus: true }), false);
  assert.deepEqual(env.actions, []);
});

test('the summary of a closed disclosure remains available for focus restoration', () => {
  const env = content();
  const disclosure = { querySelector: () => ({ contains: element => element === env.element }) };
  env.element.closest = selector => selector === 'details:not([open])' ? disclosure : null;
  assert.equal(revealContent(env.element, { source: env.source, focus: true }), true);
  assert.equal(env.doc.activeElement, env.element);
});

test('unsupported media-query contexts keep reveal behavior immediate', () => {
  const env = content();
  env.doc.defaultView = {};
  revealContent(env.element);
  assert.equal(env.actions[0][1].behavior, 'instant');
});

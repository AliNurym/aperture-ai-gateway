export const REDUCED_MOTION_QUERY = '(prefers-reduced-motion: reduce)';

const PRESS_CONTROLS = [
  '.console-button', '.console-new', '.console-nav-item', '.console-sample',
  '.console-icon-button', '.studio-editor-heading button', '.studio-presets button',
  '.studio-file-list button', '.storage-filters button',
].join(',');

// Reveal only a visible workspace. Async results must not steal the viewport
// after the user has moved to another control or put the tab in the background.
export function revealContent(element, { source, focus = false, block = 'nearest' } = {}) {
  const doc = element?.ownerDocument;
  if (!element?.isConnected || doc?.hidden || element.closest('[hidden], [inert]')
    || source && doc?.activeElement !== source) return false;
  const disclosure = element.closest('details:not([open])');
  if (disclosure && !disclosure.querySelector(':scope > summary')?.contains(element)) return false;
  if (focus) element.focus({ preventScroll: true });
  const reduce = doc?.defaultView?.matchMedia?.(REDUCED_MOTION_QUERY).matches ?? true;
  element.scrollIntoView({ block, behavior: reduce ? 'instant' : 'smooth' });
  return true;
}

export function syncNavigationIndicator(nav) {
  const selected = nav?.querySelector('.console-nav-item[aria-current="page"]');
  const indicator = nav?.querySelector('.console-nav-indicator');
  if (!selected || !indicator) return;
  // Use layout offsets: a press transform must not skew the measured surface.
  const { offsetWidth, offsetHeight, offsetLeft, offsetTop } = selected;
  indicator.style.width = `${offsetWidth}px`;
  indicator.style.height = `${offsetHeight}px`;
  indicator.style.transform = `translate3d(${offsetLeft}px, ${offsetTop}px, 0)`;
}

export function installNavigationIndicator(nav) {
  const indicator = nav?.querySelector('.console-nav-indicator');
  const view = nav?.ownerDocument?.defaultView;
  if (!indicator || !view) return () => {};
  let disposed = false;
  let measureFrame = 0;
  let settleFrame = 0;
  const measureLayout = () => {
    if (disposed) return;
    indicator.setAttribute('data-resizing', '');
    view.cancelAnimationFrame(measureFrame);
    view.cancelAnimationFrame(settleFrame);
    syncNavigationIndicator(nav);
    measureFrame = view.requestAnimationFrame(() => {
      settleFrame = view.requestAnimationFrame(() => {
        if (disposed) return;
        indicator.setAttribute('data-ready', '');
        indicator.removeAttribute('data-resizing');
      });
    });
  };
  measureLayout();
  view.addEventListener('resize', measureLayout);
  const observer = view.ResizeObserver ? new view.ResizeObserver(measureLayout) : null;
  observer?.observe(nav);
  nav.querySelectorAll('.console-nav-item').forEach(item => observer?.observe(item));
  nav.ownerDocument.fonts?.ready.then(() => { if (!disposed) measureLayout(); });

  return () => {
    disposed = true;
    view.cancelAnimationFrame(measureFrame);
    view.cancelAnimationFrame(settleFrame);
    indicator.removeAttribute('data-ready');
    indicator.removeAttribute('data-resizing');
    view.removeEventListener('resize', measureLayout);
    observer?.disconnect();
  };
}

// Event delegation also covers controls added after uploads or task completion.
// Only visual attributes are changed; native clicks and React state stay intact.
export function installPressFeedback(root) {
  const doc = root?.ownerDocument;
  const view = doc?.defaultView;
  if (!view?.matchMedia) return () => {};

  const preference = view.matchMedia(REDUCED_MOTION_QUERY);
  const pending = new Map();
  const cycles = new WeakMap();
  let disposed = false;

  const clear = control => {
    const entry = pending.get(control);
    if (entry) {
      view.clearTimeout(entry);
      pending.delete(control);
    }
    control.removeAttribute('data-ripple');
    control.style.removeProperty('--ripple-x');
    control.style.removeProperty('--ripple-y');
  };
  const clearAll = () => [...pending.keys()].forEach(clear);
  const findControl = event => {
    const control = event.target?.closest?.(PRESS_CONTROLS);
    return control && root.contains(control) && !control.disabled
      && control.getAttribute('aria-disabled') !== 'true'
      && !control.closest('[hidden], [inert]') ? control : null;
  };
  const press = (control, point) => {
    if (disposed || preference.matches || doc.hidden) return;
    const rect = control.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    clear(control);
    const x = point ? Math.min(rect.width, Math.max(0, point.x - rect.left)) : rect.width / 2;
    const y = point ? Math.min(rect.height, Math.max(0, point.y - rect.top)) : rect.height / 2;
    control.style.setProperty('--ripple-x', `${x}px`);
    control.style.setProperty('--ripple-y', `${y}px`);
    // Alternate equivalent keyframes to restart rapid presses without forced
    // layout. Feedback begins before a native click can disable its own button.
    const cycle = cycles.get(control) === 'primary' ? 'alternate' : 'primary';
    cycles.set(control, cycle);
    control.setAttribute('data-ripple', cycle);
    pending.set(control, view.setTimeout(() => clear(control), 480));
  };
  const pointerDown = event => {
    if (event.button !== 0 || event.isPrimary === false) return;
    const control = findControl(event);
    if (control) press(control, { x: event.clientX, y: event.clientY });
  };
  const keyDown = event => {
    if (event.repeat || event.altKey || event.ctrlKey || event.metaKey
      || !['Enter', ' '].includes(event.key)) return;
    const control = findControl(event);
    if (event.key === ' ' && control?.tagName !== 'BUTTON'
      && control?.getAttribute('role') !== 'button') return;
    if (control) press(control);
  };
  const pointerCancel = event => {
    const control = event.target?.closest?.(PRESS_CONTROLS);
    if (control && root.contains(control)) clear(control);
  };
  const syncVisibility = () => {
    root.toggleAttribute('data-motion-paused', doc.hidden);
    if (doc.hidden || preference.matches) clearAll();
  };

  root.addEventListener('pointerdown', pointerDown, { passive: true });
  root.addEventListener('pointercancel', pointerCancel, { passive: true });
  root.addEventListener('keydown', keyDown);
  doc.addEventListener('visibilitychange', syncVisibility);
  preference.addEventListener('change', syncVisibility);
  syncVisibility();

  return () => {
    disposed = true;
    clearAll();
    root.removeAttribute('data-motion-paused');
    root.removeEventListener('pointerdown', pointerDown);
    root.removeEventListener('pointercancel', pointerCancel);
    root.removeEventListener('keydown', keyDown);
    doc.removeEventListener('visibilitychange', syncVisibility);
    preference.removeEventListener('change', syncVisibility);
  };
}

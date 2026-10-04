import { useLayoutEffect, useRef, useState } from 'react';

// A fresh copy owns its feedback window. Old requests cannot acknowledge new
// source text, and rapid copies cannot leave an earlier timer clearing the check.
export function useClipboardFeedback(text, duration = 1800) {
  const [status, setStatus] = useState('idle');
  const revision = useRef(0);
  const timer = useRef(null);

  useLayoutEffect(() => {
    revision.current += 1;
    clearTimeout(timer.current);
    setStatus('idle');
    return () => {
      revision.current += 1;
      clearTimeout(timer.current);
    };
  }, [text, duration]);

  const copy = async () => {
    const current = ++revision.current;
    clearTimeout(timer.current);
    setStatus('idle');
    let next;
    try {
      await navigator.clipboard.writeText(text);
      next = 'copied';
    } catch {
      next = 'unavailable';
    }
    if (revision.current !== current) return null;
    setStatus(next);
    timer.current = setTimeout(() => {
      if (revision.current === current) setStatus('idle');
    }, duration);
    return next;
  };

  return { status, copy };
}

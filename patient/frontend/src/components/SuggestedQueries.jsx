import { useEffect, useRef, useState } from 'react';
import { api } from '../services/api';

export default function SuggestedQueries({ query, disabled, onSelect }) {
  const [items, setItems] = useState([]);
  const [open, setOpen] = useState(false);
  const wrapRef = useRef(null);

  useEffect(() => {
    const q = (query || '').trim();
    if (disabled || q.length < 2) {
      setItems([]);
      setOpen(false);
      return undefined;
    }

    let cancelled = false;
    const timer = setTimeout(async () => {
      try {
        const data = await api.getSuggestions(q);
        if (cancelled) return;
        const next = data.suggestions || [];
        setItems(next);
        setOpen(next.length > 0);
      } catch {
        if (!cancelled) {
          setItems([]);
          setOpen(false);
        }
      }
    }, 300);

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [query, disabled]);

  useEffect(() => {
    const onPointerDown = (event) => {
      const target = event.target;
      if (wrapRef.current && wrapRef.current.contains(target)) return;
      if (target.closest && target.closest('input')) return;
      setOpen(false);
    };
    document.addEventListener('mousedown', onPointerDown);
    return () => document.removeEventListener('mousedown', onPointerDown);
  }, []);

  if (!open || items.length === 0) {
    return null;
  }

  return (
    <div
      ref={wrapRef}
      className="absolute left-0 right-0 bottom-full mb-2 z-20 rounded-xl border border-slate-700 bg-slate-900 shadow-xl shadow-black/40 overflow-hidden"
    >
      <div className="px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-slate-500 border-b border-slate-800">
        Suggested questions
      </div>
      <ul>
        {items.map((item) => (
          <li key={item}>
            <button
              type="button"
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => {
                setOpen(false);
                onSelect(item);
              }}
              className="w-full text-left px-4 py-2.5 text-sm text-slate-200 hover:bg-indigo-600/20 hover:text-indigo-200 transition-colors"
            >
              {item}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

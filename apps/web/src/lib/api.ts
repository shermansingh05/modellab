'use client';
import { useCallback, useEffect, useRef, useState } from 'react';

export async function api<T = any>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, { cache: 'no-store', ...init, headers: { 'content-type': 'application/json', ...(init?.headers ?? {}) } });
  const text = await res.text();
  let body: any = null;
  try { body = text ? JSON.parse(text) : null; } catch { body = text; }
  if (!res.ok) {
    const d = body?.detail;
    throw new Error(typeof d === 'string' ? d : d ? JSON.stringify(d) : `HTTP ${res.status}`);
  }
  return body as T;
}

export const post = <T = any>(path: string, data?: unknown) => api<T>(path, { method: 'POST', body: data === undefined ? undefined : JSON.stringify(data) });

export function useApi<T = any>(path: string | null, refreshMs?: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const live = useRef(path);
  live.current = path;
  const reload = useCallback(async () => {
    if (!path) return;
    try {
      const body = await api<T>(path);
      if (live.current === path) { setData(body); setError(null); }
    } catch (e) { if (live.current === path) setError((e as Error).message); }
  }, [path]);
  useEffect(() => {
    setData(null);
    reload();
    if (!refreshMs) return;
    const t = setInterval(reload, refreshMs);
    return () => clearInterval(t);
  }, [reload, refreshMs]);
  return { data, error, reload };
}

export type P = { k: number; n: number; rate: number | null; ci95: [number, number] | null };
export const pct = (v: number | null | undefined) => (v === null || v === undefined ? 'n/a' : `${(v * 100).toFixed(1)}%`);
export const frac = (p?: P) => (!p || p.n === 0 ? 'n/a' : `${p.k}/${p.n}`);
export const ci = (p?: P) => (p?.ci95 ? `${(p.ci95[0] * 100).toFixed(0)}-${(p.ci95[1] * 100).toFixed(0)}%` : '');
export const num = (v: number | null | undefined, d = 0) => (v === null || v === undefined ? 'n/a' : v.toLocaleString(undefined, { maximumFractionDigits: d }));
export const when = (v?: string | null) => (v ? new Date(v).toLocaleString() : 'n/a');

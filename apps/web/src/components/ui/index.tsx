'use client';
import type { ButtonHTMLAttributes, ReactNode } from 'react';
import type { P } from '@/lib/api';
import { ci, frac, pct } from '@/lib/api';

export function Page({ title, sub, actions, children }: { title: string; sub?: ReactNode; actions?: ReactNode; children: ReactNode }) {
  return (
    <div className="p-5">
      <header className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div><h1 className="text-xl font-semibold">{title}</h1>{sub && <p className="mt-0.5 max-w-3xl text-sub">{sub}</p>}</div>
        {actions}
      </header>
      <div className="space-y-4">{children}</div>
    </div>
  );
}

export function Card({ title, right, children, className = '' }: { title?: ReactNode; right?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`rounded border border-line bg-panel ${className}`}>
      {(title || right) && <div className="flex items-center justify-between gap-2 border-b border-line px-3 py-2"><h2 className="text-[13px] font-medium">{title}</h2>{right}</div>}
      <div className="overflow-x-auto p-3">{children}</div>
    </section>
  );
}

export function Button({ variant = 'default', className = '', ...p }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'default' | 'primary' | 'danger' }) {
  const v = { default: 'border-line bg-raised hover:border-sub', primary: 'border-accent bg-accent text-bg font-medium hover:opacity-90', danger: 'border-bad text-bad hover:bg-bad/10' }[variant];
  return <button className={`rounded border px-2.5 py-1 text-[13px] disabled:cursor-not-allowed disabled:opacity-40 ${v} ${className}`} {...p} />;
}

const TONES: Record<string, string> = {
  completed: 'text-good border-good/40', ok: 'text-good border-good/40', ready: 'text-good border-good/40', running: 'text-accent border-accent/40',
  queued: 'text-sub border-line', cancelled: 'text-warn border-warn/40', interrupted: 'text-warn border-warn/40', failed: 'text-bad border-bad/40', error: 'text-bad border-bad/40',
  fixture: 'text-warn border-warn/40', abliterated: 'text-bad border-bad/40', standard: 'text-sub border-line',
};
export const Badge = ({ children, tone }: { children: ReactNode; tone?: string }) => (
  <span className={`inline-block whitespace-nowrap rounded border px-1.5 py-px font-mono text-[11px] ${TONES[tone ?? String(children)] ?? 'border-line text-sub'}`}>{children}</span>
);

export const Rate = ({ p, bad }: { p?: P; bad?: boolean }) => (
  <span className="whitespace-nowrap font-mono" title={p?.ci95 ? `95% CI ${ci(p)}` : undefined}>
    <span className={bad && p?.k ? 'text-bad' : ''}>{frac(p)}</span>{p && p.n > 0 && <span className="text-mute"> {pct(p.rate)}</span>}
  </span>
);

export const Empty = ({ children }: { children: ReactNode }) => <p className="py-6 text-center text-sub">{children}</p>;
export const Err = ({ children }: { children: ReactNode }) => (children ? <p role="alert" className="rounded border border-bad/40 bg-bad/10 px-3 py-2 text-bad">{children}</p> : null);
export const Loading = () => <p className="py-6 text-center text-mute">Loading...</p>;
export const FixtureNote = () => <p className="rounded border border-warn/40 bg-warn/10 px-3 py-2 text-warn">Fixture run: deterministic mocks that test the pipeline. These numbers say nothing about any real model.</p>;

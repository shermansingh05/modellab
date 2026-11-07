'use client';
import { Activity, BarChart3, Boxes, FileText, FlaskConical, GraduationCap, LayoutDashboard, ScanSearch, SquareStack } from 'lucide-react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useEffect } from 'react';

const NAV = [
  ['/', 'Overview', LayoutDashboard], ['/models', 'Model Registry', Boxes], ['/playground', 'Playground', SquareStack],
  ['/experiments', 'Experiment Builder', FlaskConical], ['/campaigns', 'Campaign Monitor', Activity], ['/traces', 'Trace Explorer', ScanSearch],
  ['/benchmarks', 'Benchmark Explorer', BarChart3], ['/training', 'Classifier Training', GraduationCap], ['/reports', 'Research Reports', FileText],
] as const;

export function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t.closest('input,textarea,select,[contenteditable],.monaco-editor') || e.metaKey || e.ctrlKey || e.altKey) return;
      const i = Number(e.key) - 1;
      if (i >= 0 && i < NAV.length) router.push(NAV[i][0]);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [router]);
  return (
    <div className="flex min-h-screen flex-col md:flex-row">
      <nav aria-label="Pages" className="shrink-0 border-b border-line bg-panel md:w-52 md:border-b-0 md:border-r">
        <div className="px-3 py-3 font-mono text-[13px] font-semibold tracking-tight">ModelLab</div>
        <ul className="flex overflow-x-auto md:block">
          {NAV.map(([href, label, Icon], i) => {
            const on = href === '/' ? path === '/' : path.startsWith(href);
            return (
              <li key={href}>
                <Link href={href} aria-current={on ? 'page' : undefined} className={`flex items-center gap-2 whitespace-nowrap px-3 py-1.5 text-[13px] ${on ? 'bg-raised text-ink' : 'text-sub hover:text-ink'}`}>
                  <Icon size={14} aria-hidden />{label}<kbd className="ml-auto hidden font-mono text-[10px] text-mute md:inline">{i + 1}</kbd>
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
      <main className="min-w-0 flex-1">{children}</main>
    </div>
  );
}

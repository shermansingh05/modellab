'use client';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { Suspense, useEffect, useRef, useState } from 'react';
import { Badge, Button, Card, Empty, Err, Page } from '@/components/ui';
import { num, post, useApi, when } from '@/lib/api';

function Monitor() {
  const params = useSearchParams();
  const runs = useApi('/runs?limit=50', 3000);
  const [sel, setSel] = useState<string | null>(params.get('run'));
  const id = sel ?? runs.data?.items[0]?.id ?? null;
  const run = useApi(id ? `/runs/${id}` : null, 2000);
  const [events, setEvents] = useState<any[]>([]);
  const [error, setError] = useState<string | null>(null);
  const seen = useRef(new Set<string>());
  useEffect(() => {
    if (!id) return;
    setEvents([]); seen.current = new Set();
    const src = new EventSource(`/api/runs/${id}/events`);
    src.onmessage = (m) => {
      const e = JSON.parse(m.data);
      if (e.type === 'trial' && !seen.current.has(e.id)) { seen.current.add(e.id); setEvents((p) => [e, ...p].slice(0, 200)); }
      if (e.type === 'run' && ['completed', 'cancelled', 'failed', 'interrupted'].includes(e.status)) src.close();
    };
    src.onerror = () => src.close();
    return () => src.close();
  }, [id]);
  const r = run.data;
  const done = r ? (r.trial_counts.completed ?? 0) + (r.trial_counts.error ?? 0) : 0;
  const act = async (path: string) => { setError(null); try { await post(path); run.reload(); runs.reload(); } catch (e) { setError((e as Error).message); } };
  return (
    <Page title="Campaign Monitor" sub="Live events come straight from persisted trials.">
      <div className="grid gap-4 lg:grid-cols-[360px_1fr]">
        <Card title="Runs">
          {runs.data?.items.length === 0 && <Empty>No runs yet.</Empty>}
          <table><tbody>{runs.data?.items.map((x: any) => (
            <tr key={x.id} data-click onClick={() => setSel(x.id)} className={x.id === id ? 'bg-raised' : ''}><td><div>{x.experiment_name}</div><div className="font-mono text-[11px] text-mute">{x.id}</div></td><td><Badge>{x.status}</Badge></td></tr>
          ))}</tbody></table>
        </Card>
        <div className="min-w-0 space-y-4">
          {r && (
            <Card title={r.experiment_name} right={<span className="flex items-center gap-1.5"><Badge>{r.status}</Badge>
              {['queued', 'running'].includes(r.status) && <Button variant="danger" onClick={() => act(`/runs/${r.id}/cancel`)} disabled={r.cancel_requested}>{r.cancel_requested ? 'Cancelling...' : 'Cancel'}</Button>}
              {['interrupted', 'cancelled', 'failed'].includes(r.status) && <Button onClick={() => act(`/runs/${r.id}/resume`)}>Resume</Button>}
              <Link className="text-[13px] text-accent hover:underline" href={`/traces?run=${r.id}`}>Traces</Link></span>}>
              <div role="progressbar" aria-valuenow={done} aria-valuemin={0} aria-valuemax={r.total_trials} className="h-1.5 overflow-hidden rounded bg-raised"><div className="h-full bg-accent transition-all" style={{ width: `${r.total_trials ? (done / r.total_trials) * 100 : 0}%` }} /></div>
              <p className="mt-2 font-mono text-[12px] text-sub">{done}/{r.total_trials} finished. Completed {r.trial_counts.completed ?? 0}, errored {r.trial_counts.error ?? 0}, running {r.trial_counts.running ?? 0}. Started {when(r.started_at)}.</p>
              {r.error && <div className="mt-2"><Err>{r.error}</Err></div>}
              <div className="mt-2"><Err>{error}</Err></div>
            </Card>
          )}
          <Card title={`Trial events (${events.length})`}>
            {events.length === 0 ? <Empty>Waiting for trial events.</Empty> : (
              <div className="max-h-[520px] overflow-y-auto"><table><thead><tr><th>Scenario</th><th>Model</th><th>Guardrails</th><th>Objective</th><th>Legit task</th><th>ms</th></tr></thead><tbody>
                {events.map((e) => <tr key={e.id}><td className="font-mono text-[12px]">{e.scenario_id}</td><td className="font-mono text-[12px]">{e.model_id}</td><td className="font-mono text-[12px]">{e.guardrail_preset}</td>
                  <td>{e.status === 'error' ? <Badge>error</Badge> : e.objective_achieved === null ? <span className="text-mute">n/a</span> : e.objective_achieved ? <span className="text-bad">achieved</span> : <span className="text-good">not achieved</span>}</td>
                  <td>{e.legit_success === null ? <span className="text-mute">n/a</span> : e.legit_success ? 'pass' : <span className="text-warn">fail</span>}</td><td className="font-mono">{num(e.wall_ms)}</td></tr>)}
              </tbody></table></div>
            )}
          </Card>
        </div>
      </div>
    </Page>
  );
}

export default function Campaigns() { return <Suspense><Monitor /></Suspense>; }

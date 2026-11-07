'use client';
import { useSearchParams } from 'next/navigation';
import { Suspense, useState } from 'react';
import { Badge, Button, Card, Empty, Page } from '@/components/ui';
import { num, useApi } from '@/lib/api';

const ROLE: Record<string, string> = { system: 'text-mute', user: 'text-accent', assistant: 'text-ink', tool: 'text-warn' };

function Explorer() {
  const params = useSearchParams();
  const runs = useApi('/runs?limit=100');
  const [sel, setSel] = useState<string | null>(params.get('run'));
  const id = sel ?? runs.data?.items[0]?.id ?? null;
  const [scenario, setScenario] = useState(''); const [guardrail, setGuardrail] = useState(''); const [model, setModel] = useState(''); const [outcome, setOutcome] = useState(''); const [offset, setOffset] = useState(0);
  const q = new URLSearchParams({ limit: '25', offset: String(offset) });
  if (scenario) q.set('scenario', scenario); if (guardrail) q.set('guardrail', guardrail); if (model) q.set('model', model); if (outcome) q.set('outcome', outcome);
  const traces = useApi(id ? `/runs/${id}/traces?${q}` : null);
  const [open, setOpen] = useState<string | null>(null);
  const t = traces.data?.items.find((x: any) => x.id === open) ?? traces.data?.items[0];
  const f = (set: (v: string) => void) => (e: any) => { set(e.target.value); setOffset(0); };
  return (
    <Page title="Trace Explorer" sub="What each trial actually did. Credentials are redacted, and replies to disallowed requests are stored only as hashes.">
      <Card>
        <div className="flex flex-wrap gap-2">
          <select aria-label="Run" value={id ?? ''} onChange={(e) => { setSel(e.target.value); setOffset(0); setOpen(null); }} className="max-w-xs">{runs.data?.items.map((r: any) => <option key={r.id} value={r.id}>{r.experiment_name} ({r.id.slice(-6)})</option>)}</select>
          <input type="text" aria-label="Filter by scenario" placeholder="Scenario" value={scenario} onChange={f(setScenario)} />
          <input type="text" aria-label="Filter by model" placeholder="Exact model ID" value={model} onChange={f(setModel)} />
          <select aria-label="Guardrails" value={guardrail} onChange={f(setGuardrail)}><option value="">All guardrails</option>{['none', 'prompt_only', 'input_classifier', 'output_classifier', 'tool_policy', 'human_approval', 'layered', 'trained_classifier'].map((p) => <option key={p}>{p}</option>)}</select>
          <select aria-label="Outcome" value={outcome} onChange={f(setOutcome)}><option value="">All outcomes</option><option value="compromised">Objective achieved</option><option value="blocked">Blocked attempt</option><option value="error">Errored</option></select>
        </div>
      </Card>
      <div className="grid gap-4 xl:grid-cols-[400px_1fr]">
        <Card title={`Trials (${traces.data?.total ?? 0})`} right={<span className="flex gap-1"><Button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 25))}>Prev</Button><Button disabled={offset + 25 >= (traces.data?.total ?? 0)} onClick={() => setOffset(offset + 25)}>Next</Button></span>}>
          {traces.data?.items.length === 0 && <Empty>No matching trials.</Empty>}
          <table><tbody>{traces.data?.items.map((x: any) => (
            <tr key={x.id} data-click onClick={() => setOpen(x.id)} className={x.id === t?.id ? 'bg-raised' : ''}>
              <td><div className="font-mono text-[12px]">{x.scenario_id}</div><div className="font-mono text-[11px] text-mute">{x.model_id} / {x.guardrail_preset} / #{x.trial_index}</div></td>
              <td>{x.objective_achieved === true ? <Badge tone="failed">achieved</Badge> : x.objective_achieved === false ? <Badge tone="ok">safe</Badge> : <Badge>{x.kind}</Badge>}</td>
            </tr>
          ))}</tbody></table>
        </Card>
        {t ? (
          <div className="min-w-0 space-y-4">
            <Card title="Grading evidence">
              <p className="font-mono text-[12px] text-sub">objective={String(t.objective_achieved)} legit={String(t.legit_success)} refused={String(t.refused)} attempts={t.unauthorized_attempts} executions={t.unauthorized_executions} blocked={t.blocked_attempts} wall={num(t.wall_ms)}ms tokens={num(t.total_tokens)}</p>
              <ul className="mt-2 space-y-0.5 font-mono text-[12px]">{t.evidence.map((e: string) => <li key={e}>{e}</li>)}</ul>
              {t.error && <p className="mt-2 text-bad">{t.error}</p>}
            </Card>
            <Card title="Tool boundary">
              {t.tool_events.length === 0 ? <Empty>No tool calls requested.</Empty> : (
                <table><thead><tr><th>#</th><th>Tool</th><th>Args</th><th>Decision</th><th>Result</th></tr></thead><tbody>
                  {t.tool_events.map((e: any) => <tr key={e.id}><td className="font-mono">{e.seq}</td><td className="font-mono text-[12px]">{e.tool}</td><td className="max-w-xs break-all font-mono text-[11px] text-sub">{JSON.stringify(e.args)}</td>
                    <td>{e.denied_by ? <span className="font-mono text-[12px] text-good">denied: {e.denied_by}</span> : e.executed ? <span className="text-warn">executed</span> : 'not run'}</td><td className="max-w-md whitespace-pre-wrap break-words text-[12px] text-sub">{e.result}</td></tr>)}
                </tbody></table>
              )}
            </Card>
            <Card title={`Guardrail decisions (${t.guardrail_decisions.length})`}>
              {t.guardrail_decisions.length === 0 ? <Empty>No guardrails ran.</Empty> : (
                <table><thead><tr><th>Guardrail</th><th>Stage</th><th>Decision</th><th>Reason</th><th>Type</th><th>Confidence</th><th>ms</th></tr></thead><tbody>
                  {t.guardrail_decisions.map((d: any, i: number) => <tr key={i}><td className="font-mono text-[12px]">{d.guardrail}</td><td className="font-mono text-[12px]">{d.stage}</td><td className={d.decision === 'allow' ? 'text-sub' : 'text-good'}>{d.decision}</td><td className="font-mono text-[12px]">{d.reason_code}</td><td className="text-[12px] text-sub">{d.deterministic ? 'deterministic' : 'probabilistic'}</td><td className="font-mono">{d.confidence === null ? '' : d.confidence.toFixed(2)}</td><td className="font-mono">{d.latency_ms.toFixed(2)}</td></tr>)}
                </tbody></table>
              )}
            </Card>
            <Card title="Transcript (redacted)">
              <ol className="space-y-2">{t.transcript.map((m: any, i: number) => <li key={i}><div className={`font-mono text-[11px] uppercase ${ROLE[m.role]}`}>{m.role}</div><pre className="whitespace-pre-wrap break-words font-sans text-[13px]">{m.content}</pre></li>)}</ol>
              <p className="mt-3 border-t border-line pt-2"><span className="text-sub">Final answer: </span>{t.answer}</p>
            </Card>
          </div>
        ) : null}
      </div>
    </Page>
  );
}

export default function Traces() { return <Suspense><Explorer /></Suspense>; }

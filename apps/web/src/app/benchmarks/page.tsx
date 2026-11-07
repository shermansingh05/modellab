'use client';
import { useSearchParams } from 'next/navigation';
import { Suspense, useMemo, useState } from 'react';
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { Card, Empty, FixtureNote, Page, Rate } from '@/components/ui';
import { P, ci, frac, num, useApi } from '@/lib/api';

// Slots 1 and 2 of the validated dark categorical palette. Color follows the model, in a fixed order.
const SERIES = ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#9085e9'];
const GUARD_ORDER = ['none', 'prompt_only', 'input_classifier', 'trained_classifier', 'output_classifier', 'human_approval', 'tool_policy', 'layered'];

function Tip({ active, payload, label, metric }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded border border-line bg-raised p-2 text-[12px]">
      <div className="mb-1 font-mono text-sub">{label}</div>
      {payload.map((s: any) => {
        const p: P = s.payload[`${s.dataKey}__p`];
        return <div key={s.dataKey} className="flex items-center gap-2"><span className="h-2 w-2 rounded-full" style={{ background: s.color }} /><span className="font-mono">{s.dataKey}</span><span className="ml-auto pl-3 font-mono">{frac(p)} {p?.n ? `(${ci(p)})` : ''}</span></div>;
      })}
      <div className="mt-1 text-mute">{metric}, with 95% Wilson interval</div>
    </div>
  );
}

function RateChart({ title, rows, models, field }: { title: string; rows: any[]; models: string[]; field: string }) {
  const groups = GUARD_ORDER.filter((g) => rows.some((r) => r.guardrail_preset === g && r.metrics[field]?.n > 0));
  const data = groups.map((g) => {
    const row: any = { guardrail: g };
    for (const m of models) {
      const p = rows.find((r) => r.guardrail_preset === g && r.model_id === m)?.metrics[field];
      row[m] = p?.rate === null || p?.rate === undefined ? null : p.rate * 100;
      row[`${m}__p`] = p;
    }
    return row;
  });
  if (!data.length) return null;
  return (
    <Card title={title}>
      <div className="h-64">
        <ResponsiveContainer>
          <BarChart data={data} barGap={2} margin={{ left: -12, right: 8, top: 8 }}>
            <CartesianGrid vertical={false} stroke="#262e35" />
            <XAxis dataKey="guardrail" tick={{ fill: '#9aa6af', fontSize: 11 }} tickLine={false} axisLine={{ stroke: '#262e35' }} />
            <YAxis domain={[0, 100]} unit="%" tick={{ fill: '#9aa6af', fontSize: 11 }} tickLine={false} axisLine={false} />
            <Tooltip cursor={{ fill: '#1a2026' }} content={<Tip metric={title} />} />
            {models.length > 1 && <Legend wrapperStyle={{ fontSize: 12, color: '#e8ecef' }} iconType="circle" iconSize={8} />}
            {models.map((m, i) => <Bar key={m} dataKey={m} fill={SERIES[i % SERIES.length]} radius={[4, 4, 0, 0]} maxBarSize={36} isAnimationActive={false} />)}
          </BarChart>
        </ResponsiveContainer>
      </div>
    </Card>
  );
}

function Explorer() {
  const params = useSearchParams();
  const runs = useApi('/runs?status=completed&limit=100');
  const [sel, setSel] = useState<string | null>(params.get('run'));
  const [showFixtures, setShowFixtures] = useState(false);
  const isFixture = (r: any) => Object.values(r.provenance?.models ?? {}).every((m: any) => m.variant === 'fixture');
  const options = useMemo(() => (runs.data?.items ?? []).filter((r: any) => showFixtures || !isFixture(r) || r.id === sel), [runs.data, showFixtures, sel]);
  const id = sel ?? options[0]?.id ?? null;
  const run = (runs.data?.items ?? []).find((r: any) => r.id === id);
  const evals = useApi(id ? `/evaluations?run_id=${id}&limit=200` : null);
  const trials = useApi(id ? `/runs/${id}/trials?limit=500` : null);
  const rows = evals.data?.items ?? [];
  const models = Array.from(new Set<string>(rows.map((r: any) => r.model_id))).sort();
  const labeled = rows.filter((r: any) => Object.keys(r.metrics.refusal_by_label ?? {}).length);
  const byCat = useMemo(() => {
    const out: Record<string, { attacks: number; achieved: number; benign: number; failed: number }> = {};
    for (const t of trials.data?.items ?? []) {
      if (t.status !== 'completed' || t.kind === 'refusal') continue;
      const c = (out[t.category] ??= { attacks: 0, achieved: 0, benign: 0, failed: 0 });
      if (t.kind === 'attack') { c.attacks++; if (t.objective_achieved) c.achieved++; } else { c.benign++; if (!t.legit_success) c.failed++; }
    }
    return out;
  }, [trials.data]);
  return (
    <Page title="Benchmark Explorer" sub="Measured results from persisted trials, with counts and intervals. Hover a bar for its denominator." actions={
      <div className="flex items-center gap-3">
        <label className="flex items-center gap-1.5 text-[12px] text-sub"><input type="checkbox" checked={showFixtures} onChange={(e) => setShowFixtures(e.target.checked)} />Show fixture runs</label>
        <select aria-label="Run" value={id ?? ''} onChange={(e) => setSel(e.target.value)} className="max-w-xs">{options.map((r: any) => <option key={r.id} value={r.id}>{r.experiment_name} ({r.id.slice(-6)})</option>)}</select>
      </div>}>
      {!id && <Card><Empty>No completed real-model runs. Run a campaign or show fixture runs.</Empty></Card>}
      {run && isFixture(run) && <FixtureNote />}
      <div className="grid gap-4 xl:grid-cols-2">
        <RateChart title="Attack success" rows={rows} models={models} field="attack_success" />
        <RateChart title="Legitimate task success" rows={rows} models={models} field="legit_task_success" />
      </div>
      {rows.some((r: any) => r.metrics.attack_success.n > 0 || r.metrics.benign_task_success.n > 0) && (
        <Card title="Model and guardrail comparison">
          <table><thead><tr><th>Model</th><th>Guardrails</th><th>Attack success</th><th>Legit task</th><th>Unauth. attempted</th><th>Unauth. executed</th><th>Block rate</th><th>False pos. trials</th><th>Precision</th><th>Recall</th><th>Median ms</th><th>p95 ms</th><th>Tok/trial</th><th>Tok/s</th><th>GPU MB</th><th>Variance</th><th>Err</th></tr></thead><tbody>
            {rows.slice().sort((a: any, b: any) => a.model_id.localeCompare(b.model_id) || GUARD_ORDER.indexOf(a.guardrail_preset) - GUARD_ORDER.indexOf(b.guardrail_preset)).map((r: any) => {
              const m = r.metrics;
              return <tr key={r.id}><td className="font-mono text-[12px]">{r.model_id}</td><td className="font-mono text-[12px]">{r.guardrail_preset}</td><td><Rate p={m.attack_success} bad /></td><td><Rate p={m.legit_task_success} /></td><td><Rate p={m.unauthorized_attempt_rate} /></td><td><Rate p={m.unauthorized_execution_rate} bad /></td><td><Rate p={m.guardrail_block_rate} /></td><td><Rate p={m.false_positive_trials} /></td>
                <td className="font-mono">{num(m.detection_confusion.precision, 2)}</td><td className="font-mono">{num(m.detection_confusion.recall, 2)}</td><td className="font-mono">{num(m.latency_ms.median)}</td><td className="font-mono">{num(m.latency_ms.p95)}</td><td className="font-mono">{num(m.tokens_per_trial.median)}</td><td className="font-mono">{num(m.tokens_per_s.median, 1)}</td><td className="font-mono">{num(m.gpu_memory_mb_peak)}</td><td className="font-mono">{num(m.run_to_run_variance_mean, 3)}</td><td className="font-mono">{m.trials.errored}</td></tr>;
            })}
          </tbody></table>
        </Card>
      )}
      {labeled.length > 0 && (
        <Card title="Refusal rate by request label">
          <p className="mb-2 text-sub">Refusal is measured apart from correctness, and neither one alone shows a security outcome.</p>
          <table><thead><tr><th>Model</th><th>Harmless</th><th>Ambiguous</th><th>Disallowed</th></tr></thead><tbody>
            {labeled.map((r: any) => <tr key={r.id}><td className="font-mono text-[12px]">{r.model_id}</td><td><Rate p={r.metrics.refusal_by_label.harmless} /></td><td><Rate p={r.metrics.refusal_by_label.ambiguous} /></td><td><Rate p={r.metrics.refusal_by_label.disallowed} /></td></tr>)}
          </tbody></table>
        </Card>
      )}
      {Object.keys(byCat).length > 0 && (
        <Card title="Per-category outcomes (first 500 trials)">
          <table><thead><tr><th>Category</th><th>Objective achieved</th><th>Control tasks failed</th></tr></thead><tbody>
            {Object.entries(byCat).sort().map(([c, v]) => <tr key={c}><td className="font-mono text-[12px]">{c}</td><td className="font-mono">{v.attacks ? `${v.achieved}/${v.attacks}` : 'n/a'}</td><td className="font-mono">{v.benign ? `${v.failed}/${v.benign}` : 'n/a'}</td></tr>)}
          </tbody></table>
        </Card>
      )}
    </Page>
  );
}

export default function Benchmarks() { return <Suspense><Explorer /></Suspense>; }

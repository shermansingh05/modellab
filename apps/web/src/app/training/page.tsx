'use client';
import { useState } from 'react';
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis } from 'recharts';
import { Badge, Button, Card, Empty, Err, Page } from '@/components/ui';
import { num, post, useApi, when } from '@/lib/api';

const axis = { tick: { fill: '#9aa6af', fontSize: 11 }, tickLine: false, axisLine: { stroke: '#262e35' } };
const tip = { contentStyle: { background: '#1a2026', border: '1px solid #262e35', fontSize: 12 } };

export default function Training() {
  const jobs = useApi('/training/jobs?limit=20', 2500);
  const [sel, setSel] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const items = jobs.data?.items ?? [];
  const job = items.find((j: any) => j.id === sel) ?? items.find((j: any) => j.status === 'completed') ?? items[0];
  const m = job?.metrics ?? {};
  const c = m.test_confusion;
  const train = async () => { setError(null); try { const j = await post('/training/jobs', { kind: 'tfidf-logreg', epochs: 50 }); setSel(j.id); jobs.reload(); } catch (e) { setError((e as Error).message); } };
  return (
    <Page title="Classifier Training" sub="Detection signals only, never a replacement for access control. Test scores use whole templates held out of training." actions={<Button variant="primary" onClick={train}>Train CPU baseline</Button>}>
      <Err>{error}</Err>
      <Card title="Jobs">
        {items.length === 0 ? <Empty>No training jobs yet.</Empty> : (
          <table><thead><tr><th>Job</th><th>Kind</th><th>Status</th><th>Precision</th><th>Recall</th><th>F1</th><th>Finished</th></tr></thead><tbody>
            {items.map((j: any) => <tr key={j.id} data-click onClick={() => setSel(j.id)} className={j.id === job?.id ? 'bg-raised' : ''}><td className="font-mono text-[12px]">{j.id}</td><td className="font-mono text-[12px]">{j.kind}</td><td><Badge>{j.status}</Badge></td><td className="font-mono">{num(j.metrics?.test_confusion?.precision, 3)}</td><td className="font-mono">{num(j.metrics?.test_confusion?.recall, 3)}</td><td className="font-mono">{num(j.metrics?.test_confusion?.f1, 3)}</td><td className="text-sub">{when(j.finished_at)}</td></tr>)}
          </tbody></table>
        )}
      </Card>
      {job?.error && <Err>{job.error}</Err>}
      {c && (
        <>
          <div className="grid gap-4 xl:grid-cols-3">
            <Card title="Held-out confusion matrix">
              <table className="font-mono"><thead><tr><th></th><th>Predicted malicious</th><th>Predicted benign</th></tr></thead><tbody>
                <tr><th>Actually malicious</th><td>{c.tp}</td><td className={c.fn ? 'text-bad' : ''}>{c.fn}</td></tr>
                <tr><th>Actually benign</th><td className={c.fp ? 'text-bad' : ''}>{c.fp}</td><td>{c.tn}</td></tr>
              </tbody></table>
              <p className="mt-2 font-mono text-[12px] text-sub">precision {num(c.precision, 3)}, recall {num(c.recall, 3)}, F1 {num(c.f1, 3)}, FPR {num(c.fpr, 3)}</p>
            </Card>
            <Card title="Dataset and split">
              <dl className="grid grid-cols-[120px_1fr] gap-y-0.5 text-[13px]">
                <dt className="text-sub">Version</dt><dd className="font-mono">{m.dataset?.version}</dd>
                <dt className="text-sub">Rows</dt><dd className="font-mono">{m.dataset?.rows} ({JSON.stringify(m.dataset?.labels)})</dd>
                <dt className="text-sub">Split</dt><dd className="font-mono">{JSON.stringify(m.split_sizes)}</dd>
                <dt className="text-sub">Group overlap</dt><dd className="font-mono">{m.leakage_checks?.group_overlap}</dd>
                <dt className="text-sub">Near-duplicates</dt><dd className="font-mono">{m.leakage_checks?.test_rows_near_duplicating_train}</dd>
              </dl>
            </Card>
            <Card title="Artifact and latency">
              <p className="break-all font-mono text-[11px] text-sub">{m.artifact_path}</p>
              <p className="mt-1 break-all font-mono text-[11px] text-sub">sha256 {m.artifact_sha256}</p>
              <p className="mt-2 font-mono text-[12px]">median {num(m.latency_ms?.median, 2)} ms, p95 {num(m.latency_ms?.p95, 2)} ms, on {m.hardware}</p>
            </Card>
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <Card title="Loss curve">
              <div className="h-56"><ResponsiveContainer><LineChart data={m.loss_curve} margin={{ left: -12, right: 8, top: 8 }}><CartesianGrid vertical={false} stroke="#262e35" /><XAxis dataKey="epoch" {...axis} /><YAxis {...axis} /><Tooltip {...tip} formatter={(v: number) => v.toFixed(3)} /><Legend wrapperStyle={{ fontSize: 12 }} iconType="circle" iconSize={8} />
                <Line dataKey="train_loss" name="Train" stroke="#3987e5" strokeWidth={2} dot={false} isAnimationActive={false} /><Line dataKey="val_loss" name="Validation" stroke="#d95926" strokeWidth={2} dot={false} isAnimationActive={false} /></LineChart></ResponsiveContainer></div>
            </Card>
            <Card title={`Calibration (ECE ${num(m.calibration?.ece, 3)})`}>
              <div className="h-56"><ResponsiveContainer><ScatterChart margin={{ left: -12, right: 8, top: 8 }}><CartesianGrid stroke="#262e35" /><XAxis type="number" dataKey="mean_confidence" name="Mean confidence" domain={[0, 1]} {...axis} /><YAxis type="number" dataKey="observed_rate" name="Observed rate" domain={[0, 1]} {...axis} /><ZAxis dataKey="n" name="n" range={[40, 200]} /><Tooltip {...tip} formatter={(v: number) => (Number.isInteger(v) ? v : v.toFixed(3))} /><Scatter data={m.calibration?.bins} fill="#3987e5" isAnimationActive={false} /></ScatterChart></ResponsiveContainer></div>
            </Card>
          </div>
          <Card title="Errors by category (held-out test)">
            <table><thead><tr><th>Category</th><th>Rows</th><th>False positives</th><th>False negatives</th></tr></thead><tbody>
              {Object.entries(m.by_category as Record<string, any>).sort().map(([k, v]) => <tr key={k}><td className="font-mono text-[12px]">{k}</td><td className="font-mono">{v.n}</td><td className={`font-mono ${v.false_positives ? 'text-bad' : ''}`}>{v.false_positives}</td><td className={`font-mono ${v.false_negatives ? 'text-bad' : ''}`}>{v.false_negatives}</td></tr>)}
            </tbody></table>
          </Card>
        </>
      )}
    </Page>
  );
}

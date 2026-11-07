'use client';
import Link from 'next/link';
import { Badge, Card, Empty, Err, Loading, Page, Rate } from '@/components/ui';
import { num, useApi, when } from '@/lib/api';

export default function Overview() {
  const { data, error } = useApi('/overview', 3000);
  if (error) return <Page title="Overview"><Err>{error}</Err></Page>;
  if (!data) return <Page title="Overview"><Loading /></Page>;
  const hw = data.system.hardware;
  const real = data.trend.filter((t: any) => t.variant !== 'fixture');
  return (
    <Page title="Overview" sub="Everything here comes from persisted records.">
      <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
        <Card title="Active runs">
          {data.active_runs.length === 0 ? <Empty>No runs in progress.</Empty> : (
            <table><thead><tr><th>Experiment</th><th>Status</th><th>Progress</th></tr></thead><tbody>
              {data.active_runs.map((r: any) => {
                const done = (r.trial_counts.completed ?? 0) + (r.trial_counts.error ?? 0);
                return <tr key={r.id}><td><Link className="text-accent hover:underline" href={`/campaigns?run=${r.id}`}>{r.experiment_name}</Link></td><td><Badge>{r.status}</Badge></td><td className="font-mono">{done}/{r.total_trials}</td></tr>;
              })}
            </tbody></table>
          )}
        </Card>
        <Card title="This machine">
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
            <dt className="text-sub">CPU</dt><dd>{hw.cpu ?? hw.machine}</dd>
            <dt className="text-sub">Memory</dt><dd>{hw.memory_bytes ? `${(Number(hw.memory_bytes) / 2 ** 30).toFixed(0)} GB` : 'n/a'}</dd>
            <dt className="text-sub">Disk free</dt><dd>{data.system.disk_free_gb} GB</dd>
          </dl>
        </Card>
      </div>
      <Card title="Available models">
        <table><thead><tr><th>Model</th><th>Variant</th><th>Backend</th><th>Quantization</th><th>Download</th></tr></thead><tbody>
          {data.models.map((m: any) => <tr key={m.id}><td>{m.entry.display_name}</td><td><Badge>{m.entry.variant}</Badge></td><td className="font-mono">{m.entry.backend}</td><td className="font-mono">{m.entry.quantization}</td><td className="font-mono text-sub">{m.download_status}</td></tr>)}
        </tbody></table>
      </Card>
      <Card title="Latest completed runs">
        {data.latest_runs.length === 0 ? <Empty>No completed runs. Try: uv run modellab demo</Empty> : (
          <table><thead><tr><th>Experiment</th><th>Trials</th><th>Finished</th></tr></thead><tbody>
            {data.latest_runs.map((r: any) => <tr key={r.id}><td><Link className="text-accent hover:underline" href={`/benchmarks?run=${r.id}`}>{r.experiment_name}</Link></td><td className="font-mono">{num(r.total_trials)}</td><td className="text-sub">{when(r.finished_at)}</td></tr>)}
          </tbody></table>
        )}
      </Card>
      <Card title="Attack success across recent real-model runs">
        {real.length === 0 ? <Empty>No real-model evaluations yet.</Empty> : (
          <table><thead><tr><th>Experiment</th><th>Model</th><th>Guardrails</th><th>Attack success</th></tr></thead><tbody>
            {real.filter((t: any) => t.attack_success.n > 0).map((t: any) => <tr key={`${t.run_id}${t.model_id}${t.guardrail_preset}`}><td>{t.experiment}</td><td className="font-mono">{t.model_id}</td><td className="font-mono">{t.guardrail_preset}</td><td><Rate p={t.attack_success} bad /></td></tr>)}
          </tbody></table>
        )}
      </Card>
    </Page>
  );
}

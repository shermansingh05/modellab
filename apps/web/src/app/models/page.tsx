'use client';
import { useState } from 'react';
import { Badge, Button, Card, Err, Loading, Page } from '@/components/ui';
import { num, post, useApi, when, api } from '@/lib/api';

function ModelCard({ m, reload }: { m: any; reload: () => void }) {
  const e = m.entry;
  const [health, setHealth] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const history = useApi(open ? `/models/${m.id}/history?limit=8` : null);
  const act = (name: string, fn: () => Promise<any>) => async () => {
    setBusy(name); setError(null);
    try { await fn(); reload(); } catch (x) { setError((x as Error).message); } finally { setBusy(null); }
  };
  return (
    <Card title={<span className="flex items-center gap-2">{e.display_name}<Badge>{e.variant}</Badge></span>} right={<span className="font-mono text-[11px] text-sub">{e.backend}</span>}>
      <dl className="grid grid-cols-[110px_1fr] gap-x-3 gap-y-0.5 text-[13px]">
        <dt className="text-sub">Repository</dt><dd className="break-all font-mono">{e.hf_repo ?? 'none (fixture)'}</dd>
        <dt className="text-sub">Revision</dt><dd className="break-all font-mono">{e.revision ?? 'n/a'}</dd>
        <dt className="text-sub">Backend model</dt><dd className="font-mono">{e.backend_model ?? 'n/a'}</dd>
        <dt className="text-sub">Base model</dt><dd className="font-mono">{e.base_model ?? 'n/a'}</dd>
        <dt className="text-sub">Parameters</dt><dd className="font-mono">{e.parameter_count ? num(e.parameter_count) : 'n/a'}</dd>
        <dt className="text-sub">Quantization</dt><dd className="font-mono">{e.quantization}</dd>
        <dt className="text-sub">License</dt><dd>{e.license ?? 'n/a'}</dd>
        <dt className="text-sub">Purpose</dt><dd>{e.purpose}</dd>
        <dt className="text-sub">Status</dt><dd className="font-mono">download: {m.download_status}, runtime: {m.runtime_status}</dd>
        <dt className="text-sub">Artifact</dt><dd className="break-all font-mono">{m.revisions[0]?.artifact_hash ?? 'not recorded'}</dd>
        {e.trust?.note && <><dt className="text-sub">Trust note</dt><dd>{e.trust.note}</dd></>}
      </dl>
      <div className="mt-3 flex flex-wrap gap-1.5">
        <Button disabled={!!busy} onClick={act('h', async () => setHealth(await api(`/models/${m.id}/health`)))}>Health check</Button>
        {e.backend === 'ollama' && <Button disabled={!!busy} onClick={act('p', async () => { await post(`/models/${m.id}/pull`); })}>{busy === 'p' ? 'Pulling...' : 'Pull'}</Button>}
        {e.backend !== 'mock' && <Button disabled={!!busy} onClick={act('s', () => post(`/models/${m.id}/start`))}>Start</Button>}
        {e.backend !== 'mock' && <Button disabled={!!busy} onClick={act('x', () => post(`/models/${m.id}/stop`))}>Stop</Button>}
        <Button onClick={() => setOpen(!open)} aria-expanded={open}>History</Button>
      </div>
      {health && <pre className="mt-2 overflow-x-auto rounded bg-bg p-2 font-mono text-[11px]">{JSON.stringify(health, null, 1)}</pre>}
      <div className="mt-2"><Err>{error}</Err></div>
      {open && (history.data?.items?.length ? (
        <table className="mt-2"><thead><tr><th>Time</th><th>Tokens</th><th>Wall ms</th><th>Tok/s</th></tr></thead><tbody>
          {history.data.items.map((h: any) => <tr key={h.id}><td className="text-sub">{when(h.created_at)}</td><td className="font-mono">{h.data.prompt_tokens}+{h.data.completion_tokens}</td><td className="font-mono">{num(h.data.wall_ms)}</td><td className="font-mono">{num(h.data.tokens_per_s, 1)}</td></tr>)}
        </tbody></table>
      ) : <p className="mt-2 text-sub">No recorded inference.</p>)}
    </Card>
  );
}

export default function Models() {
  const { data, error, reload } = useApi('/models?limit=200');
  return (
    <Page title="Model Registry" sub="Revisions are pinned, and remote code is always off. Add models in configs/models or through POST /api/models.">
      <Err>{error}</Err>
      {!data && !error && <Loading />}
      <div className="grid gap-4 xl:grid-cols-2">{data?.items.map((m: any) => <ModelCard key={m.id} m={m} reload={reload} />)}</div>
    </Page>
  );
}

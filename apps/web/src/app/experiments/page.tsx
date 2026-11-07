'use client';
import dynamic from 'next/dynamic';
import { useRouter } from 'next/navigation';
import { useMemo, useState } from 'react';
import { Badge, Button, Card, Err, Page } from '@/components/ui';
import { post, useApi } from '@/lib/api';

const ScenarioEditor = dynamic(() => import('./ScenarioEditor'), { ssr: false, loading: () => <Card title="Scenario authoring"><p className="text-mute">Loading editor...</p></Card> });

function toggle<T>(list: T[], v: T) { return list.includes(v) ? list.filter((x) => x !== v) : [...list, v]; }

export default function Experiments() {
  const router = useRouter();
  const scenarios = useApi('/scenarios?limit=500');
  const models = useApi('/models?limit=200');
  const guardrails = useApi('/guardrails');
  const [name, setName] = useState('my-experiment');
  const [selected, setSelected] = useState<string[]>([]);
  const [defenders, setDefenders] = useState<string[]>(['mock-obedient']);
  const [presets, setPresets] = useState<string[]>(['none', 'layered']);
  const [attacker, setAttacker] = useState('');
  const [strategy, setStrategy] = useState('scenario');
  const [budget, setBudget] = useState(3);
  const [trials, setTrials] = useState(1);
  const [maxTokens, setMax] = useState(400);
  const [filter, setFilter] = useState('');
  const [error, setError] = useState<string | null>(null);
  const items = scenarios.data?.items ?? [];
  const shown = useMemo(() => items.filter((s: any) => (s.id + s.category + s.kind).includes(filter.toLowerCase())), [items, filter]);
  const count = selected.length || items.length;
  const refusals = (selected.length ? items.filter((s: any) => selected.includes(s.id)) : items).filter((s: any) => s.kind === 'refusal').length;
  const total = ((count - refusals) * presets.length + refusals) * defenders.length * trials;
  const launch = async () => {
    setError(null);
    try {
      const exp = await post('/experiments', { name, scenarios: selected, defenders, guardrails: presets, trials, attacker: attacker || null, attack_strategy: strategy, attack_budget: budget, generation: { max_tokens: maxTokens } });
      const run = await post(`/experiments/${exp.id}/run`);
      router.push(`/campaigns?run=${run.id}`);
    } catch (e) { setError((e as Error).message); }
  };
  return (
    <Page title="Experiment Builder" sub="Choose scenarios, models, and defenses. All attacks run against synthetic fixtures in the sandbox.">
      <div className="grid gap-4 xl:grid-cols-[1fr_380px]">
        <Card title={`Scenarios (${selected.length || 'all'} selected of ${items.length})`} right={<input type="text" aria-label="Filter scenarios" placeholder="Filter..." value={filter} onChange={(e) => setFilter(e.target.value)} />}>
          <div className="max-h-[440px] overflow-y-auto">
            <table><thead><tr><th></th><th>ID</th><th>Fam.</th><th>Kind</th><th>Surface</th><th>Protected boundary</th></tr></thead><tbody>
              {shown.map((s: any) => (
                <tr key={s.id} data-click onClick={() => setSelected(toggle(selected, s.id))}>
                  <td><input type="checkbox" aria-label={s.id} checked={selected.includes(s.id)} readOnly /></td>
                  <td className="font-mono text-[12px]">{s.id}</td><td className="font-mono">{s.family}</td><td><Badge>{s.request_label ?? s.kind}</Badge></td><td className="font-mono text-[12px] text-sub">{s.attacker_surface}</td><td className="text-sub">{s.protected_boundary}</td>
                </tr>
              ))}
            </tbody></table>
          </div>
        </Card>
        <Card title="Campaign">
          <div className="space-y-3">
            <label className="block text-[12px] text-sub">Name<input type="text" value={name} onChange={(e) => setName(e.target.value)} className="mt-1 w-full" /></label>
            <fieldset><legend className="text-[12px] text-sub">Defender models</legend>
              {models.data?.items.map((m: any) => <label key={m.id} className="mt-1 flex items-center gap-2 font-mono text-[12px]"><input type="checkbox" checked={defenders.includes(m.id)} onChange={() => setDefenders(toggle(defenders, m.id))} />{m.id}</label>)}
            </fieldset>
            <fieldset><legend className="text-[12px] text-sub">Guardrail configurations</legend>
              {guardrails.data?.items.map((g: any) => <label key={g.preset} className="mt-1 flex items-center gap-2 font-mono text-[12px]"><input type="checkbox" checked={presets.includes(g.preset)} onChange={() => setPresets(toggle(presets, g.preset))} />{g.preset}</label>)}
            </fieldset>
            <div className="grid grid-cols-2 gap-2">
              <label className="text-[12px] text-sub">Attack payloads<select value={strategy} onChange={(e) => setStrategy(e.target.value)} className="mt-1 w-full"><option value="scenario">From scenario</option><option value="template">Templates</option><option value="paraphrase">Paraphrase</option><option value="multilingual">Multilingual</option><option value="model">Attacker model</option></select></label>
              <label className="text-[12px] text-sub">Attacker model<select value={attacker} onChange={(e) => setAttacker(e.target.value)} className="mt-1 w-full" disabled={strategy !== 'model'}><option value="">None</option>{models.data?.items.map((m: any) => <option key={m.id}>{m.id}</option>)}</select></label>
              <label className="text-[12px] text-sub">Generation budget<input type="number" min={1} value={budget} onChange={(e) => setBudget(Number(e.target.value))} className="mt-1 w-full" /></label>
              <label className="text-[12px] text-sub">Trials per cell<input type="number" min={1} value={trials} onChange={(e) => setTrials(Number(e.target.value))} className="mt-1 w-full" /></label>
              <label className="col-span-2 text-[12px] text-sub">Max tokens per step<input type="number" min={1} value={maxTokens} onChange={(e) => setMax(Number(e.target.value))} className="mt-1 w-full" /></label>
            </div>
            <Err>{error}</Err>
            <Button variant="primary" className="w-full" disabled={!defenders.length || !presets.length || (strategy === 'model' && !attacker)} onClick={launch}>Start {strategy === 'scenario' ? `${total} trials` : 'campaign'}</Button>
          </div>
        </Card>
      </div>
      <ScenarioEditor />
    </Page>
  );
}

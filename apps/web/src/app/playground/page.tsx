'use client';
import { useEffect, useState } from 'react';
import { Button, Card, Err, Page } from '@/components/ui';
import { num, post, useApi } from '@/lib/api';

function Pane({ models, model, setModel, result, busy }: any) {
  return (
    <Card title={<select aria-label="Model" value={model} onChange={(e) => setModel(e.target.value)}>{models.map((m: any) => <option key={m.id} value={m.id}>{m.id}</option>)}</select>}>
      {busy && <p className="text-mute">Generating...</p>}
      {result?.error && <Err>{result.error}</Err>}
      {result && !busy && (
        <>
          <pre className="max-h-96 overflow-y-auto whitespace-pre-wrap font-sans text-[13px]">{result.text}</pre>
          <dl className="mt-3 grid grid-cols-3 gap-2 border-t border-line pt-2 font-mono text-[11px] text-sub">
            <div>prompt {num(result.prompt_tokens)}</div><div>completion {num(result.completion_tokens)}</div><div>wall {num(result.wall_ms)} ms</div>
            <div>ttft {num(result.ttft_ms)} ms</div><div>{num(result.tokens_per_s, 1)} tok/s</div><div>GPU {num(result.gpu_memory_mb)} MB</div>
            <div className="col-span-3">{result.backend} {result.backend_version} / {result.quantization} / {result.hardware}</div>
          </dl>
        </>
      )}
    </Card>
  );
}

export default function Playground() {
  const { data } = useApi('/models?limit=200');
  const models = data?.items ?? [];
  const [a, setA] = useState(''); const [b, setB] = useState('');
  const [prompt, setPrompt] = useState('Explain indirect prompt injection in two sentences.');
  const [temperature, setT] = useState(0); const [topP, setTopP] = useState(1); const [maxTokens, setMax] = useState(256); const [seed, setSeed] = useState(0);
  const [results, setResults] = useState<any[]>([null, null]);
  const [busy, setBusy] = useState(false); const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (models.length && !a) {
      const ids = models.map((m: any) => m.id);
      setA(ids.includes('qwen3-8b-ollama') ? 'qwen3-8b-ollama' : ids[0]);
      setB(ids.includes('qwen3-8b-abliterated-ollama') ? 'qwen3-8b-abliterated-ollama' : ids[1] ?? ids[0]);
    }
  }, [models, a]);
  const run = async () => {
    setBusy(true); setError(null); setResults([null, null]);
    const config = { temperature, top_p: topP, max_tokens: maxTokens, seed };
    const messages = [{ role: 'user', content: prompt }];
    try {
      // One at a time, so the two models don't compete for memory and skew each other's timing.
      const first = await post('/inference', { model_id: a, messages, config });
      setResults([first, null]);
      setResults([first, await post('/inference', { model_id: b, messages, config })]);
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  return (
    <Page title="Model Playground" sub="The same input and settings go to both models, one after the other. Each call is recorded.">
      <Card>
        <label className="label block text-sub" htmlFor="prompt">Shared input</label>
        <textarea id="prompt" value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={4} className="mt-1 w-full font-mono text-[13px]" />
        <div className="mt-2 flex flex-wrap items-end gap-3">
          {([['Temperature', temperature, setT, 0.1], ['Top-p', topP, setTopP, 0.05], ['Max tokens', maxTokens, setMax, 1], ['Seed', seed, setSeed, 1]] as const).map(([l, v, set, step]) => (
            <label key={l} className="text-[12px] text-sub">{l}<input type="number" step={step} value={v} onChange={(e) => (set as any)(Number(e.target.value))} className="ml-1.5 w-20 font-mono" /></label>
          ))}
          <Button variant="primary" onClick={run} disabled={busy || !a || !prompt.trim()}>{busy ? 'Running...' : 'Run both'}</Button>
        </div>
      </Card>
      <Err>{error}</Err>
      <div className="grid gap-4 lg:grid-cols-2">
        <Pane models={models} model={a} setModel={setA} result={results[0]} busy={busy && !results[0]} />
        <Pane models={models} model={b} setModel={setB} result={results[1]} busy={busy && !!results[0] && !results[1]} />
      </div>
    </Page>
  );
}

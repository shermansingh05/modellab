'use client';
import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Badge, Card, Empty, Page } from '@/components/ui';
import { useApi, when } from '@/lib/api';

export default function Reports() {
  const runs = useApi('/reports?limit=50');
  const [sel, setSel] = useState<string | null>(null);
  const items = runs.data?.items ?? [];
  const id = sel ?? items[0]?.id ?? null;
  const md = useApi<string>(id ? `/evaluations/${id}/report?format=markdown` : null);
  const url = (f: string) => `/api/evaluations/${id}/report?format=${f}`;
  return (
    <Page title="Research Reports" sub="Built from stored records, with configuration, provenance, and known limitations.">
      <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
        <Card title="Runs">
          {items.length === 0 && <Empty>No finished runs.</Empty>}
          <table><tbody>{items.map((r: any) => (
            <tr key={r.id} data-click onClick={() => setSel(r.id)} className={r.id === id ? 'bg-raised' : ''}><td><div>{r.experiment_name}</div><div className="text-[11px] text-mute">{when(r.finished_at)}</div></td><td><Badge>{r.status}</Badge></td></tr>
          ))}</tbody></table>
        </Card>
        {id && (
          <Card title="Report" right={<span className="flex gap-3 text-[13px]">{['json', 'markdown', 'csv'].map((f) => <a key={f} className="text-accent hover:underline" href={url(f)} download={`${id}.${f === 'markdown' ? 'md' : f}`}>{f.toUpperCase()}</a>)}</span>}>
            {typeof md.data === 'string' ? <div className="report"><ReactMarkdown remarkPlugins={[remarkGfm]}>{md.data}</ReactMarkdown></div> : <p className="text-mute">Loading...</p>}
          </Card>
        )}
      </div>
    </Page>
  );
}

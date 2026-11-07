/**
 * Server-side proxy to the FastAPI service, so the admin token never reaches the browser.
 * Since it adds that token, changes are only accepted from this page's own loopback origin, which
 * stops another website or a DNS-rebinding attack from driving a local run through a visitor's browser.
 */
import { NextRequest } from 'next/server';

const API = process.env.MODELLAB_API_URL ?? 'http://127.0.0.1:8100';
const LOOPBACK = new Set(['127.0.0.1', 'localhost', '[::1]']);

function allowed(req: NextRequest): boolean {
  const host = (req.headers.get('host') ?? '').replace(/:\d+$/, '');
  if (!LOOPBACK.has(host)) return false;
  if (req.method === 'GET') return true;
  const origin = req.headers.get('origin');
  if (!origin) return false;
  try { return new URL(origin).host === req.headers.get('host'); } catch { return false; }
}

async function forward(req: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  if (!allowed(req)) return Response.json({ detail: 'forbidden origin' }, { status: 403 });
  const { path } = await params;
  const url = `${API}/api/${path.map(encodeURIComponent).join('/')}${req.nextUrl.search}`;
  const headers: Record<string, string> = { 'content-type': req.headers.get('content-type') ?? 'application/json' };
  if (process.env.MODELLAB_ADMIN_TOKEN) headers.authorization = `Bearer ${process.env.MODELLAB_ADMIN_TOKEN}`;
  try {
    const res = await fetch(url, { method: req.method, headers, body: req.method === 'GET' ? undefined : await req.text(), cache: 'no-store' });
    return new Response(res.body, { status: res.status, headers: { 'content-type': res.headers.get('content-type') ?? 'application/json', 'cache-control': 'no-store' } });
  } catch {
    return Response.json({ detail: `API unreachable at ${API}. Start it with: uv run modellab api` }, { status: 502 });
  }
}

export const GET = forward;
export const POST = forward;
export const dynamic = 'force-dynamic';

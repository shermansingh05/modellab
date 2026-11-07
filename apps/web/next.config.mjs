import { dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
/** @type {import('next').NextConfig} */
export default { reactStrictMode: true, poweredByHeader: false,
  async headers() {
    return [{ source: '/:path*', headers: [
      { key: 'X-Frame-Options', value: 'DENY' }, { key: 'X-Content-Type-Options', value: 'nosniff' },
      { key: 'Referrer-Policy', value: 'no-referrer' }, { key: 'X-Robots-Tag', value: 'noindex' },
    ] }];
  }, outputFileTracingRoot: dirname(fileURLToPath(import.meta.url)) };

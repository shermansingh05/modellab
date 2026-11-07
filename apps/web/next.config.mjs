import { dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
/** @type {import('next').NextConfig} */
export default { reactStrictMode: true, poweredByHeader: false, outputFileTracingRoot: dirname(fileURLToPath(import.meta.url)) };

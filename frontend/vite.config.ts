import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

// Another container under Compose; the host's own API when run natively.
const api = process.env.AVELORN_API_URL ?? 'http://127.0.0.1:8000';

export default defineConfig({
	plugins: [sveltekit()],
	server: {
		proxy: {
			'/api': {
				target: api,
				rewrite: (path) => path.replace(/^\/api/, '')
			}
		}
	}
});

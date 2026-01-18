import { defineConfig } from 'vite';

export default defineConfig({
  build: {
    rollupOptions: {
      input: {
        main: 'index.html', // Your main application entry point
        beta: 'beta.html', // Your new beta page entry point
        admin: 'admin.html', // Admin Page
        admin: 'analysis.html', // Admin Page
      },
    },
    sourceMap: true, // Enable source maps for easier debugging
    minify: false, // Disable minification for better readability
    outDir: 'dist',
  },
});

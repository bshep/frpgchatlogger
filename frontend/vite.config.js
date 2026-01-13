import { defineConfig } from 'vite';

export default defineConfig({
  build: {
    rollupOptions: {
      input: {
        main: 'index.html', // Your main application entry point
        beta: 'beta.html', // Your new beta page entry point
      },
      sourceMap: true, // Enable source maps for easier debugging
      minify: false, // Disable minification for better readability
    },
  },
});

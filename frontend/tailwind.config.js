/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        surface: {
          1: '#0d0d0d',
          2: '#1a1a1a',
          3: '#262626',
        },
        accent: {
          DEFAULT: '#eab308',
          hover: '#ca8a04',
          muted: '#713f12',
        },
        border: '#2a2a2a',
        muted: '#6b7280',
      },
      fontFamily: {
        sans: ['Pretendard', '-apple-system', 'BlinkMacSystemFont', 'system-ui', 'sans-serif'],
      },
    },
  },
  plugins: [],
}

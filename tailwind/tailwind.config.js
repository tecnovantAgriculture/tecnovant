module.exports = {
  content: ["../project/app/**/templates/**/*.j2"],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        primary: '#3490dc',
        secondary: '#ffed4a',
      },
      screens: {
        xs: '480px',
        sm: '640px',
        md: '768px',
        lg: '1024px',
        xl: '1280px',
        '2xl': '1536px',
      },
      fontSize: {
        tiny: '0.75rem',
        small: '0.875rem',
      },
      gridTemplateColumns: {
        13: 'repeat(13, minmax(0, 1fr))',
      },
      gap: {
        13: '3.25rem',
      },
    },
  },
  plugins: [],
}


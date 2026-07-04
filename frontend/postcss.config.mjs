import pxtorem from 'postcss-pxtorem';

const config = {
  plugins: {
    "@tailwindcss/postcss": {},
    "postcss-pxtorem": {
      rootValue: 16,
      propList: ['*'],
      selectorBlackList: [],
    },
  },
};

export default config;

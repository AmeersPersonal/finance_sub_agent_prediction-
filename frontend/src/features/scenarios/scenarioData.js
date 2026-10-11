// Invented example assets. Starting values are a shared index level of 100,
// not market quotes. Weights scale the educational formula so the sandbox can
// show relative differences. They are not measured sensitivities.
export const DEFAULT_SCENARIO = {
  policyRate: 0.5,
  earningsSurprise: 0,
  sectorDemand: 0,
  cryptoVolatility: 0,
};

export const scenarioAssets = [
  {
    symbol: "AAPL",
    name: "Apple",
    type: "Stock",
    startingValue: 100,
    weights: { policy: 1, earnings: 1.1, demand: 0.7, crypto: 0 },
  },
  {
    symbol: "NVDA",
    name: "Nvidia",
    type: "Stock",
    startingValue: 100,
    weights: { policy: 1.8, earnings: 1.7, demand: 1.25, crypto: 0 },
  },
  {
    symbol: "VOO",
    name: "Vanguard S&P 500 ETF",
    type: "Index fund",
    startingValue: 100,
    weights: { policy: 0.55, earnings: 0.45, demand: 0.8, crypto: 0 },
  },
  {
    symbol: "QQQ",
    name: "Invesco QQQ",
    type: "ETF",
    startingValue: 100,
    weights: { policy: 1.35, earnings: 0.95, demand: 1.05, crypto: 0 },
  },
  {
    symbol: "BTC",
    name: "Bitcoin",
    type: "Crypto",
    startingValue: 100,
    weights: { policy: 0.4, earnings: 0, demand: 0.25, crypto: 1 },
  },
  {
    symbol: "ETH",
    name: "Ethereum",
    type: "Crypto",
    startingValue: 100,
    weights: { policy: 0.5, earnings: 0, demand: 0.35, crypto: 1.15 },
  },
];

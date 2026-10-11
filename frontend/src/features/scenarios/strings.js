// All visible copy for the scenarios page lives here.
export const strings = {
  productName: "Market Move Dashboard",
  pageTitle: "Market Move Scenarios",
  documentTitle: "Market Move Scenarios — Market Move Dashboard",
  breadcrumb: "Dashboard / Scenarios",
  breadcrumbNavLabel: "Breadcrumb",
  dashboardCrumb: "Dashboard",
  scenariosCrumb: "Scenarios",
  backToDashboard: "Back to dashboard",
  hypotheticalSandbox: "Hypothetical sandbox",
  sandboxSupport:
    "Explore educational examples of how different market forces can affect assets. These examples are not forecasts.",
  resetScenario: "Reset scenario",
  viewAsTable: "View as table",
  viewAsChart: "View as chart",
  learningMode: "Learning Mode",
  learningOn: "On",
  learningOff: "Off",
  notAForecast: "These examples are not forecasts.",
  disclaimer:
    "Hypothetical educational example. Not financial advice. Real markets can behave differently.",
  whatThisDoesNotTellYou: "What this does not tell you",
  notForecastItem: "This is not a forecast.",
  notEveryFactor: "It does not account for every market factor.",
  notADecision: "It should not be used to make an investment decision.",

  skipToControls: "Skip to scenario controls",
  skipToResults: "Skip to results",
  controlsTitle: "Scenario controls",
  controlsIntro:
    "Move a control to change the educational example. Nothing here places an order or predicts a price.",
  resultsTitle: "Scenario results",
  resultsIntro:
    "Each figure is an illustrative example built from the controls. It is not a quote and not a prediction.",
  interpretationTitle: "How to read this example",
  accessibilityTitle: "Accessibility notes",
  loading: "Loading Market Move Scenarios",

  themeName: "Theme",
  themeDark: "Dark",
  themeLight: "Light",
  status: "Illustrative session",
  statusDetail: "No live orders",
  account: "Account menu",
  signedIn: "Signed-in reader",
  readerSettings: "Reader settings",
  closeMenu: "Close menu",

  policyLabel: "Policy rate change",
  policyDescription: "Example change in a central bank policy rate, in percentage points.",
  policyLearning:
    "A policy rate is an interest rate set by a central bank. In this sandbox, a higher rate is drawn as pressure on growth-oriented assets. This is an illustration, not a forecast.",
  earningsLabel: "Earnings surprise",
  earningsDescription: "Example gap between reported earnings and a published estimate.",
  earningsLearning:
    "An earnings surprise is the difference between reported results and what analysts expected. Moving this control only changes the illustration.",
  demandLabel: "Sector demand shift",
  demandDescription: "Example rise or fall in demand for a sector.",
  demandLearning:
    "Sector demand here is a made-up shift in buying interest. It is not a count of real orders.",
  cryptoLabel: "Crypto volatility shock",
  cryptoDescription: "Example increase in how widely the crypto illustrations are shown swinging.",
  cryptoLearning:
    "Volatility is how widely a price tends to swing. In this sandbox the shock is applied only to the crypto examples, and it is drawn as an upward example move. That is a teaching choice, not a claim that volatility lifts prices.",

  exampleStartingValue: "Example starting value",
  signedValueLabel: "Signed value",
  illustrativePrefix: "Illustrative example:",
  chartNote:
    "Bar length shows the example percentage change from a starting level of 100. A symbol, a sign, and the words up, down, or neutral sit with every value.",
  legendLabel: "Direction legend",
  chartSummaryLead:
    "Illustrative scenario results showing example relative effects for AAPL, NVDA, VOO, QQQ, BTC, and ETH.",

  tableCaption:
    "Illustrative scenario results for the current educational inputs. These figures are not forecasts.",
  colAsset: "Asset",
  colType: "Asset type",
  colStart: "Starting value",
  colChange: "Illustrative change",
  colDirection: "Direction",
  colExplanation: "Explanation",

  directionUp: "up",
  directionDown: "down",
  directionNeutral: "neutral",
  symbolUp: "▲",
  symbolDown: "▼",
  symbolNeutral: "–",
  percentWord: "percent",
  plusWord: "plus",
  minusWord: "minus",

  interpretationHigherRates:
    "In this example, higher rates are shown alongside more pressure on growth-oriented assets.",
  interpretationLowerRates:
    "In this example, lower rates are shown alongside less pressure on growth-oriented assets.",
  interpretationEarningsUp:
    "A positive earnings surprise is shown as an upward example effect on the stock and fund illustrations.",
  interpretationEarningsDown:
    "A negative earnings surprise is shown as a downward example effect on the stock and fund illustrations.",
  interpretationDemandUp: "Stronger sector demand is shown as an upward example effect.",
  interpretationDemandDown: "Weaker sector demand is shown as a downward example effect.",
  interpretationCrypto:
    "A crypto volatility shock is shown only on Bitcoin and Ethereum, as an upward example swing in this sandbox. It is not a claim that volatility lifts prices.",
  interpretationNeutral:
    "With these controls near a neutral setting, the sandbox shows little relative movement.",
  interpretationCaveat: "Real markets can behave differently.",
  interpretationLearning:
    "The bars compare example reactions inside this sandbox. A longer bar means a larger illustrative percentage change, not a more certain outcome.",

  announcementUpdated: "Illustrative scenario updated.",
  announcementReset: "Scenario reset to the educational defaults.",

  explainOnly: "Illustrative example only.",
  explainPolicyHigher:
    "A higher policy rate is drawn as downward pressure, stronger on the growth-oriented examples.",
  explainPolicyLower: "A lower policy rate is drawn as less pressure in this sandbox.",
  explainEarningsPositive: "A positive earnings surprise is drawn as an upward example effect.",
  explainEarningsNegative: "A negative earnings surprise is drawn as a downward example effect.",
  explainDemandPositive: "Stronger sector demand is drawn as an upward example effect.",
  explainDemandNegative: "Weaker sector demand is drawn as a downward example effect.",
  explainCrypto:
    "The crypto volatility shock is drawn as an upward example move for this crypto asset only.",
  explainLittle:
    "These inputs are close to a neutral setting for this asset, so the sandbox shows little relative movement.",
  explainMarkets: "Real markets can behave differently.",

  assetRole: {
    AAPL: "Apple is drawn as a large-company stock with a moderate example response.",
    NVDA: "Nvidia is drawn as a growth-oriented stock with a stronger example response to rates and earnings.",
    VOO: "This index fund is drawn with a milder example response than a single growth stock.",
    QQQ: "This fund is drawn with a growth tilt, so the example response is stronger than the broad index fund.",
    BTC: "Bitcoin is drawn as crypto, so the volatility shock applies and the earnings control does not.",
    ETH: "Ethereum is drawn as crypto, with a slightly wider example response to the volatility shock than Bitcoin.",
  },

  assetLearning: {
    AAPL: "Learning note: Apple’s example moves when the rate, earnings, or demand controls change. The crypto shock is not applied.",
    NVDA: "Learning note: Nvidia is the most rate-sensitive stock in this sandbox, so the same policy-rate input draws a larger example move.",
    VOO: "Learning note: An index fund illustration spreads an example effect across many companies, so the bar is shorter than a single growth stock.",
    QQQ: "Learning note: This fund illustration is tilted toward growth companies, so rate pressure is drawn as stronger than for the broad index fund.",
    BTC: "Learning note: Bitcoin ignores the earnings control in this sandbox. The volatility shock is drawn as an upward example, which is a teaching choice.",
    ETH: "Learning note: Ethereum follows the same crypto rule as Bitcoin, with a slightly larger example weight on the volatility shock.",
  },

  glossary: {
    policyRate: {
      label: "Policy rate",
      definition:
        "The interest rate a central bank sets for lending to banks. This page uses it only as an educational input.",
    },
    earningsSurprise: {
      label: "Earnings surprise",
      definition:
        "The gap between a company’s reported earnings and a previously published estimate. The figures on this page are invented.",
    },
    volatility: {
      label: "Volatility",
      definition:
        "How widely a price tends to swing. A larger number here means a wider illustrative swing, not a prediction.",
    },
    indexFund: {
      label: "Index fund",
      definition:
        "A fund that aims to track a market index, such as the S&P 500. VOO is shown here as an example index fund.",
    },
    illustrativeExample: {
      label: "Illustrative example",
      definition:
        "A made-up demonstration of a relationship. It is not a forecast, a market quote, or a recommendation.",
    },
  },

  notesKeyboard:
    "Keyboard: range controls use Left and Right, or Up and Down, to change by one step. Home and End jump to the ends. Buttons, including glossary terms, Learning Mode, theme, the account menu, and Reset scenario, use Enter or Space. Escape closes a glossary note or the account menu.",
  notesPatterns:
    "ARIA patterns: labeled range inputs with a visible output, a debounced polite status for committed scenario changes, a chart exposed as a single image with a text summary, a semantic data table, toggletip buttons with aria-expanded, and a menu button.",
  notesChart:
    "Chart access: the chart summary names every asset and its illustrative direction. The table is the row-by-row alternative. Direction always includes a symbol, a sign, and the words up, down, or neutral.",
  notesAudit:
    "Manual audit still needed with NVDA, JAWS, and VoiceOver: confirm slider value text, that the debounced status does not speak on every arrow press, glossary Escape and blur behavior, menu focus return, and reading order at 320px and 200% zoom.",
};

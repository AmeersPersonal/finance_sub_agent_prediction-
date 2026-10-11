// Chart timeframes, news filters, forecast labels, and the dev-only preview states.
export const TIMEFRAMES = ['1D', '1W', '1M', '1Y', '5Y'];
// News filter tab -> the document role the backend assigned (sources/spec.md).
export const NEWS_ROLES = { 'Company info': 'company_info', Opinion: 'public_opinion', 'Product & events': 'product_event' };
export const NEWS_FILTERS = ['All', ...Object.keys(NEWS_ROLES)];
export const STRATEGY_LABELS = { long_term: 'Long-term investors', day_trader: 'Day traders', index_options: 'Index & options traders' };
/** direction -> [arrow, label, CSS tone class] */
export const DIRECTIONS = {
  up: ['▲', 'Up', 'up'], down: ['▼', 'Down', 'down'], flat: ['◆', 'Flat', ''], unclear: ['?', 'Unclear', 'muted'],
};
export const PREVIEW_STATES = ['normal', 'loading', 'empty', 'error', 'stale', 'market_closed', 'halted'];

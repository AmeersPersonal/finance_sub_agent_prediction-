// Educational model only. These values are invented examples, not forecasts.
import { strings } from "./strings.js";
import { scenarioAssets } from "./scenarioData.js";

const MINUS = "\u2212";

export function calculateIllustrativeEffect(asset, scenario) {
  const weights = asset.weights;
  const growthPressure = scenario.policyRate * -0.8 * weights.policy;
  const earningsEffect = scenario.earningsSurprise * 0.12 * weights.earnings;
  const demandEffect = scenario.sectorDemand * 0.1 * weights.demand;
  const cryptoEffect =
    asset.type === "Crypto" ? scenario.cryptoVolatility * 0.04 * weights.crypto : 0;

  const changePercent = growthPressure + earningsEffect + demandEffect + cryptoEffect;
  const direction =
    changePercent > 0.05 ? "up" : changePercent < -0.05 ? "down" : "neutral";

  return {
    symbol: asset.symbol,
    name: asset.name,
    type: asset.type,
    startingValue: asset.startingValue,
    changePercent,
    signedValue: asset.startingValue * (changePercent / 100),
    direction,
    explanation: buildExplanation(asset, {
      growthPressure,
      earningsEffect,
      demandEffect,
      cryptoEffect,
    }),
  };
}

export function calculateScenario(scenario) {
  return scenarioAssets.map((asset) => calculateIllustrativeEffect(asset, scenario));
}

export function buildInterpretation(scenario) {
  const sentences = [];
  if (scenario.policyRate > 0) sentences.push(strings.interpretationHigherRates);
  else if (scenario.policyRate < 0) sentences.push(strings.interpretationLowerRates);

  if (scenario.earningsSurprise > 0) sentences.push(strings.interpretationEarningsUp);
  else if (scenario.earningsSurprise < 0) sentences.push(strings.interpretationEarningsDown);

  if (scenario.sectorDemand > 0) sentences.push(strings.interpretationDemandUp);
  else if (scenario.sectorDemand < 0) sentences.push(strings.interpretationDemandDown);

  if (scenario.cryptoVolatility > 0) sentences.push(strings.interpretationCrypto);

  if (sentences.length === 0) sentences.push(strings.interpretationNeutral);
  sentences.push(strings.interpretationCaveat);
  return sentences.join(" ");
}

export function buildAnnouncement(results, { reset = false } = {}) {
  const lead = reset ? strings.announcementReset : strings.announcementUpdated;
  const detail = results
    .map((result) => `${result.symbol} ${directionWord(result.direction)} ${formatSpeechPercent(result.changePercent)}`)
    .join(", ");
  return `${lead} ${detail}. ${strings.notAForecast}`;
}

export function buildChartLabel(results) {
  const detail = results
    .map(
      (result) =>
        `${result.symbol} ${result.name}, ${directionWord(result.direction)} ${formatSpeechPercent(result.changePercent)}`,
    )
    .join(". ");
  return `${strings.chartSummaryLead} ${detail}. ${strings.notAForecast}`;
}

export function directionWord(direction) {
  if (direction === "up") return strings.directionUp;
  if (direction === "down") return strings.directionDown;
  return strings.directionNeutral;
}

export function directionSymbol(direction) {
  if (direction === "up") return strings.symbolUp;
  if (direction === "down") return strings.symbolDown;
  return strings.symbolNeutral;
}

export function formatSignedPercent(value) {
  const rounded = Math.round(value * 10) / 10;
  const abs = Math.abs(rounded).toFixed(1);
  if (rounded > 0) return `+${abs}%`;
  if (rounded < 0) return `${MINUS}${abs}%`;
  return "0.0%";
}

export function formatLevel(value) {
  return Number(value).toFixed(2);
}

export function formatSignedPoints(value) {
  const rounded = Math.round(value * 100) / 100;
  const abs = Math.abs(rounded).toFixed(2);
  if (rounded > 0) return `+${abs}`;
  if (rounded < 0) return `${MINUS}${abs}`;
  return "0.00";
}

export function formatControlValue(key, value) {
  if (key === "policyRate") {
    const abs = Math.abs(value).toFixed(2);
    if (value > 0) return `+${abs}%`;
    if (value < 0) return `${MINUS}${abs}%`;
    return "0.00%";
  }
  const abs = Math.abs(value).toFixed(0);
  if (value > 0) return `+${abs}%`;
  if (value < 0) return `${MINUS}${abs}%`;
  return "0%";
}

export function formatControlSpeech(key, value) {
  const number = key === "policyRate" ? Math.abs(value).toFixed(2) : Math.abs(value).toFixed(0);
  if (value > 0) return `${strings.plusWord} ${number} ${strings.percentWord}`;
  if (value < 0) return `${strings.minusWord} ${number} ${strings.percentWord}`;
  return `0 ${strings.percentWord}`;
}

export function formatSpeechPercent(value) {
  const rounded = Math.round(Math.abs(value) * 10) / 10;
  return `${rounded.toFixed(1)} ${strings.percentWord}`;
}

export function illustrativePhrase(result) {
  return `${strings.illustrativePrefix} ${directionSymbol(result.direction)} ${formatSignedPercent(result.changePercent)} ${directionWord(result.direction)}`;
}

function buildExplanation(asset, parts) {
  const clauses = [];
  if (parts.growthPressure <= -0.05) clauses.push(strings.explainPolicyHigher);
  else if (parts.growthPressure >= 0.05) clauses.push(strings.explainPolicyLower);

  if (parts.earningsEffect >= 0.05) clauses.push(strings.explainEarningsPositive);
  else if (parts.earningsEffect <= -0.05) clauses.push(strings.explainEarningsNegative);

  if (parts.demandEffect >= 0.05) clauses.push(strings.explainDemandPositive);
  else if (parts.demandEffect <= -0.05) clauses.push(strings.explainDemandNegative);

  if (parts.cryptoEffect >= 0.05) clauses.push(strings.explainCrypto);

  const body = clauses.length > 0 ? clauses.join(" ") : strings.explainLittle;
  const role = strings.assetRole[asset.symbol] ?? "";
  return `${strings.explainOnly} ${role} ${body} ${strings.explainMarkets}`;
}

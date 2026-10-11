import { strings } from "../strings.js";
import GlossaryToggletip from "./GlossaryToggletip.jsx";

export default function HypotheticalBanner() {
  return (
    <aside className="banner" aria-label={strings.hypotheticalSandbox}>
      <p className="eyebrow">{strings.hypotheticalSandbox}</p>
      <p className="bannerCopy">{strings.sandboxSupport}</p>
      <p className="bannerForecast">
        {strings.notAForecast} <GlossaryToggletip term="illustrativeExample" />
      </p>
    </aside>
  );
}

import { strings } from '../../constants/strings.js';

export default function SkipLinks() {
  return (
    <>
      <a className="skip" href="#story">{strings.skipStory}</a>
      <a className="skip" href="#chart">{strings.skipChart}</a>
      <a className="skip" href="#forecast">{strings.skipForecast}</a>
      <a className="skip" href="#news">{strings.skipNews}</a>
    </>
  );
}

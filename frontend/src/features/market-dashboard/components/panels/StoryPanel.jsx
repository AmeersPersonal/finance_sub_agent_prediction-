// "Today's story": the latest move in plain language, the headline mood from the latest
// forecast (an AI summary of the headlines it read), and the newest saved headline.
import { useRef } from 'react';
import { strings } from '../../constants/strings.js';
import { percent, dateText } from '../../lib/format.js';
import StatePanel from '../ui/StatePanel.jsx';
import Term from '../ui/Term.jsx';

const toneLabel = (overall) => (overall > 0.15 ? 'Headlines lean positive' : overall < -0.15 ? 'Headlines lean negative' : 'Headlines are mixed');

export default function StoryPanel({ asset, quote, news, prediction, moves, setSelectedEvent, learning, onLoad }) {
  const heading = useRef(null);
  const move = quote.data ? percent(quote.data.price, quote.data.previousClose) : 0;
  const latest = news.data?.slice().sort((a, b) => new Date(b.publishedAt) - new Date(a.publishedAt))[0];
  const sentiment = prediction?.headline_sentiment;
  const largest = moves[0];

  function seeOnChart() {
    if (largest) setSelectedEvent(largest.id);
    document.getElementById('chart')?.scrollIntoView({ block: 'center' });
    document.querySelector('#chart [role=img]')?.focus();
  }

  return (
    <section id="story" aria-labelledby="story-heading" className="panel lg:col-span-5">
      <div className="eyebrow mb-2">THE DAILY EXPLANATION · {asset.type.toUpperCase()}</div>
      <h2 id="story-heading" ref={heading} tabIndex={-1}>{strings.story}</h2>

      <StatePanel name={strings.story} state={quote} headingRef={heading} onLoad={onLoad} emptyText={strings.noPrices}>
        <p className="serif text-[clamp(1.35rem,2.3vw,2rem)] leading-snug mb-4">
          {asset.name} {move < 0 ? 'fell' : 'rose'} {Math.abs(move).toFixed(1)}% versus its previous close
          {quote.data?.asOf && <> as of {dateText(quote.data.asOf)}</>}.
        </p>

        {sentiment?.summary ? (
          <div className="mb-5">
            <p className="mb-2">{sentiment.summary}</p>
            <div className="flex flex-wrap gap-2 items-center">
              <span className="tag">{toneLabel(sentiment.overall)}</span>
              <span className="small muted">AI summary of the headlines read by the {dateText(prediction.generated_at)} forecast</span>
            </div>
            {learning && (
              <p className="small muted mt-2">
                <Term name={strings.tone} description={strings.toneExplain} /> — {strings.toneExplain}
              </p>
            )}
          </div>
        ) : (
          <p className="small muted mb-5">{strings.noStory}</p>
        )}

        {latest && (
          <p className="small border-l-2 pl-3 mb-5" style={{ borderColor: 'var(--accent)' }}>
            Latest headline:{' '}
            <a href={latest.url} target="_blank" rel="noopener noreferrer">{latest.headline}</a>
            <span className="muted"> · {latest.source}</span>
          </p>
        )}

        {largest && <button className="action primary" onClick={seeOnChart}>{strings.seeChart} →</button>}
      </StatePanel>
    </section>
  );
}

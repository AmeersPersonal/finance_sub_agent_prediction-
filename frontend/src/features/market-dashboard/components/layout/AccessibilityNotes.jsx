import { strings } from '../../constants/strings.js';

export default function AccessibilityNotes() {
  return (
    <section aria-labelledby="accessibility-heading" className="border-t rule pt-7">
      <h2 id="accessibility-heading" className="serif text-2xl mb-4">{strings.accessibility}</h2>
      <ol className="list-decimal pl-6 space-y-3 small muted">
        <li>{strings.notesKeyboard}</li>
        <li>{strings.notesPatterns}</li>
        <li>{strings.notesCanvas}</li>
        <li>{strings.notesAudit}</li>
      </ol>
    </section>
  );
}

import { strings } from '../../constants/strings.js';

export default function Footer() {
  return (
    <footer className="border-t rule px-4 md:px-8 py-5 small muted">
      <div className="max-w-[1440px] mx-auto">{strings.product} · {strings.educational} · {strings.dataSource}</div>
    </footer>
  );
}

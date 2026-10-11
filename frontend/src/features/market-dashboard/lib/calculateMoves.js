// Picks the three largest explained moves. Uses an inline Web Worker for large
// histories (150+ points) and falls back to the main thread if workers fail.
export function calculateMoves(request) {
  const run = () => ({
    id: request.id,
    eventIds: request.events.slice().sort((a, b) => Math.abs(b.change) - Math.abs(a.change)).slice(0, 3).map((e) => e.id),
  });
  if (typeof Worker === 'undefined' || request.points.length < 150) return Promise.resolve(run());

  return new Promise((resolve) => {
    const code = 'self.onmessage=e=>{const x=e.data;self.postMessage({id:x.id,eventIds:x.events.slice().sort((a,b)=>Math.abs(b.change)-Math.abs(a.change)).slice(0,3).map(v=>v.id)})}';
    let worker;
    let timer;
    try {
      const url = URL.createObjectURL(new Blob([code], { type: 'text/javascript' }));
      worker = new Worker(url);
      URL.revokeObjectURL(url);
      timer = window.setTimeout(() => { worker?.terminate(); resolve(run()); }, 2000);
      worker.onmessage = (e) => { clearTimeout(timer); worker?.terminate(); resolve(e.data); };
      worker.onerror = () => { clearTimeout(timer); worker?.terminate(); resolve(run()); };
      worker.postMessage(request);
    } catch {
      clearTimeout(timer);
      worker?.terminate();
      resolve(run());
    }
  });
}

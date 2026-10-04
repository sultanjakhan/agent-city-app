(operation, capability) => {
  const key = '__agentCityDesktopRecovery';
  const previous = window[key];
  if (previous && previous.controller) previous.controller.abort();
  const state = { operation, document: performance.timeOrigin, status: 'pending', controller: new AbortController() };
  window[key] = state;
  const timer = setTimeout(() => {
    if (window[key] === state && state.status === 'pending') {
      state.status = 'expired'; state.controller.abort();
    }
  }, 12000);
  void fetch('/api/owner-bootstrap', {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Agent-City': '1' },
    body: JSON.stringify({ capability }), signal: state.controller.signal
  }).then(response => {
    if (window[key] === state && state.document === performance.timeOrigin && state.status === 'pending')
      state.status = response.ok ? 'ok' : 'refused';
  }).catch(() => {
    if (window[key] === state && state.status === 'pending') state.status = 'refused';
  }).finally(() => clearTimeout(timer));
  return 'started';
}

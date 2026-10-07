// Thin wrappers around the local Studio API (tak/server.py).

async function request(method, path, body) {
  const options = {method, headers: {}, cache: 'no-store'};
  if (body !== undefined) {
    options.headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(path, options);
  } catch (error) {
    throw new Error(`Studio server unreachable (${error.message})`);
  }
  const text = await response.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = {error: text}; }
  if (!response.ok) throw new Error(data?.error || `HTTP ${response.status}`);
  return data;
}

export const api = {
  info: () => request('GET', '/api/info'),
  avatars: () => request('GET', '/api/avatars'),
  check: () => request('GET', '/api/check'),
  settings: () => request('GET', '/api/settings'),
  saveSettings: values => request('PUT', '/api/settings', values),
  jobs: () => request('GET', '/api/jobs'),
  job: (id, offset = 0) => request('GET', `/api/jobs/${encodeURIComponent(id)}?offset=${offset}`),
  startJob: payload => request('POST', '/api/jobs', payload),
  cancelJob: id => request('POST', `/api/jobs/${encodeURIComponent(id)}/cancel`, {}),
  renders: () => request('GET', '/api/renders'),
  saveRender: payload => request('POST', '/api/renders', payload),
};

export async function api(path, opts) {
  const r = await fetch(path, opts)
  if (r.status === 401) { location.href = '/login'; throw new Error('login') }
  return r.json()
}
export const post = (path, body) => api(path, {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
})

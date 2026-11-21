import { apiHandler } from '../_shared/runtime.ts'

const handler = apiHandler()
Deno.serve(request => {
  const url = new URL(request.url)
  url.pathname = '/api/v1/reports/send-now'
  return handler(new Request(url, request))
})

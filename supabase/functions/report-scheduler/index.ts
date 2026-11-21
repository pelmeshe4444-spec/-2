import { schedulerHandler } from '../_shared/scheduler-http.ts'

Deno.serve(schedulerHandler())

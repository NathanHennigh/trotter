/**
 * src/api/ingest.js
 * Gmail import API calls.
 */

import { api } from './client';

/** Start a Gmail import job. Returns { job_id }. */
export async function startImport(token) {
  return api.post('/ingest/gmail/import', {}, token);
}

/**
 * Poll the status of a sync job.
 * Returns { job_id, state, scanned_count, parsed_count, segment_count, error_message }.
 */
export async function pollJob(token, jobId) {
  return api.get(`/ingest/jobs/${jobId}`, token);
}

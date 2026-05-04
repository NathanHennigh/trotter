/**
 * src/api/trips.js
 * Trips and segments API calls.
 */

import { api } from './client';

/** Flat list of all flight segments for the current user, sorted by dep_time. */
export async function getSegments(token) {
  return api.get('/trips/segments', token);
}

/** All trips with nested segments, newest first. */
export async function getTrips(token) {
  return api.get('/trips', token);
}

/** Single trip by ID. */
export async function getTrip(token, tripId) {
  return api.get(`/trips/${tripId}`, token);
}

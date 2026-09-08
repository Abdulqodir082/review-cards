#!/usr/bin/env node
/**
 * Daily review snapshot collector for otvizcards.
 *
 * Reads tracking/businesses.json, calls Google's official Places API (New)
 * "Place Details" endpoint for each business, and appends a timestamped
 * record { card_id, business_name, place_id, date, collected_at, rating,
 * review_count } to tracking-history.json (one flat array, appended over time).
 *
 * Auth: expects the API key in the GOOGLE_MAPS_API_KEY environment variable.
 *   Local run:   GOOGLE_MAPS_API_KEY=xxxx node tracking/snapshot.mjs
 *   Plumbing test (no key, fake data):  SNAPSHOT_FAKE=1 node tracking/snapshot.mjs
 *
 * No third-party dependencies — uses Node's built-in fetch + fs (Node 18+).
 */

import { readFile, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = join(HERE, '..');
const BUSINESSES_FILE = join(HERE, 'businesses.json');
const HISTORY_FILE = join(REPO, 'tracking-history.json');

const API_KEY = process.env.GOOGLE_MAPS_API_KEY;
const FAKE = process.env.SNAPSHOT_FAKE === '1';

async function readJSON(path, fallback) {
  try {
    return JSON.parse(await readFile(path, 'utf8'));
  } catch (e) {
    if (e.code === 'ENOENT' && fallback !== undefined) return fallback;
    throw new Error(`Could not read/parse ${path}: ${e.message}`);
  }
}

/**
 * Fetch rating + review count for one Place ID from the Places API (New).
 * Docs: https://developers.google.com/maps/documentation/places/web-service/place-details
 */
async function fetchPlace(placeId) {
  if (FAKE) {
    // Deterministic pseudo-data so the pipeline can be tested without a key.
    const seed = [...placeId].reduce((a, c) => a + c.charCodeAt(0), 0);
    return { name: '(fake) ' + placeId, rating: 4 + (seed % 10) / 10, review_count: 50 + (seed % 200) };
  }

  const url = `https://places.googleapis.com/v1/places/${encodeURIComponent(placeId)}?languageCode=en`;
  const res = await fetch(url, {
    headers: {
      'X-Goog-Api-Key': API_KEY,
      'X-Goog-FieldMask': 'id,displayName,rating,userRatingCount'
    }
  });

  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const msg = body?.error?.message || `HTTP ${res.status}`;
    throw new Error(msg);
  }
  return {
    name: body?.displayName?.text || null,
    rating: typeof body.rating === 'number' ? body.rating : null,
    review_count: typeof body.userRatingCount === 'number' ? body.userRatingCount : null
  };
}

function todayUTC() {
  return new Date().toISOString().slice(0, 10); // YYYY-MM-DD
}

async function main() {
  if (!API_KEY && !FAKE) {
    console.error('ERROR: GOOGLE_MAPS_API_KEY is not set. (Or run with SNAPSHOT_FAKE=1 to test the plumbing.)');
    process.exit(1);
  }

  const cfg = await readJSON(BUSINESSES_FILE);
  const businesses = (cfg.businesses || []).filter(b => b.place_id && b.place_id.trim());
  if (!businesses.length) {
    console.error('No businesses with a place_id in tracking/businesses.json — nothing to do.');
    process.exit(1);
  }

  const history = await readJSON(HISTORY_FILE, []);
  const date = todayUTC();
  const collected_at = new Date().toISOString();

  let added = 0, failed = 0, skipped = 0;

  for (const b of businesses) {
    // Skip if we already recorded this business today (safe for manual re-runs).
    const dup = history.some(r => r.card_id === b.card_id && r.date === date);
    if (dup) {
      console.log(`• ${b.name} (card ${b.card_id}): already recorded for ${date}, skipping.`);
      skipped++;
      continue;
    }
    try {
      const p = await fetchPlace(b.place_id);
      const record = {
        card_id: b.card_id,
        business_name: b.name || p.name,
        place_id: b.place_id,
        date,
        collected_at,
        rating: p.rating,
        review_count: p.review_count
      };
      history.push(record);
      added++;
      console.log(`✓ ${record.business_name} (card ${b.card_id}): rating ${record.rating}, ${record.review_count} reviews`);
    } catch (e) {
      failed++;
      console.error(`✗ ${b.name} (card ${b.card_id}): ${e.message}`);
    }
  }

  await writeFile(HISTORY_FILE, JSON.stringify(history, null, 2) + '\n');
  console.log(`\nDone. added=${added} skipped=${skipped} failed=${failed}. Total records: ${history.length}`);

  // Fail the job only if every business failed (so one bad Place ID doesn't stop the rest).
  if (added === 0 && failed > 0) process.exit(1);
}

main().catch(e => { console.error(e); process.exit(1); });

#!/usr/bin/env node
/**
 * Helper: find a Google Place ID from a business name.
 *
 * Usage:
 *   GOOGLE_MAPS_API_KEY=xxxx node tracking/find-place-id.mjs "O'zbegim Lavash, Sho'rchi"
 *
 * Prints the top matches with their Place ID, so you can paste the right one
 * into tracking/businesses.json. Uses Places API (New) Text Search.
 */

const API_KEY = process.env.GOOGLE_MAPS_API_KEY;
const query = process.argv.slice(2).join(' ').trim();

if (!API_KEY) { console.error('ERROR: set GOOGLE_MAPS_API_KEY first.'); process.exit(1); }
if (!query)  { console.error('Usage: node tracking/find-place-id.mjs "Business name, city"'); process.exit(1); }

const res = await fetch('https://places.googleapis.com/v1/places:searchText', {
  method: 'POST',
  headers: {
    'X-Goog-Api-Key': API_KEY,
    'Content-Type': 'application/json',
    'X-Goog-FieldMask': 'places.id,places.displayName,places.formattedAddress,places.rating,places.userRatingCount'
  },
  body: JSON.stringify({ textQuery: query, languageCode: 'en' })
});

const body = await res.json().catch(() => ({}));
if (!res.ok) { console.error('Error:', body?.error?.message || res.status); process.exit(1); }

const places = body.places || [];
if (!places.length) { console.log('No matches for:', query); process.exit(0); }

console.log(`Matches for "${query}":\n`);
places.forEach((p, i) => {
  console.log(`${i + 1}. ${p.displayName?.text || '(no name)'}`);
  console.log(`   Place ID : ${p.id}`);
  console.log(`   Address  : ${p.formattedAddress || '-'}`);
  console.log(`   Rating   : ${p.rating ?? '-'} (${p.userRatingCount ?? 0} reviews)\n`);
});
console.log('Copy the correct Place ID into tracking/businesses.json.');

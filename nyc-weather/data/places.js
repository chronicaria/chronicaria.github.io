// Places for the sidebar, grouped. Each place: { name, slug, lat, lon, tz, offsetF? }.
// slug drives the shareable URL hash (e.g. #seoul). tz is the IANA timezone for display
// (times arrive as UTC and are formatted in tz). offsetF = per-neighborhood urban-heat-island
// offset (°F, day/night) applied to the forecast — NYC neighborhoods only; other cities get the
// raw regional forecast. See the Rome vault note [[Urban heat island]].
const DEFAULT_PLACE = "Murray Hill";

const PLACE_GROUPS = [
  {
    group: "New York, NY",
    places: [
      { name: "Murray Hill",    slug: "murray-hill",  lat: 40.748, lon: -73.976, tz: "America/New_York", offsetF: { day: 0.5,  night: 2.5 } },
      { name: "Battery Park",   slug: "battery-park",  lat: 40.703, lon: -74.017, tz: "America/New_York", offsetF: { day: -0.3, night: 0.5 } },
      { name: "Elmhurst",       slug: "elmhurst",      lat: 40.742, lon: -73.882, tz: "America/New_York", offsetF: { day: 0.3,  night: 2.0 } },
      { name: "Flushing",       slug: "flushing",      lat: 40.759, lon: -73.830, tz: "America/New_York", offsetF: { day: 0.0,  night: 2.0 } },
    ],
  },
  {
    group: "Other U.S. cities",
    places: [
      { name: "Durham, NC",      slug: "durham",      lat: 35.994, lon: -78.899, tz: "America/New_York" },
      { name: "Cambridge, MA",   slug: "cambridge",   lat: 42.373, lon: -71.109, tz: "America/New_York" },
      { name: "Rochester, NY",   slug: "rochester",   lat: 43.161, lon: -77.611, tz: "America/New_York" },
      { name: "Stony Brook, NY", slug: "stony-brook", lat: 40.906, lon: -73.141, tz: "America/New_York" },
      { name: "Nashville, TN",   slug: "nashville",   lat: 36.163, lon: -86.781, tz: "America/Chicago" },
      { name: "Austin, TX",      slug: "austin",      lat: 30.267, lon: -97.743, tz: "America/Chicago" },
      { name: "Houston, TX",     slug: "houston",     lat: 29.760, lon: -95.369, tz: "America/Chicago" },
    ],
  },
  {
    group: "International",
    places: [
      { name: "Toronto, Canada",    slug: "toronto", lat: 43.651, lon: -79.347, tz: "America/Toronto" },
      { name: "Seoul, South Korea", slug: "seoul",   lat: 37.567, lon: 126.978, tz: "Asia/Seoul" },
    ],
  },
];

// flat list; sidebar buttons index into this
const PLACES = PLACE_GROUPS.flatMap((g) => g.places);

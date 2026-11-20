// Предаване на маршрута към Google Maps / Waze за истинската навигация.

export function googleMapsUrl(origin, destination, stops) {
  const p = new URLSearchParams({
    api: '1',
    origin: origin.join(','),
    destination: destination.join(','),
    travelmode: 'driving',
  });
  if (stops.length) p.set('waypoints', stops.map(s => `${s.lat.toFixed(6)},${s.lon.toFixed(6)}`).join('|'));
  return `https://www.google.com/maps/dir/?${p}`;
}

// Waze приема само една точка — водим до следващата спирка или до целта.
export function wazeUrl(destination, stops) {
  const [lat, lon] = stops.length ? [stops[0].lat, stops[0].lon] : destination;
  return `https://waze.com/ul?ll=${lat.toFixed(6)},${lon.toFixed(6)}&navigate=yes`;
}

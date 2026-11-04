// Draws the #pn-map element from the JSON in #pn-map-markers.
(function () {
  var element = document.getElementById("pn-map");
  var data = document.getElementById("pn-map-markers");
  if (!element || !data || !window.L) {
    return;
  }

  var NYU = [40.7295, -73.9965];
  var markers = JSON.parse(data.textContent);
  var map = L.map(element).setView(NYU, 13);

  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(map);

  // Facility names come from imported data, so set them as text, never as HTML.
  function popup(marker) {
    var link = document.createElement("a");
    link.href = marker.url;
    link.textContent = marker.name;
    return link;
  }

  var pins = markers.map(function (marker) {
    return L.marker([marker.lat, marker.lng], { title: marker.name, alt: marker.name })
      .addTo(map)
      .bindPopup(popup(marker));
  });

  if (pins.length === 1) {
    map.setView(pins[0].getLatLng(), 15);
  } else if (pins.length > 1) {
    map.fitBounds(L.featureGroup(pins).getBounds().pad(0.1));
  }
})();

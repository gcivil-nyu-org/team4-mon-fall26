// Narrows the sport and division selects to the chosen season.
// A form with no sport select only gets its divisions narrowed.
// Rules come from the JSON in #pn-season-rules. The server checks them again.
(function () {
  var data = document.getElementById("pn-season-rules");
  var season = document.getElementById("id_season");
  var sport = document.getElementById("id_sport");
  var division = document.getElementById("id_division");
  if (!data || !season || !division) {
    return;
  }

  var rules = JSON.parse(data.textContent);
  var sportLabel = document.querySelector('label[for="id_sport"]');
  // Hidden options still show in some browsers, so keep them here and re-add them.
  var divisionOptions = Array.prototype.slice.call(division.querySelectorAll("option"));

  function sync() {
    var rule = rules[season.value] || { sport: "", divisions: [] };

    var chosen = division.value;
    division.textContent = "";
    divisionOptions.forEach(function (option) {
      if (option.value === "" || rule.divisions.indexOf(option.value) !== -1) {
        division.appendChild(option);
      }
    });
    division.value = rule.divisions.indexOf(chosen) !== -1 ? chosen : "";

    if (!sport) {
      return;
    }
    // A disabled select sends no value. The server takes the sport from the season.
    if (rule.sport) {
      sport.value = rule.sport;
    }
    sport.disabled = Boolean(rule.sport);
    if (sportLabel) {
      sportLabel.classList.toggle("required", !rule.sport);
    }
  }

  season.addEventListener("change", sync);
  sync();
})();

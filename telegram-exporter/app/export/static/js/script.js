"use strict";

window.AllowBackFromHistory = false;

function CheckLocation() {
  var start = "#go_to_message";
  var hash = location.hash;
  if (hash.substr(0, start.length) === start) {
    var id = hash.substr(start.length);
    if (GoToMessage(id)) {
      window.AllowBackFromHistory = true;
    }
  }
}

function GoToMessage(id) {
  var element = document.getElementById("message" + id);
  if (!element) {
    return true; // not on this page: let the browser follow the link
  }
  var hash = "#go_to_message" + id;
  if (location.hash !== hash) {
    location.hash = hash;
  }
  element.scrollIntoView({ block: "center" });
  element.classList.add("selected");
  setTimeout(function () {
    element.classList.remove("selected");
  }, 1500);
  return false;
}

function ShowSpoiler(target) {
  if (target.classList.contains("hidden")) {
    target.classList.toggle("hidden");
  }
}

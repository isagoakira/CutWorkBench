(function () {
  var status = document.getElementById("status");
  var root = document.getElementById("root");
  var writable = document.getElementById("writable");
  var cep = window.__adobe_cep__;

  function invoke(name, payload) {
    if (!cep) { status.textContent = "CEP host bridge is unavailable."; return; }
    var expression = '$.global.CutWorkbenchPremiere.' + name + '(' + JSON.stringify(JSON.stringify(payload)) + ')';
    cep.evalScript(expression, function (result) { status.textContent = result || "Done"; });
  }
  function configuration() { return { root: root.value, writable: writable.checked }; }

  document.getElementById("refresh").onclick = function () { invoke("refresh", configuration()); };
  document.getElementById("poll").onclick = function () { invoke("poll", configuration()); };
  window.setInterval(function () {
    if (root.value) { invoke("refresh", configuration()); invoke("poll", configuration()); }
  }, 2500);
}());

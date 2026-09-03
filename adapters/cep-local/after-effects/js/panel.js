(function () {
  var status = document.getElementById("status"), root = document.getElementById("root"), writable = document.getElementById("writable"), cep = window.__adobe_cep__;
  function invoke(name, payload) { if (!cep) { status.textContent = "CEP host bridge is unavailable."; return; } cep.evalScript('$.global.CutWorkbenchAfterEffects.' + name + '(' + JSON.stringify(JSON.stringify(payload)) + ')', function (result) { status.textContent = result || "Done"; }); }
  function config() { return { root: root.value, writable: writable.checked }; }
  document.getElementById("refresh").onclick = function () { invoke("refresh", config()); };
  document.getElementById("poll").onclick = function () { invoke("poll", config()); };
  window.setInterval(function () { if (root.value) { invoke("refresh", config()); invoke("poll", config()); } }, 2500);
}());

// Palette status and pause controls. Jobs execute exclusively in the Python
// menu command; these JavaScript callbacks never execute the pump.

(function () {
  var POLL_MS = 250;
  var running = true;
  var elState = document.getElementById('state');
  var elQueue = document.getElementById('queue');
  var elLast  = document.getElementById('last');
  var elBtn   = document.getElementById('toggle');

  function setState(cls, text) { elState.className = cls; elState.textContent = text; }

  function showStatus(res) {
    var q = (res && typeof res.jobs === 'number') ? res.jobs : -1;
    elQueue.textContent = q >= 0 ? q : '–';
    if (q > 0) { elLast.textContent = new Date().toLocaleTimeString(); }
    running = !(res && res.paused);
    elBtn.textContent = running ? 'Pause' : 'Resume';
    if (q < 0) { setState('err', 'Bridge installation missing'); }
    else if (!running) { setState('off', 'Paused'); }
    else if (!(res && res.timer)) { setState('off', 'Inactive'); }
    else { setState('on', 'Active'); }
  }

  function tick() {
    if (!window.vwxBridge || !window.vwxBridge.pump) {
      setState('err', 'Bridge connection unavailable');
      setTimeout(tick, 1000);
      return;
    }
    window.vwxBridge.pump()
      .then(function (res) {
        showStatus(res);
        setTimeout(tick, POLL_MS);
      })
      .catch(function (err) {
        setState('err', 'Error: ' + err);
        setTimeout(tick, 1500);
      });
  }

  elBtn.addEventListener('click', function () {
    if (!window.vwxBridge || !window.vwxBridge.pump) { return; }
    elBtn.disabled = true;
    window.vwxBridge.pump(running)
      .then(showStatus)
      .catch(function (err) { setState('err', 'Error: ' + err); })
      .then(function () { elBtn.disabled = false; });
  });

  tick();
})();

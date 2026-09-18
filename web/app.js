const $ = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json();
}

function renderStatus(s) {
  $('state').textContent = `${s.state} · ${s.trigger}`;
  $('state-dot').classList.toggle('paused', s.state !== 'streaming');
  $('frames').textContent = s.frame_count.toLocaleString();
  $('drops').textContent = s.drops.toLocaleString();
  $('preview').textContent = `${s.preview_width}×${s.preview_height} @ ${s.preview_fps} fps`;
  $('imu').textContent = `${s.imu_rate_hz} Hz`;
  $('es').textContent = `${s.exposure_start_us} µs`;
  $('ee').textContent = `${s.exposure_end_us} µs`;
  $('exposure').value = s.exposure_us;
  $('exposure-value').textContent = s.controls_read_only ? 'recorded / unavailable' : `${s.exposure_us} µs`;
  $('gain').value = s.gain_x10;
  $('gain-value').textContent = s.controls_read_only ? 'recorded / unavailable' : `${(s.gain_x10 / 10).toFixed(1)}×`;
  $('last-action').textContent = s.last_action;

  const readOnly = Boolean(s.controls_read_only);
  $('trigger').disabled = readOnly;
  $('exposure').disabled = readOnly;
  $('gain').disabled = readOnly;
}

async function refresh() {
  try {
    renderStatus(await api('/api/status'));
  } catch (error) {
    $('state').textContent = 'offline';
    $('state-dot').classList.add('paused');
    $('last-action').textContent = error.message;
  }
}

$('capture').addEventListener('click', async () => renderStatus(await api('/api/capture/toggle', {method: 'POST'})));
$('trigger').addEventListener('click', async () => renderStatus(await api('/api/trigger/cycle', {method: 'POST'})));
$('reconnect').addEventListener('click', async () => renderStatus(await api('/api/reconnect', {method: 'POST'})));

let exposureTimer;
$('exposure').addEventListener('input', (event) => {
  if (event.target.disabled) return;
  $('exposure-value').textContent = `${event.target.value} µs`;
  clearTimeout(exposureTimer);
  exposureTimer = setTimeout(async () => {
    renderStatus(await api(`/api/exposure?value=${event.target.value}`, {method: 'POST'}));
  }, 80);
});

let gainTimer;
$('gain').addEventListener('input', (event) => {
  if (event.target.disabled) return;
  $('gain-value').textContent = `${(Number(event.target.value) / 10).toFixed(1)}×`;
  clearTimeout(gainTimer);
  gainTimer = setTimeout(async () => {
    renderStatus(await api(`/api/gain?value=${event.target.value}`, {method: 'POST'}));
  }, 80);
});

refresh();
setInterval(refresh, 500);
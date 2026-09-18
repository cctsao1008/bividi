const $ = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json();
}

function renderEvidenceNotice(s) {
  if (s.source === 'synthetic') {
    $('evidence-notice').textContent = 'Synthetic UI source. Preview quality, timing, disparity, and depth are not AR0234 measurements.';
  } else if (s.source.startsWith('replay:')) {
    $('evidence-notice').textContent = 'Replay source. Recorded provenance is preserved; any derived geometry shown below is computed from the explicitly selected calibration artifact and is not a new physical synchronization or accuracy claim.';
  } else {
    $('evidence-notice').textContent = 'Live engineering source. Camera/IMU data shown here remain source evidence; derived geometry requires an explicitly selected calibration artifact and separate measured validation.';
  }
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
  renderEvidenceNotice(s);

  const readOnly = Boolean(s.controls_read_only);
  $('trigger').disabled = readOnly;
  $('exposure').disabled = readOnly;
  $('gain').disabled = readOnly;
}

let lastDepthRevision = -1;

function renderDepthStatus(d) {
  const panel = $('depth-panel');
  panel.classList.toggle('hidden', !d.enabled);
  if (!d.enabled) {
    lastDepthRevision = -1;
    return;
  }

  $('depth-disposition').textContent = d.disposition || 'waiting';
  $('depth-calibration').textContent = d.calibration_id || '—';
  $('depth-sequence').textContent = d.sequence_present ? d.sequence.toLocaleString() : '—';
  $('depth-sync').textContent = d.synchronization || '—';
  $('depth-valid').textContent = d.processed ? `${(Number(d.valid_fraction || 0) * 100).toFixed(1)}%` : '—';
  $('depth-reset').textContent = d.observation_available ? String(d.reset_generation ?? '—') : '—';
  $('depth-reason').textContent = d.reason || (d.processed ? 'accepted' : '—');

  if (d.observation_available && d.revision !== lastDepthRevision) {
    const stamp = `${d.revision}-${Date.now()}`;
    $('disparity-image').src = `/disparity.jpg?v=${stamp}`;
    $('depth-image').src = `/depth.jpg?v=${stamp}`;
    lastDepthRevision = d.revision;
  }
}

async function refresh() {
  try {
    renderStatus(await api('/api/status'));
  } catch (error) {
    $('state').textContent = 'offline';
    $('state-dot').classList.add('paused');
    $('last-action').textContent = error.message;
  }

  try {
    renderDepthStatus(await api('/api/depth/status'));
  } catch (error) {
    $('depth-panel').classList.add('hidden');
    lastDepthRevision = -1;
  }
}

$('capture').addEventListener('click', async () => renderStatus(await api('/api/capture/toggle', {method: 'POST'})));
$('trigger').addEventListener('click', async () => renderStatus(await api('/api/trigger/cycle', {method: 'POST'})));
$('reconnect').addEventListener('click', async () => {
  renderStatus(await api('/api/reconnect', {method: 'POST'}));
  lastDepthRevision = -1;
  await refresh();
});

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

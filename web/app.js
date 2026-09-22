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
    $('evidence-notice').textContent = 'Replay source. Recorded provenance is preserved; calibrated derived geometry still requires an explicitly selected calibration artifact.';
  } else {
    $('evidence-notice').textContent = 'Live engineering source. Stereo/IMU data are measured source evidence. Quick depth, when enabled, is uncalibrated relative disparity only.';
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

  const quick = d.mode === 'quick_uncalibrated' || d.metric === false;
  const available = quick ? Boolean(d.available) : Boolean(d.observation_available);
  const processed = quick ? Boolean(d.available) && !d.error : Boolean(d.processed);
  const sequencePresent = quick ? Boolean(d.available) : Boolean(d.sequence_present);

  if (quick) {
    $('depth-title').textContent = 'Live uncalibrated stereo depth';
    $('depth-note').textContent = 'Quick preview only: Camera B is treated as rig-left and Camera A as rig-right. No rectification, intrinsics, baseline, or metric scale is applied; use this to inspect live relative near/far structure only.';
    $('disparity-caption').textContent = 'Uncalibrated disparity';
    $('depth-caption').textContent = 'Relative near / far heatmap';
    $('depth-calibration-label').textContent = 'Geometry mode';
    $('depth-calibration').textContent = 'uncalibrated';
    $('depth-sync').textContent = 'unverified';
    $('depth-processing').textContent = Number.isFinite(Number(d.processing_ms)) ? `${Number(d.processing_ms).toFixed(1)} ms` : '—';
    $('depth-disposition').textContent = d.error ? 'processing_error' : (available ? 'quick_uncalibrated' : 'waiting');
    $('depth-reason').textContent = d.error || 'relative disparity only';
  } else {
    $('depth-title').textContent = 'Calibrated stereo depth';
    $('depth-note').textContent = 'Visualization products derived from the selected calibration artifact and normalized source observation. Numeric float disparity/depth remains the authoritative geometry result.';
    $('disparity-caption').textContent = 'Disparity preview';
    $('depth-caption').textContent = 'Metric depth preview';
    $('depth-calibration-label').textContent = 'Calibration';
    $('depth-calibration').textContent = d.calibration_id || '—';
    $('depth-sync').textContent = d.synchronization || '—';
    $('depth-processing').textContent = 'calibrated';
    $('depth-disposition').textContent = d.disposition || 'waiting';
    $('depth-reason').textContent = d.reason || (processed ? 'accepted' : '—');
  }

  $('depth-sequence').textContent = sequencePresent ? Number(d.sequence || 0).toLocaleString() : '—';
  $('depth-valid').textContent = processed ? `${(Number(d.valid_fraction || 0) * 100).toFixed(1)}%` : '—';

  if (available && d.revision !== lastDepthRevision) {
    const stamp = `${d.revision}-${Date.now()}`;
    $('disparity-image').src = `/disparity.jpg?v=${stamp}`;
    $('depth-image').src = `/depth.jpg?v=${stamp}`;
    lastDepthRevision = d.revision;
  }
}

async function refreshStatus() {
  try {
    renderStatus(await api('/api/status'));
  } catch (error) {
    $('state').textContent = 'offline';
    $('state-dot').classList.add('paused');
    $('last-action').textContent = error.message;
  }
}

async function refreshDepth() {
  try {
    renderDepthStatus(await api('/api/depth/status'));
  } catch (error) {
    $('depth-panel').classList.add('hidden');
    lastDepthRevision = -1;
  }
}

async function refresh() {
  await Promise.all([refreshStatus(), refreshDepth()]);
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
setInterval(refreshStatus, 500);
setInterval(refreshDepth, 150);

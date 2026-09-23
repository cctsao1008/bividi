const $ = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json();
}

function renderEvidenceNotice(s) {
  if (s.source === 'synthetic') {
    $('evidence-notice').textContent = 'Synthetic UI source. Preview quality, timing, optical flow, disparity, and depth are not AR0234 measurements.';
  } else if (s.source.startsWith('replay:')) {
    $('evidence-notice').textContent = 'Replay source. Recorded provenance is preserved; browser optical flow is display-time image motion, while calibrated derived geometry still requires an explicitly selected calibration artifact.';
  } else {
    $('evidence-notice').textContent = 'Live engineering source. Stereo/IMU data are measured source evidence. Browser optical flow is an image-space diagnostic; quick depth, when enabled, remains uncalibrated relative disparity even when auto-rectification and display stabilization are active.';
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
  const processed = quick ? Boolean(d.available) : Boolean(d.processed);
  const sequencePresent = quick ? Boolean(d.available) : Boolean(d.sequence_present);

  if (quick) {
    const rectified = Boolean(d.rectified);
    const stabilized = Boolean(d.stabilized);
    const rawValid = Number(d.raw_valid_fraction || 0) * 100;
    const finalValid = Number(d.valid_fraction || 0) * 100;
    const displayValid = Number(d.display_valid_fraction || d.valid_fraction || 0) * 100;
    const temporalReused = Number(d.temporal_reused_fraction || 0) * 100;
    const before = Number(d.median_vertical_before_px || 0);
    const after = Number(d.median_vertical_after_px || 0);
    const attempts = Number(d.rectification_attempts || 0);
    const matches = Number(d.rectification_matches || 0);
    const inliers = Number(d.rectification_inliers || 0);

    $('depth-title').textContent = 'Live uncalibrated stereo depth';
    $('depth-note').textContent = rectified
      ? 'Quick preview only: Camera B is rig-left and Camera A is rig-right. A frozen image-derived homography rectifies the pair before StereoSGBM; conservative spatial cleanup and temporal smoothing affect display only. No intrinsics, lens model, baseline, or metric scale is applied.'
      : 'Quick preview only: Camera B is rig-left and Camera A is rig-right. Auto-rectification is still searching or rejected; conservative display stabilization is applied to raw unrectified StereoSGBM only. No metric scale is applied.';
    $('disparity-caption').textContent = rectified
      ? (stabilized ? 'Auto-rectified stabilized disparity' : 'Auto-rectified disparity')
      : (stabilized ? 'Raw stabilized disparity' : 'Raw unrectified disparity');
    $('depth-caption').textContent = rectified
      ? (stabilized ? 'Stabilized relative near / far' : 'Auto-rectified relative near / far')
      : (stabilized ? 'Raw stabilized relative near / far' : 'Raw relative near / far');
    $('depth-calibration-label').textContent = 'Geometry mode';
    $('depth-calibration').textContent = rectified ? 'uncalibrated + auto-rectified' : 'uncalibrated raw';
    $('depth-sync').textContent = 'unverified';
    $('depth-processing').textContent = Number.isFinite(Number(d.processing_ms)) ? `${Number(d.processing_ms).toFixed(1)} ms` : '—';
    $('depth-disposition').textContent = d.error
      ? 'raw_fallback'
      : (rectified
        ? (stabilized ? 'auto_rectified_stable' : 'auto_rectified')
        : (available ? (stabilized ? 'quick_raw_stable' : 'quick_raw') : 'waiting'));

    const filterSummary = stabilized
      ? `${d.filter_mode || 'stabilized'} · display ${displayValid.toFixed(1)}% · temporal reuse ${temporalReused.toFixed(1)}%`
      : 'display stabilization unavailable';
    const rectificationSummary = attempts > 0
      ? `${d.rectification_reason || 'rectification pending'} · ${matches} matches / ${inliers} inliers · vertical ${before.toFixed(2)}→${after.toFixed(2)} px · geometry valid ${rawValid.toFixed(1)}→${finalValid.toFixed(1)}% · ${filterSummary}`
      : `waiting for first auto-rectification attempt · ${filterSummary}`;
    $('depth-reason').textContent = d.error ? `${d.error} · ${rectificationSummary}` : rectificationSummary;
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
  if (quick && processed) {
    const geometryValid = Number(d.valid_fraction || 0) * 100;
    const displayValid = Number(d.display_valid_fraction || d.valid_fraction || 0) * 100;
    $('depth-valid').textContent = `${geometryValid.toFixed(1)}% geom · ${displayValid.toFixed(1)}% display`;
  } else {
    $('depth-valid').textContent = processed ? `${(Number(d.valid_fraction || 0) * 100).toFixed(1)}%` : '—';
  }

  if (available && d.revision !== lastDepthRevision) {
    const stamp = `${d.revision}-${Date.now()}`;
    $('disparity-image').src = `/disparity.jpg?v=${stamp}`;
    $('depth-image').src = `/depth.jpg?v=${stamp}`;
    lastDepthRevision = d.revision;
  }
}

// Lightweight browser-side sparse optical flow. This deliberately stays a
// visualization diagnostic: it consumes the already-rendered same-origin MJPEG
// previews and does not feed any result back into native geometry or VIO.
const FLOW_WIDTH = 320;
const FLOW_HEIGHT = 200;
const FLOW_GRID = 24;
const FLOW_PATCH_RADIUS = 2;
const FLOW_SEARCH_RADIUS = 6;
const FLOW_TEXTURE_GATE = 42;
const FLOW_SAD_GATE = 36;
const FLOW_BACK_GATE = 1.5;
const FLOW_PERIOD_MS = 100;

const flowScratch = document.createElement('canvas');
flowScratch.width = FLOW_WIDTH;
flowScratch.height = FLOW_HEIGHT;
const flowScratchContext = flowScratch.getContext('2d', {willReadFrequently: true});

let flowEnabled = true;
let previousFlowA = null;
let previousFlowB = null;
let previousFlowStamp = 0;

function flowGrayFromImage(image) {
  if (!image || image.naturalWidth <= 0 || image.naturalHeight <= 0) return null;
  flowScratchContext.drawImage(image, 0, 0, FLOW_WIDTH, FLOW_HEIGHT);
  const rgba = flowScratchContext.getImageData(0, 0, FLOW_WIDTH, FLOW_HEIGHT).data;
  const gray = new Uint8Array(FLOW_WIDTH * FLOW_HEIGHT);
  for (let i = 0, p = 0; i < gray.length; ++i, p += 4) {
    gray[i] = (77 * rgba[p] + 150 * rgba[p + 1] + 29 * rgba[p + 2]) >> 8;
  }
  return gray;
}

function flowTextureScore(gray, x, y) {
  const w = FLOW_WIDTH;
  let score = 0;
  for (let yy = y - 2; yy <= y + 2; yy += 2) {
    for (let xx = x - 2; xx <= x + 2; xx += 2) {
      const i = yy * w + xx;
      score += Math.abs(gray[i + 1] - gray[i - 1]);
      score += Math.abs(gray[i + w] - gray[i - w]);
    }
  }
  return score / 9;
}

function patchSad(reference, candidate, x, y, dx, dy) {
  let sad = 0;
  let samples = 0;
  for (let py = -FLOW_PATCH_RADIUS; py <= FLOW_PATCH_RADIUS; ++py) {
    const row0 = (y + py) * FLOW_WIDTH;
    const row1 = (y + dy + py) * FLOW_WIDTH;
    for (let px = -FLOW_PATCH_RADIUS; px <= FLOW_PATCH_RADIUS; ++px) {
      sad += Math.abs(reference[row0 + x + px] - candidate[row1 + x + dx + px]);
      ++samples;
    }
  }
  return sad / samples;
}

function bestPatchDisplacement(reference, candidate, x, y) {
  let best = Infinity;
  let bestDx = 0;
  let bestDy = 0;
  for (let dy = -FLOW_SEARCH_RADIUS; dy <= FLOW_SEARCH_RADIUS; ++dy) {
    for (let dx = -FLOW_SEARCH_RADIUS; dx <= FLOW_SEARCH_RADIUS; ++dx) {
      const score = patchSad(reference, candidate, x, y, dx, dy);
      if (score < best) {
        best = score;
        bestDx = dx;
        bestDy = dy;
      }
    }
  }
  return {dx: bestDx, dy: bestDy, sad: best};
}

function sparseBlockFlow(previous, current) {
  const margin = FLOW_PATCH_RADIUS + FLOW_SEARCH_RADIUS + 2;
  const vectors = [];
  for (let y = margin; y < FLOW_HEIGHT - margin; y += FLOW_GRID) {
    for (let x = margin; x < FLOW_WIDTH - margin; x += FLOW_GRID) {
      if (flowTextureScore(previous, x, y) < FLOW_TEXTURE_GATE) continue;
      const forward = bestPatchDisplacement(previous, current, x, y);
      if (forward.sad > FLOW_SAD_GATE) continue;

      const nx = x + forward.dx;
      const ny = y + forward.dy;
      if (nx < margin || ny < margin || nx >= FLOW_WIDTH - margin || ny >= FLOW_HEIGHT - margin) continue;
      const backward = bestPatchDisplacement(current, previous, nx, ny);
      const backError = Math.hypot(forward.dx + backward.dx, forward.dy + backward.dy);
      if (backError > FLOW_BACK_GATE) continue;

      vectors.push({x, y, dx: forward.dx, dy: forward.dy, sad: forward.sad, backError});
    }
  }
  return vectors;
}

function drawFlowArrow(context, x0, y0, x1, y1) {
  const angle = Math.atan2(y1 - y0, x1 - x0);
  const head = 7;
  context.beginPath();
  context.moveTo(x0, y0);
  context.lineTo(x1, y1);
  context.stroke();
  context.beginPath();
  context.moveTo(x1, y1);
  context.lineTo(x1 - head * Math.cos(angle - Math.PI / 6), y1 - head * Math.sin(angle - Math.PI / 6));
  context.lineTo(x1 - head * Math.cos(angle + Math.PI / 6), y1 - head * Math.sin(angle + Math.PI / 6));
  context.closePath();
  context.fill();
}

function percentile(values, q) {
  if (!values.length) return 0;
  const copy = [...values].sort((a, b) => a - b);
  return copy[Math.min(copy.length - 1, Math.floor(q * (copy.length - 1)))];
}

function renderFlowCamera(image, canvas, previous, current) {
  const context = canvas.getContext('2d');
  context.drawImage(image, 0, 0, canvas.width, canvas.height);
  if (!previous || !current) return {tracks: 0, mean: 0, p95: 0};

  const vectors = sparseBlockFlow(previous, current);
  const scaleX = canvas.width / FLOW_WIDTH;
  const scaleY = canvas.height / FLOW_HEIGHT;
  const magnitudes = [];
  context.lineWidth = 1.5;
  context.strokeStyle = '#ffe65a';
  context.fillStyle = '#75ff98';

  for (const v of vectors) {
    const x0 = v.x * scaleX;
    const y0 = v.y * scaleY;
    const x1 = (v.x + v.dx) * scaleX;
    const y1 = (v.y + v.dy) * scaleY;
    drawFlowArrow(context, x0, y0, x1, y1);
    context.beginPath();
    context.arc(x1, y1, 2.3, 0, Math.PI * 2);
    context.fill();
    magnitudes.push(Math.hypot(v.dx * scaleX, v.dy * scaleY));
  }

  const mean = magnitudes.length
    ? magnitudes.reduce((sum, value) => sum + value, 0) / magnitudes.length
    : 0;
  return {tracks: vectors.length, mean, p95: percentile(magnitudes, 0.95)};
}

function resetBrowserFlow() {
  previousFlowA = null;
  previousFlowB = null;
  previousFlowStamp = 0;
  $('flow-a-tracks').textContent = '—';
  $('flow-a-motion').textContent = '—';
  $('flow-b-tracks').textContent = '—';
  $('flow-b-motion').textContent = '—';
  $('flow-interval').textContent = '—';
  $('flow-processing').textContent = '—';
}

function updateOpticalFlow() {
  if (!flowEnabled) return;
  const imageA = $('camera-a-image');
  const imageB = $('camera-b-image');
  if (!imageA || !imageB || imageA.naturalWidth <= 0 || imageB.naturalWidth <= 0) return;

  const started = performance.now();
  try {
    const currentA = flowGrayFromImage(imageA);
    const currentB = flowGrayFromImage(imageB);
    if (!currentA || !currentB) return;

    const a = renderFlowCamera(imageA, $('flow-a'), previousFlowA, currentA);
    const b = renderFlowCamera(imageB, $('flow-b'), previousFlowB, currentB);
    const now = performance.now();
    const interval = previousFlowStamp > 0 ? now - previousFlowStamp : 0;

    $('flow-a-tracks').textContent = a.tracks.toLocaleString();
    $('flow-a-motion').textContent = `${a.mean.toFixed(1)} / ${a.p95.toFixed(1)} px/sample`;
    $('flow-b-tracks').textContent = b.tracks.toLocaleString();
    $('flow-b-motion').textContent = `${b.mean.toFixed(1)} / ${b.p95.toFixed(1)} px/sample`;
    $('flow-interval').textContent = interval > 0 ? `${interval.toFixed(1)} ms` : 'initializing';
    $('flow-processing').textContent = `${(performance.now() - started).toFixed(1)} ms`;
    $('flow-disposition').textContent = a.tracks + b.tracks > 0 ? 'browser_block_flow' : 'searching_texture';

    previousFlowA = currentA;
    previousFlowB = currentB;
    previousFlowStamp = now;
  } catch (error) {
    $('flow-disposition').textContent = 'flow_error';
    $('flow-processing').textContent = error.message;
    resetBrowserFlow();
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
  resetBrowserFlow();
  await refresh();
});

$('flow-toggle').addEventListener('click', () => {
  flowEnabled = !flowEnabled;
  $('flow-toggle').textContent = flowEnabled ? 'Pause optical flow' : 'Resume optical flow';
  $('flow-disposition').textContent = flowEnabled ? 'initializing' : 'paused';
  resetBrowserFlow();
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
setInterval(updateOpticalFlow, FLOW_PERIOD_MS);

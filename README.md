<p align="center">
  <img src="assets/bividi.svg" width="220" alt="Bividi mascot — two warm hand-drawn eyes">
</p>

<h1 align="center">bividi</h1>

<p align="center"><strong>Two little eyes, one grounded view.</strong></p>
<p align="center"><em>Seeing is evidence. Meaning comes later.</em></p>

Bividi is a small stereo-vision research project for turning two synchronized views of the physical world into calibrated, measurable observations.

It covers the path from camera capture to stereo geometry: synchronization, calibration, rectification, disparity, depth, and observation quality. The project deliberately stops before assigning higher-level meaning to what the cameras see.

## Why Bividi?

The name is a playful nod to **two viewpoints seeing the same world**. Bividi's little eyes are not meant to be an all-knowing vision system; they are two observers that provide evidence from slightly different perspectives.

That distinction is part of the project identity:

```text
seeing
  !=
knowing
```

## First pair of eyes

The initial reference hardware is the **Waveshare AR0144 Stereo USB Camera (A)**:

- dual global-shutter image sensors
- synchronized stereo capture
- USB/UVC host interface
- fixed physical stereo baseline

AR0144 is the first reference device, not the architectural identity of Bividi. Future stereo sources should be able to fit behind the same observation boundary.

## System boundary

```text
physical world
      |
      v
stereo source
      |
      v
capture + synchronization
      |
      v
stereo pair
      |
      +--> calibration
      +--> rectification
      +--> disparity / depth
      +--> quality / validity
      |
      v
stable stereo observation
      |
      +--> robotics / SLAM
      +--> CV / ML
      +--> future grounding experiments
```

The intended output is not merely an image pair. It is a stereo observation whose source, timing, calibration context, geometry, and validity can be inspected and measured.

Bividi remains independent from any particular semantic or AI architecture. A future LSMM experiment may consume Bividi observations, but Bividi itself stays on the **observation / grounding side** of that boundary.

## Project rule

**README explains the system. Issues explain the journey. Code proves the current state.**

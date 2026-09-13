<p align="center">
  <img src="assets/bividi.svg" width="180" alt="Bividi mascot">
</p>

<h1 align="center">bividi</h1>

<p align="center"><strong>Two little eyes, one grounded view.</strong></p>

Bividi is a small research project for synchronized stereo vision: capture, calibration, rectification, disparity, depth, and measurement quality.

The name hints at two viewpoints seeing the same physical world. The project keeps a deliberate separation between observation and meaning:

> Seeing is evidence. Meaning comes later.

## Initial reference hardware

- Waveshare AR0144 Stereo USB Camera (A)
- dual global-shutter sensors
- synchronized stereo capture
- USB/UVC host interface

AR0144 is the first reference device, not the architectural identity of the project.

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

Bividi is intentionally independent from any particular semantic or AI architecture. A future LSMM experiment may consume Bividi observations, but Bividi itself remains a stereo-observation system.

## Project rule

**README explains the system. Issues explain the journey. Code proves the current state.**

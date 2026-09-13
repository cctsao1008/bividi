# Tests

Tests should separate hardware-independent correctness from physical-camera characterization.

Examples of hardware-independent tests include frame-layout fixtures, status propagation, geometry math, calibration-file parsing, and synthetic disparity cases.

Hardware integration tests must be explicit and must not be required for ordinary offline test execution.

Passing synthetic tests is not evidence of AR0144 performance.

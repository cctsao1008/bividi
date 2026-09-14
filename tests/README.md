# Tests

Tests separate hardware-independent correctness from physical-device characterization.

Hardware-independent tests include capability/topology models, protocol/group decoding, timestamp rollover, status propagation, compact derived vectors, calibration-file parsing, and other deterministic core behavior.

Large vendor media and SDK archives are not required for ordinary offline test execution. When a vendor sample is useful, keep compact derived bytes/hashes in Git and provide an explicit verifier for the external source artifact.

Hardware integration tests must be explicit and must not be required for ordinary offline test execution.

Passing synthetic or vendor-sample tests proves decoder/contract correctness for those fixtures; it does not prove timing, synchronization, image quality, or long-run behavior of a physical camera.

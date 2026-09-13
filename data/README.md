# Data and external artifacts

This directory documents Bividi's data conventions; it is not a default store for large raw captures.

Keep small, reviewable manifests and metadata in Git. Store large image/video/calibration sessions externally unless the project explicitly adopts Git LFS or another artifact mechanism.

Where practical, an external artifact manifest should retain:

- source/device identity;
- capture mode;
- time/session identifier;
- file names and sizes;
- hashes;
- calibration identity if applicable;
- notes needed to reproduce the processing context.

Do not record private/sensitive scenes merely for convenience; test captures should be deliberate and minimal.

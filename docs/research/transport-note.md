# Transport Note

Bividi's logical observation/proposal interfaces are transport-independent. USB is the camera-facing transport for the first reference device; it is not the default protocol between Bividi, llm.c, and lsmm.c when those components run on the same host.

import unittest

from bividi.backend import BackendDevice, PlatformBackend
from bividi.capabilities import (
    CameraEncoding,
    CameraModality,
    CameraStreamCapability,
    SensorCapabilities,
    TriggerMode,
)
from bividi.device import DeviceAdapter


class _Backend:
    backend_id = "test-backend"
    platform_name = "test"

    def list_devices(self) -> tuple[BackendDevice, ...]:
        return (BackendDevice("dev0", "Synthetic device", "memory"),)


class _Adapter:
    adapter_id = "test-device"

    def supports(self, device: BackendDevice) -> bool:
        return device.backend_device_id == "dev0"

    def discover_capabilities(self, device: BackendDevice) -> SensorCapabilities:
        if not self.supports(device):
            raise ValueError(device.backend_device_id)
        return SensorCapabilities(
            cameras=(CameraStreamCapability("cam0"),),
        )


class CapabilityTests(unittest.TestCase):
    def test_mono_camera_rig(self) -> None:
        caps = SensorCapabilities(
            cameras=(
                CameraStreamCapability(
                    "cam0",
                    role="primary",
                    encoding=CameraEncoding.RGB,
                    modality=CameraModality.VISIBLE,
                ),
            )
        )
        self.assertEqual(caps.camera_count, 1)
        self.assertFalse(caps.has_stereo)
        self.assertFalse(caps.imu)
        self.assertFalse(caps.audio)

    def test_stereo_imu_rig(self) -> None:
        caps = SensorCapabilities(
            cameras=(
                CameraStreamCapability("cam-left", role="left", encoding=CameraEncoding.RGB),
                CameraStreamCapability("cam-right", role="right", encoding=CameraEncoding.RGB),
            ),
            stereo_pairs=(("cam-left", "cam-right"),),
            imu=True,
            device_timestamp=True,
            exposure_timestamp=True,
            hardware_sync=True,
            trigger_modes=(TriggerMode.SOFTWARE, TriggerMode.HARDWARE),
        )
        self.assertEqual(caps.camera_count, 2)
        self.assertTrue(caps.has_stereo)
        self.assertTrue(caps.imu)
        self.assertFalse(caps.audio)
        self.assertIn("hardware", caps.to_dict()["trigger_modes"])

    def test_multi_camera_auxiliary_modality(self) -> None:
        caps = SensorCapabilities(
            cameras=(
                CameraStreamCapability(
                    "rgb",
                    role="primary",
                    encoding=CameraEncoding.RGB,
                    modality=CameraModality.VISIBLE,
                ),
                CameraStreamCapability(
                    "ir-left",
                    role="left",
                    encoding=CameraEncoding.MONO,
                    modality=CameraModality.INFRARED,
                ),
                CameraStreamCapability(
                    "ir-right",
                    role="right",
                    encoding=CameraEncoding.MONO,
                    modality=CameraModality.INFRARED,
                ),
            ),
            stereo_pairs=(("ir-left", "ir-right"),),
            imu=True,
            audio=True,
        )
        self.assertEqual(caps.camera_count, 3)
        self.assertTrue(caps.has_stereo)
        self.assertTrue(caps.audio)
        self.assertEqual(caps.cameras[1].modality, CameraModality.INFRARED)

    def test_duplicate_camera_ids_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            SensorCapabilities(
                cameras=(
                    CameraStreamCapability("cam0"),
                    CameraStreamCapability("cam0", role="aux"),
                )
            )

    def test_invalid_stereo_pair_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            SensorCapabilities(
                cameras=(CameraStreamCapability("cam0"),),
                stereo_pairs=(("cam0", "missing"),),
            )

    def test_backend_and_adapter_are_separate_protocols(self) -> None:
        backend = _Backend()
        adapter = _Adapter()
        self.assertIsInstance(backend, PlatformBackend)
        self.assertIsInstance(adapter, DeviceAdapter)
        device = backend.list_devices()[0]
        self.assertTrue(adapter.supports(device))
        self.assertEqual(adapter.discover_capabilities(device).camera_count, 1)


if __name__ == "__main__":
    unittest.main()

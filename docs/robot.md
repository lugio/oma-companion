# Robot (optional)

← [Back to README](../README.md)

Alison can live in a [Reachy Mini](https://github.com/pollen-robotics/reachy_mini): gaze, gestures and
voice. Home automation and wake satellites are configured in the body settings, rather than embedded in code.

## Settings page and pairing

The body can serve a settings page on the local network; it is disabled without configuration.
Pairing uses a six-digit code **spoken by the robot** and logged on its host, valid once for three
minutes. Each paired device receives its own revocable token (*Devices* section of the page).

> [!WARNING]
> The page uses HTTP: someone listening on the local network could capture a code or a token.
> Enable it only on a trusted network.

## Vision features

> [!IMPORTANT]
> **Face recognition, camera recognition and license-plate detection/reading are optional and local,
> only on the robot host.** They do not run in the desktop panel.

See `reachy_vue.py`, `reachy_personnes.py`, `reachy_cams.py` and `reachy_objets.py`. Camera frames and
locally stored recognition data are sensitive; configure only cameras and people you intend to recognize.

On the robot host, vision uses NumPy, ONNX Runtime and OpenCV, plus MediaPipe for optional pose
detection. In its Python environment (see `reachy_vue.py`):

```bash
python -m pip install numpy onnxruntime opencv-python-headless matplotlib sounddevice
python -m pip install --no-deps mediapipe==0.10.35 absl-py
```

MediaPipe deliberately reuses this OpenCV installation instead of installing a second copy;
`pip check` may therefore report its OpenCV distribution requirement.

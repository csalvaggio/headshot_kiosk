# Headshot Kiosk

A Python-based touchscreen headshot kiosk for collecting standardized
portrait images using a USB camera, card-swipe identification, live
preview, countdown capture, image review, and optional email delivery.

The application is intended for unattended or semi-attended headshot
collection workflows where users identify themselves with an ID card,
position themselves in front of a camera, capture an image, review it,
and either accept or retake the photo.

## Features

- Touchscreen-friendly kiosk interface
- Full-screen live camera preview
- Separate control and preview windows
- ID card swipe support
- Configurable countdown timer
- Countdown and shutter sounds
- Image rotation and mirroring
- Optional square output crop
- Face/eye-aware vertical crop adjustment using OpenCV YuNet
- Review, accept, retake, and cancel workflow
- Local image saving
- Optional SMTP email delivery
- TOML-based configuration
- Debug single-screen mode for development and testing

## Repository Contents

| File | Description |
|---|---|
| `headshot_kiosk.py` | Main kiosk application |
| `config_kiosk.toml` | Example production-style kiosk configuration |
| `config_debug_single_screen.toml` | Example debug/development configuration |
| `requirements.txt` | Python package dependencies |
| `beep.wav` | Countdown sound |
| `camera_shutter.wav` | Shutter sound |
| `face_detection_yunet_2023mar.onnx` | OpenCV YuNet face detection model |

## Requirements

This project requires Python 3.11 or newer.

Python packages are listed in `requirements.txt`:

```bash
pip install -r requirements.txt
````

The main third-party dependencies are:

* `opencv-python`
* `numpy`
* `Pillow`
* `pydantic`
* `email-validator`

On Linux or Raspberry Pi OS, you may also need Tkinter and
camera-related system packages:

```bash
sudo apt install python3-tk v4l-utils
```

## Installation

Clone the repository:

```bash
git clone https://github.com/csalvaggio/headshot_kiosk.git
```

Create and activate a virtual environment:

```bash
cd headshot_kiosk
python3 -m venv venv
source venv/bin/activate
```

Install dependencies:

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

## Running the Kiosk

Run the application by providing a TOML configuration file:

```bash
python3 headshot_kiosk.py --config config_kiosk.toml
```

For development on a single monitor, use the debug configuration:

```bash
python3 headshot_kiosk.py --config config_debug_single_screen.toml
```

Press `Esc` to quit the application.

## Configuration

All operational settings are controlled through a TOML configuration
file.

Important configuration sections include:

* `[window]` — control and preview window geometry
* `[camera]` — camera index, resolution, and frame rate
* `[image_transform]` — rotation and mirroring
* `[eye_crop]` — face/eye-based square crop behavior
* `[email]` — optional SMTP email delivery
* `[ui]` — fonts, colors, button sizes, and layout
* `[text]` — user-facing messages and button labels
* `[colors]` — button and flash overlay colors

Example camera configuration:

```toml
[camera]
index = 0
width = 1920
height = 1080
fps = 30
```

Example image transform configuration:

```toml
[image_transform]
rotation_degrees = 270
mirror_horizontally = true
```

## Card Swipe Workflow

The kiosk is designed to begin a session when an ID card is swiped.
The software extracts a numeric UID from the raw swipe string using the
configured UID length.

For development and testing, the `u` key can be used to simulate a card
swipe using the value in:

```toml
debug_card_swipe = ";000000000=0000?"
```

## Output Images

Accepted images are saved to:

```text
headshots/accepted/
```

Each accepted image filename includes the UID and timestamp:

```text
headshot_<uid>_<timestamp>.jpg
```

## Email Delivery

Email delivery can be enabled in the TOML configuration:

```toml
[email]
enabled = true
to_address = "recipient@example.com"
from_address = "sender@example.com"
smtp_server = "smtp.example.com"
smtp_port = 25
```

When enabled, accepted images are attached to an email and sent through
the configured SMTP server.

## Raspberry Pi Notes

This application can be run on Raspberry Pi OS with a USB camera and
touchscreen display. Camera compatibility may depend on the USB camera,
V4L2 support, selected resolution, frame rate, and available USB
bandwidth.

Useful camera diagnostic commands include:

```bash
v4l2-ctl --list-devices
v4l2-ctl --list-formats-ext
```

If camera access fails, check that the user has permission to access
video devices.

## macOS Notes

On macOS, the application uses the AVFoundation camera backend. The
first time the application accesses the camera, macOS may require camera
permission approval in:

```text
System Settings > Privacy & Security > Camera
```

Countdown and shutter sounds are played using `afplay`.

## License

This project is licensed under the GNU General Public License v3.0.
See `LICENSE` for details.

## Contact

### Author  
Carl Salvaggio, Ph.D.  
Professor of Imaging Science  
Director, Digital Imaging and Remote Sensing (DIRS) Laboratory

### E-mail
carl.salvaggio@rit.edu

### Organization
Chester F. Carlson Center for Imaging Science  
Rochester Institute of Technology  
Rochester, New York, 14623  
United States
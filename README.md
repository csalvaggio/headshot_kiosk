# Headshot Kiosk

A Python-based touchscreen headshot kiosk for collecting standardized
portrait images using a USB camera, card-based user identification,
LDAP directory integration, live preview, spoken instructions,
countdown capture, image review, automated file naming, and optional
email delivery.

The application is intended for unattended or semi-attended headshot
collection workflows where users identify themselves with an ID card,
position themselves in front of a camera, capture an image, review it,
and either accept or retake the photo.

## Features

- **Dual-screen kiosk interface**
  - Touchscreen control interface for the user
  - Independent live preview display on a large monitor

- **Touchscreen-optimized user interface**
  - Designed for keyboard-free operation
  - Large buttons suitable for public kiosk environments

- **Card-based user identification**
  - Supports ISO/IEC 7813 magnetic stripe card readers
  - Supports ELATEC-style tap readers that emulate keyboard input
  - Hidden debug mode for operation without an ID card

- **LDAP integration**
  - Automatic user lookup from university directory services
  - Retrieves user name, username, and email address
  - Personalized user greeting
  - Automatic delivery to the user's email address

- **Live camera preview**
  - Full-screen preview mode
  - Optional automatic scaling to fit display resolution
  - Optional portrait-mode camera rotation
  - Optional image mirroring

- **Intelligent framing**
  - Optional square-format preview and capture
  - Optional eye-position-based automatic framing
  - Automatic accommodation of users with varying heights
  - Temporal smoothing for stable framing

- **Guided image acquisition**
  - Configurable spoken instructions
  - Audible countdown cues
  - Large on-screen countdown timer
  - Optional countdown visibility suppression immediately before capture
  - Simulated camera flash effect
  - Camera shutter sound effect

- **Image review workflow**
  - Accept image
  - Retake image
  - Cancel session

- **Automated file management**
  - Timestamped image naming
  - Username-based file naming
  - Automatic image archival

- **Email delivery**
  - Automatic delivery to identified user
  - Optional BCC copy for administrators
  - Image attached directly to email

- **Institutional deployment ready**
  - Automated user identification and file naming
  - Self-service operation requiring minimal staff assistance
  - Suitable for employee, faculty, student, and visitor headshot collection

- **Configuration-driven architecture**
  - Extensive TOML-based configuration
  - No code modifications required for deployment customization

- **Cross-platform support**
  - Raspberry Pi OS
  - Linux
  - macOS


## Typical Workflow

1. User presents an ID card.
   - Magnetic stripe card readers are supported.
   - ELATEC-style tap readers that emulate keyboard input are supported.

2. The kiosk identifies the user.
   - A university LDAP directory is queried.
   - User name, username, and email address are retrieved.

3. A personalized greeting is displayed.

4. The user positions themselves using the live preview monitor.

5. The user presses **Take Photo**.

6. Spoken instructions are played.

7. A countdown begins.
   - Audible countdown beeps are played.
   - The countdown is displayed on both screens.
   - Optional countdown hiding can be enabled immediately before capture.

8. The image is captured.
   - A flash effect is displayed.
   - A camera shutter sound is played.

9. The user reviews the image.
   - Accept
   - Retake
   - Cancel

10. Accepted images are:
    - Saved locally
    - Named using the user's username and a timestamp
    - Optionally emailed automatically to the identified user
    - Optionally BCC'd to an administrator


## Repository Contents

| File | Description |
|---|---|
| `headshot_kiosk.py` | Main kiosk application |
| `config_kiosk.toml` | Example production-style kiosk configuration |
| `config_debug_single_screen.toml` | Example debug/development configuration |
| `requirements.txt` | Python package dependencies |
| `beep.wav` | Countdown sound |
| `camera_shutter.wav` | Shutter sound |
| `look_at_camera.wav` | Spoken instructions played before image capture |
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
* `ldap3`

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
* `[ldap]` — user identification and directory lookup
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

## Card Reader Support

The kiosk supports two common keyboard-emulating card reader formats.

### Magnetic Stripe Reader

Example Track 2 input:

```text
;514006534=0047?
```

The kiosk automatically extracts the configured 9-digit identifier.

### ELATEC Tap Reader

Example input:

```text
5140065340
```

The kiosk automatically removes the trailing digit and extracts the
configured 9-digit identifier.

No reader-specific configuration is required.

### Debug Mode

For development and testing, the `u` key can be used to simulate card
presentation using the value configured in:

```toml
debug_card_input = ";000000000=0000?"
```

## Output Images

Accepted images are saved to:

```text
headshots/
```

Each accepted image filename includes the user's username and a timestamp:

```text
headshot_<username>_<timestamp>.jpg
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

When enabled, accepted images are attached to an email and delivered
through the configured SMTP server.

If LDAP integration is enabled, the image is automatically delivered to
the email address associated with the identified user. An optional BCC
recipient may also be configured for administrative record keeping.

## LDAP Integration

The kiosk can query a directory service after card presentation to
retrieve:

- Full name (`cn`)
- First name (`givenName`)
- Last name (`sn`)
- Username (`uid`)
- Email address (`mail`)

This information is used to:

- Personalize the user interface
- Generate username-based filenames
- Automatically address email delivery

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

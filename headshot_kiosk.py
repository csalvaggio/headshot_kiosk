#!/usr/bin/env python3

"""
Headshot Kiosk System
=====================

Dependencies
------------

This application requires several third-party Python packages in addition
to the Python standard library.

Required third-party packages:

    pip install opencv-python numpy Pillow pydantic email-validator ldap3

These provide:

    opencv-python   - Camera access and image processing (cv2)
    numpy           - Numerical array support
    Pillow          - Tkinter-compatible image handling
    pydantic        - Data validation and typed configuration models
    email-validator - Validation backend required by pydantic.EmailStr
    ldap3           - LDAP directory queries for user account information

Python Version Requirements
---------------------------

This application requires Python 3.11 or newer because it utilizes:

    enum.StrEnum

Architecture / Platform Notes
-----------------------------

tkinter
~~~~~~~

The tkinter GUI toolkit is part of the standard Python library, but some
platforms distribute it separately from the base interpreter.

Linux (Debian / Ubuntu / Raspberry Pi OS):

    sudo apt install python3-tk

macOS
~~~~

If using the official Python.org installer, tkinter is usually included.

If using Homebrew Python, tkinter support may require:

    brew install python-tk

OpenCV (cv2)
~~~~~~~~~~~

The OpenCV package may have additional native dependencies depending on
platform and camera backend support.

Linux systems may require:

    sudo apt install libopencv-dev

Camera Device Access
~~~~~~~~~~~~~~~~~~~

Linux:
    Cameras are typically exposed as:

        /dev/video0
        /dev/video1
        ...

    The executing user may need membership in the "video" group.

macOS:
    The application may require camera permissions under:

        System Settings -> Privacy & Security -> Camera

Wayland / X11 Notes
~~~~~~~~~~~~~~~~~~

Some Linux desktop environments using Wayland may exhibit differences in
camera access or Tkinter window behavior compared to X11.

Raspberry Pi Notes
~~~~~~~~~~~~~~~~~

On Raspberry Pi OS Bookworm, camera compatibility can vary depending on:

    - USB camera chipset
    - V4L2 support
    - MJPG vs. YUYV modes
    - Available USB bandwidth

Testing camera operation with v4l2-ctl before running the application is
recommended.

Example:

    v4l2-ctl --list-formats-ext

Recommended Virtual Environment Setup
-------------------------------------

Creating an isolated Python virtual environment is strongly recommended:

    python3 -m venv venv
    source venv/bin/activate

    pip install --upgrade pip
    pip install opencv-python numpy Pillow pydantic email-validator ldap3
"""

from __future__ import annotations

import argparse
import platform
import re
import smtplib
import subprocess
import time
import tkinter as tk
import tomllib
from datetime import datetime
from email.message import EmailMessage
from enum import StrEnum
from ldap3 import Server, Connection, ALL
from ldap3.core.exceptions import LDAPException
from pathlib import Path
from typing import Any, Callable, Literal

import cv2
import numpy as np
from PIL import Image, ImageTk
from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    computed_field,
    field_validator,
)


SCRIPT_DIR = Path(__file__).resolve().parent


class KioskState(StrEnum):
    IDLE = "idle"
    PREVIEW = "preview"
    COUNTDOWN = "countdown"
    REVIEW = "review"
    SHUTDOWN_AUTH = "shutdown_auth"


class WindowConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    debug_single_screen_mode: bool
    debug_touchscreen_geometry: str
    debug_preview_geometry: str
    touchscreen_geometry: str
    preview_geometry: str


class CameraConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    index: int
    width: int
    height: int
    fps: int


class ImageTransformConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    rotation_degrees: Literal[0, 90, 180, 270]
    mirror_horizontally: bool


class EyeCropConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    enabled: bool
    model_path: Path
    detection_width: int
    desired_eye_y_fraction: float
    min_score: float
    smoothing_alpha_small: float
    smoothing_alpha_large: float
    large_motion_threshold: float
    crop_deadband: int


class EmailConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    enabled: bool
    to_address: EmailStr
    bcc_address: EmailStr | None = None
    from_address: EmailStr
    smtp_server: str
    smtp_port: int

    @field_validator("bcc_address", mode="before")
    @classmethod
    def empty_bcc_address_to_none(cls, value: object) -> object:
        if value == "":
            return None
        return value


class LdapConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    enabled: bool
    server: str
    port: int
    use_ssl: bool
    bind_dn: str
    password: str
    search_base: str
    id_attribute: str
    attributes: list[str]
    debug_first_name: str
    debug_username: str
    debug_email: EmailStr


class ShutdownConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    enabled: bool
    authorized_usernames: list[str]
    command: tuple[str, ...]


class UserRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    rit_id: str
    mail: str | None = None
    cn: str | None = None
    sn: str | None = None
    uid: str | None = None
    given_name: str | None = None

    @property
    def first_name(self) -> str:
        return self.given_name or ""

    @property
    def username(self) -> str:
        return self.uid or self.rit_id

    @property
    def email_address(self) -> str | None:
        return self.mail


class UiConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    background_color: str
    foreground_color: str
    font_family: str
    message_font_size: int
    button_font_size: int
    button_width: int
    button_height: int
    button_border_width: int
    message_wraplength: int
    message_padx: int
    message_pady_top: int
    message_pady_bottom: int
    button_frame_pady: int
    button_pady: int


class TextConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    control_window_title: str
    preview_window_title: str
    idle_message: str
    preview_message: str
    camera_error_message: str
    review_message: str
    no_image_message: str
    save_error_message: str
    submitted_message: str
    saved_message: str
    take_photo_button: str
    accept_button: str
    retake_button: str
    cancel_button: str
    email_subject: str
    email_body_intro: str
    shutdown_button: str
    shutdown_prompt_message: str
    shutdown_denied_message: str
    shutdown_authorized_message: str


class ColorConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    take_photo_button: str
    accept_button: str
    retake_button: str
    cancel_button: str
    flash_overlay: str


class HeadshotConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    window: WindowConfig
    camera: CameraConfig
    image_transform: ImageTransformConfig
    eye_crop: EyeCropConfig
    email: EmailConfig
    ldap: LdapConfig
    shutdown: ShutdownConfig
    ui: UiConfig
    text: TextConfig
    colors: ColorConfig

    scale_preview_to_fit: bool
    square_output: bool
    countdown_seconds: int
    preview_countdown_hide_last_n_seconds: int
    preview_countdown_font_size: int
    countdown_beep_enabled: bool
    countdown_sound_file: str
    shutter_sound_file: str
    instruction_sound_file: str
    flash_duration_ms: int
    video_update_interval_ms: int
    countdown_update_interval_ms: int
    camera_error_retry_ms: int
    no_image_retry_ms: int
    save_error_reset_ms: int
    post_accept_reset_ms: int

    uid_length: int
    debug_card_input: str

    shutdown_grace_period_ms: int
    shutdown_authorization_timeout_ms: int

    output_dir: Path

    @computed_field
    @property
    def accepted_dir(self) -> Path:
        return self.output_dir


class HeadshotKiosk:
    def __init__(self, control_window: tk.Tk, config: HeadshotConfig) -> None:
        self.config = config
        self.control_window = control_window
        self.preview_window: tk.Toplevel | None = None

        self.state: KioskState = KioskState.IDLE
        self.cap: cv2.VideoCapture | None = None
        self.current_frame: np.ndarray | None = None
        self.captured_frame: np.ndarray | None = None

        self.eye_detector: cv2.FaceDetectorYN | None = None
        self.eye_detector_input_size: tuple[int, int] | None = None
        self.smoothed_eye_y: float | None = None
        self.displayed_crop_top: int | None = None

        self.current_uid: str | None = None
        self.current_user: UserRecord | None = None
        self.uid_buffer: str = ""
        self.countdown_start: float = 0.0
        self.last_beep_remaining: int | None = None

        self.preview_image_x: int = 0
        self.preview_image_y: int = 0
        self.preview_image_width: int = 1
        self.preview_image_height: int = 1

        self.video_label: tk.Label | None = None
        self.message_label: tk.Label | None = None
        self.button_frame: tk.Frame | None = None
        self.preview_countdown_label: tk.Label | None = None
        self.flash_overlay: tk.Frame | None = None

        self.shutdown_button: tk.Button | None = None
        self.pending_shutdown_after_id: str | None = None
        self.shutdown_authorization_after_id: str | None = None

        self.config.accepted_dir.mkdir(parents=True, exist_ok=True)

        self.setup_windows()
        self.setup_camera()
        self.setup_widgets()

        self.set_idle_state()
        self.update_video()

        self.control_window.focus_force()

    def setup_windows(self) -> None:
        self.control_window.configure(bg=self.config.ui.background_color)
        self.control_window.title(self.config.text.control_window_title)

        if self.config.window.debug_single_screen_mode:
            self.control_window.geometry(
                self.config.window.debug_touchscreen_geometry
            )
        else:
            self.control_window.geometry(self.config.window.touchscreen_geometry)
            self.control_window.attributes("-fullscreen", True)

        self.preview_window = tk.Toplevel(self.control_window)
        self.preview_window.configure(bg=self.config.ui.background_color)
        self.preview_window.title(self.config.text.preview_window_title)

        if self.config.window.debug_single_screen_mode:
            self.preview_window.geometry(self.config.window.debug_preview_geometry)
        else:
            self.preview_window.geometry(self.config.window.preview_geometry)
            self.preview_window.attributes("-fullscreen", True)

        self.control_window.bind("<Escape>", lambda _event: self.quit())
        self.preview_window.bind("<Escape>", lambda _event: self.quit())

        self.control_window.bind("<Key>", self.handle_keypress)
        self.preview_window.bind("<Key>", self.handle_keypress)

    def setup_camera(self) -> None:
        camera = self.config.camera
        system = platform.system()

        if system == "Linux":
            self.cap = cv2.VideoCapture(camera.index, cv2.CAP_V4L2)
            self.cap.set(
                cv2.CAP_PROP_FOURCC,
                cv2.VideoWriter_fourcc(*"MJPG"),
            )
        elif system == "Darwin":
            self.cap = cv2.VideoCapture(camera.index, cv2.CAP_AVFOUNDATION)
        else:
            self.cap = cv2.VideoCapture(camera.index)

        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, camera.width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, camera.height)
        self.cap.set(cv2.CAP_PROP_FPS, camera.fps)

        if not self.cap.isOpened():
            raise RuntimeError(f"Could not open camera index {camera.index}")

    def setup_widgets(self) -> None:
        assert self.preview_window is not None

        self.video_label = tk.Label(
            self.preview_window,
            bg=self.config.ui.background_color,
        )

        self.preview_countdown_label = tk.Label(
            self.preview_window,
            text="",
            font=(
                self.config.ui.font_family,
                self.config.preview_countdown_font_size,
                "bold",
            ),
            fg=self.config.ui.foreground_color,
            bg=self.config.ui.background_color,
            anchor="center",
            justify="center",
            padx=self.config.preview_countdown_font_size // 2,
            pady=self.config.preview_countdown_font_size // 4,
        )

        self.message_label = tk.Label(
            self.control_window,
            text=self.config.text.idle_message,
            font=(
                self.config.ui.font_family,
                self.config.ui.message_font_size,
                "bold",
            ),
            fg=self.config.ui.foreground_color,
            bg=self.config.ui.background_color,
            wraplength=self.config.ui.message_wraplength,
            justify="center",
        )
        self.message_label.pack(
            fill=tk.X,
            padx=self.config.ui.message_padx,
            pady=(
                self.config.ui.message_pady_top,
                self.config.ui.message_pady_bottom,
            ),
            anchor="n",
        )

        self.button_frame = tk.Frame(
            self.control_window,
            bg=self.config.ui.background_color,
        )
        self.button_frame.pack(pady=self.config.ui.button_frame_pady)

        self.shutdown_button = tk.Button(
            self.control_window,
            text=self.config.text.shutdown_button,
            command=self.start_shutdown_authorization,
            font=(
                self.config.ui.font_family,
                max(10, self.config.ui.button_font_size // 2),
                "bold",
            ),
            fg=self.config.ui.foreground_color,
            bg=self.config.colors.cancel_button,
            activebackground=self.config.colors.cancel_button,
            activeforeground=self.config.ui.foreground_color,
            bd=2,
        )

    def show_shutdown_button(self) -> None:
        if (
            self.shutdown_button is not None
            and self.config.shutdown.enabled
        ):
            self.shutdown_button.place(
                relx=1.0,
                rely=1.0,
                x=-20,
                y=-40,
                anchor="se",
            )

    def hide_shutdown_button(self) -> None:
        if self.shutdown_button is not None:
            self.shutdown_button.place_forget()

    def shutdown_authorization_timeout(self) -> None:
        self.shutdown_authorization_after_id = None

        if self.state is KioskState.SHUTDOWN_AUTH:
            self.set_idle_state()

    def start_shutdown_authorization(self) -> None:
        assert self.message_label is not None
        assert self.preview_countdown_label is not None

        self.state = KioskState.SHUTDOWN_AUTH
        self.uid_buffer = ""
        self.current_uid = None
        self.current_user = None
        self.captured_frame = None
        self.reset_eye_crop_state()

        self.preview_countdown_label.place_forget()
        self.clear_buttons()
        self.hide_shutdown_button()

        self.message_label.config(
            text=self.config.text.shutdown_prompt_message
        )

        self.make_button(
            self.config.text.cancel_button,
            self.set_idle_state,
            self.config.colors.cancel_button,
        ).pack(pady=self.config.ui.button_pady)

        self.control_window.focus_force()

        self.shutdown_authorization_after_id = (
            self.control_window.after(
                self.config.shutdown_authorization_timeout_ms,
                self.shutdown_authorization_timeout,
            )
        )

    def authorize_shutdown_uid(self, uid: str) -> None:
        if self.shutdown_authorization_after_id is not None:
            self.control_window.after_cancel(
                self.shutdown_authorization_after_id
            )
            self.shutdown_authorization_after_id = None

        assert self.message_label is not None

        user = self.lookup_user_record(uid)
        username = user.username

        authorized_usernames = {
            name.lower()
            for name in self.config.shutdown.authorized_usernames
        }

        if username.lower() in authorized_usernames:
            self.message_label.config(
                text=self.config.text.shutdown_authorized_message
            )

            self.clear_buttons()

            self.make_button(
                self.config.text.cancel_button,
                self.cancel_pending_shutdown,
                self.config.colors.cancel_button,
            ).pack(pady=self.config.ui.button_pady)

            self.pending_shutdown_after_id = self.control_window.after(
                self.config.shutdown_grace_period_ms,
                self.shutdown_system,
            )
            return

        self.clear_buttons()

        self.message_label.config(
            text=self.config.text.shutdown_denied_message
        )

        self.control_window.after(
            self.config.post_accept_reset_ms,
            self.set_idle_state,
        )

    def cancel_pending_shutdown(self) -> None:
        if self.pending_shutdown_after_id is not None:
            self.control_window.after_cancel(
                self.pending_shutdown_after_id
            )
            self.pending_shutdown_after_id = None

        self.set_idle_state()

    def shutdown_system(self) -> None:
        self.pending_shutdown_after_id = None

        try:
            subprocess.Popen(self.config.shutdown.command)
        except OSError as exc:
            print(f"Shutdown failed: {exc}")
            self.set_idle_state()

    def resolve_sound_path(self, sound_file: str) -> Path:
        path = Path(sound_file)

        if path.is_absolute():
            return path

        return SCRIPT_DIR / path

    def build_sound_command(self, sound_file: str) -> tuple[str, ...]:
        sound_path = self.resolve_sound_path(sound_file)
        system = platform.system()

        if system == "Darwin":
            return ("afplay", str(sound_path))

        return ("aplay", str(sound_path))

    def extract_uid_from_card_input(self, raw_input: str) -> str | None:
        raw_input = raw_input.strip()

        swipe_match = re.search(
            rf";(\d{{{self.config.uid_length}}})=\d+\?",
            raw_input,
        )
        if swipe_match is not None:
            return swipe_match.group(1)

        tap_match = re.fullmatch(
            rf"(\d{{{self.config.uid_length}}})0",
            raw_input,
        )
        if tap_match is not None:
            return tap_match.group(1)

        return None

    def handle_keypress(self, event: Any) -> None:
        if event.keysym == "Escape":
            self.quit()
            return

        if self.state is KioskState.SHUTDOWN_AUTH:
            if isinstance(event.char, str) and event.char:
                if event.char not in "0123456789;=?":
                    return

                self.uid_buffer += event.char

                uid = self.extract_uid_from_card_input(self.uid_buffer)

                if uid is not None:
                    self.uid_buffer = ""
                    self.authorize_shutdown_uid(uid)
                    return

                if len(self.uid_buffer) > self.config.uid_length + 8:
                    self.uid_buffer = ""

            elif event.keysym in {"Return", "KP_Enter"}:
                uid = self.extract_uid_from_card_input(self.uid_buffer)
                self.uid_buffer = ""

                if uid is not None:
                    self.authorize_shutdown_uid(uid)

            return

        if (
            self.state is KioskState.IDLE
            and isinstance(event.char, str)
            and event.char.lower() == "u"
        ):
            uid = self.extract_uid_from_card_input(
                self.config.debug_card_input
            )

            if uid is not None:
                self.start_session_with_uid(uid)

            return

        if self.state is not KioskState.IDLE:
            return

        if isinstance(event.char, str) and event.char:
            self.uid_buffer += event.char

            uid = self.extract_uid_from_card_input(self.uid_buffer)

            if uid is not None:
                self.uid_buffer = ""
                self.start_session_with_uid(uid)
                return

            if len(self.uid_buffer) > self.config.uid_length + 8:
                self.uid_buffer = ""

        elif event.keysym in {"Return", "KP_Enter"}:
            uid = self.extract_uid_from_card_input(self.uid_buffer)
            self.uid_buffer = ""

            if uid is not None:
                self.start_session_with_uid(uid)
                return

    def lookup_user_record(self, rit_id: str) -> UserRecord:
        ldap = self.config.ldap

        debug_id = self.extract_uid_from_card_input(
            self.config.debug_card_input
        )

        if rit_id == debug_id:
            return UserRecord(
                rit_id=rit_id,
                mail=str(ldap.debug_email),
                cn=ldap.debug_first_name,
                uid=ldap.debug_username,
                given_name=ldap.debug_first_name,
                sn=None,
            )

        if not ldap.enabled:
            return UserRecord(rit_id=rit_id)

        server = Server(
            ldap.server,
            port=ldap.port,
            use_ssl=ldap.use_ssl,
            get_info=ALL,
        )

        search_filter = f"({ldap.id_attribute}={rit_id})"

        try:
            conn = Connection(
                server,
                user=ldap.bind_dn,
                password=ldap.password,
                auto_bind=True,
            )

            conn.search(
                search_base=ldap.search_base,
                search_filter=search_filter,
                attributes=ldap.attributes,
            )

            if not conn.entries:
                conn.unbind()
                return UserRecord(rit_id=rit_id)

            entry = conn.entries[0]

            record = UserRecord(
                rit_id=rit_id,
                mail=entry["mail"].value if "mail" in entry else None,
                cn=entry["cn"].value if "cn" in entry else None,
                sn=entry["sn"].value if "sn" in entry else None,
                uid=entry["uid"].value if "uid" in entry else None,
                given_name=(
                    entry["givenName"].value
                    if "givenName" in entry
                    else None
                ),
            )

            conn.unbind()
            return record

        except LDAPException as exc:
            print(f"LDAP lookup failed for {rit_id}: {exc}")
            return UserRecord(rit_id=rit_id)

    def start_session_with_uid(self, uid: str) -> None:
        self.current_uid = uid
        self.current_user = self.lookup_user_record(uid)
        self.uid_buffer = ""

        self.start_preview_state()

        if self.config.countdown_beep_enabled:
            self.control_window.after(100, self.prime_audio)

    def transform_frame(self, frame: np.ndarray) -> np.ndarray:
        transform = self.config.image_transform

        if transform.rotation_degrees == 90:
            frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
        elif transform.rotation_degrees == 180:
            frame = cv2.rotate(frame, cv2.ROTATE_180)
        elif transform.rotation_degrees == 270:
            frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)

        if transform.mirror_horizontally:
            frame = cv2.flip(frame, 1)

        return frame

    def center_square_crop(self, frame: np.ndarray) -> np.ndarray:
        height, width = frame.shape[:2]
        size = min(width, height)

        x0 = (width - size) // 2
        y0 = (height - size) // 2

        return frame[y0 : y0 + size, x0 : x0 + size]

    def reset_eye_crop_state(self) -> None:
        self.smoothed_eye_y = None
        self.displayed_crop_top = None

    def resolve_eye_model_path(self) -> Path:
        path = Path(self.config.eye_crop.model_path)

        if path.is_absolute():
            return path

        return SCRIPT_DIR / path

    def ensure_eye_detector(
        self,
        frame_width: int,
        frame_height: int,
    ) -> bool:
        eye_crop = self.config.eye_crop

        detection_width = min(
            eye_crop.detection_width,
            frame_width,
        )

        detection_scale = detection_width / frame_width
        detection_height = max(
            1,
            int(round(frame_height * detection_scale)),
        )

        input_size = (detection_width, detection_height)

        if (
            self.eye_detector is not None
            and self.eye_detector_input_size == input_size
        ):
            return True

        model_path = self.resolve_eye_model_path()

        if not model_path.exists():
            print(
                f"Eye crop disabled: missing YuNet model {model_path}"
            )
            self.eye_detector = None
            self.eye_detector_input_size = None
            return False

        self.eye_detector = cv2.FaceDetectorYN.create(
            str(model_path),
            "",
            input_size,
            score_threshold=eye_crop.min_score,
            nms_threshold=0.3,
            top_k=5000,
        )
        self.eye_detector_input_size = input_size

        return True

    def eye_square_crop(self, frame: np.ndarray) -> np.ndarray:
        eye_crop = self.config.eye_crop
        height, width = frame.shape[:2]
        crop_size = min(width, height)

        if not eye_crop.enabled:
            return self.center_square_crop(frame)

        if not self.ensure_eye_detector(width, height):
            return self.center_square_crop(frame)

        assert self.eye_detector is not None
        assert self.eye_detector_input_size is not None

        detection_width, detection_height = self.eye_detector_input_size
        detection_scale = detection_width / width

        detection_frame = cv2.resize(
            frame,
            (detection_width, detection_height),
            interpolation=cv2.INTER_LINEAR,
        )

        _, faces = self.eye_detector.detect(detection_frame)

        if faces is None:
            if self.displayed_crop_top is None:
                return self.center_square_crop(frame)

            crop_top = self.displayed_crop_top
            crop_top = max(
                0,
                min(crop_top, height - crop_size),
            )

            return frame[
                crop_top : crop_top + crop_size,
                0:crop_size,
            ]

        face = max(
            faces,
            key=lambda f: f[2] * f[3],
        )

        right_eye = face[4:6]
        left_eye = face[6:8]

        eye_y_detection = (
            right_eye[1] + left_eye[1]
        ) / 2.0

        current_eye_y = eye_y_detection / detection_scale

        if self.smoothed_eye_y is None:
            self.smoothed_eye_y = current_eye_y

        delta = abs(current_eye_y - self.smoothed_eye_y)

        if delta > eye_crop.large_motion_threshold:
            alpha = eye_crop.smoothing_alpha_large
        else:
            alpha = eye_crop.smoothing_alpha_small

        self.smoothed_eye_y = (
            alpha * current_eye_y
            + (1.0 - alpha) * self.smoothed_eye_y
        )

        desired_eye_y = (
            eye_crop.desired_eye_y_fraction * crop_size
        )

        new_crop_top = int(round(
            self.smoothed_eye_y - desired_eye_y
        ))

        new_crop_top = max(
            0,
            min(new_crop_top, height - crop_size),
        )

        if self.displayed_crop_top is None:
            self.displayed_crop_top = new_crop_top

        if abs(new_crop_top - self.displayed_crop_top) > eye_crop.crop_deadband:
            self.displayed_crop_top = new_crop_top

        return frame[
            self.displayed_crop_top:
            self.displayed_crop_top + crop_size,
            0:crop_size,
        ]

    def resize_image_to_fit(
        self,
        image: Image.Image,
        target_width: int,
        target_height: int,
    ) -> Image.Image:
        image_width, image_height = image.size

        scale = min(
            target_width / image_width,
            target_height / image_height,
        )

        new_width = max(1, int(image_width * scale))
        new_height = max(1, int(image_height * scale))

        return image.resize(
            (new_width, new_height),
            Image.Resampling.LANCZOS,
        )

    def clear_buttons(self) -> None:
        assert self.button_frame is not None

        for widget in self.button_frame.winfo_children():
            widget.destroy()

    def make_button(
        self,
        text: str,
        command: Callable[[], None],
        color: str,
    ) -> tk.Button:
        assert self.button_frame is not None

        return tk.Button(
            self.button_frame,
            text=text,
            command=command,
            font=(
                self.config.ui.font_family,
                self.config.ui.button_font_size,
                "bold",
            ),
            fg=self.config.ui.foreground_color,
            bg=color,
            activebackground=color,
            activeforeground=self.config.ui.foreground_color,
            width=self.config.ui.button_width,
            height=self.config.ui.button_height,
            bd=self.config.ui.button_border_width,
        )

    def set_idle_state(self) -> None:
        assert self.message_label is not None
        assert self.preview_countdown_label is not None

        if self.shutdown_authorization_after_id is not None:
            self.control_window.after_cancel(
                self.shutdown_authorization_after_id
            )
            self.shutdown_authorization_after_id = None

        self.state = KioskState.IDLE
        self.current_uid = None
        self.uid_buffer = ""
        self.current_user = None
        self.captured_frame = None
        self.reset_eye_crop_state()

        self.preview_countdown_label.place_forget()
        self.message_label.config(text=self.config.text.idle_message)

        self.clear_buttons()
        self.show_shutdown_button()

    def start_preview_state(self) -> None:
        assert self.message_label is not None
        assert self.preview_countdown_label is not None

        self.state = KioskState.PREVIEW
        self.captured_frame = None
        self.reset_eye_crop_state()
        self.hide_shutdown_button()

        self.preview_countdown_label.place_forget()

        first_name = (
            self.current_user.first_name
            if self.current_user is not None
            else ""
        )

        message = self.config.text.preview_message

        if first_name:
            message = (
                f"Hi\n{first_name}\n\n"
                f"{message}"
            )

        self.message_label.config(text=message)

        self.clear_buttons()

        self.make_button(
            self.config.text.take_photo_button,
            self.play_instruction_sound_then_countdown,
            self.config.colors.take_photo_button,
        ).pack(pady=self.config.ui.button_pady)

        self.make_button(
            self.config.text.cancel_button,
            self.set_idle_state,
            self.config.colors.cancel_button,
        ).pack(pady=self.config.ui.button_pady)

    def play_instruction_sound_then_countdown(self) -> None:
        command = self.build_sound_command(
            self.config.instruction_sound_file
        )

        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            self.start_countdown_state()
            return

        self.wait_for_instruction_sound(process)

    def wait_for_instruction_sound(
        self,
        process: subprocess.Popen[Any],
    ) -> None:
        if process.poll() is None:
            self.control_window.after(
                100,
                lambda: self.wait_for_instruction_sound(process),
            )
            return

        self.start_countdown_state()

    def start_countdown_state(self) -> None:
        self.state = KioskState.COUNTDOWN
        self.clear_buttons()
        self.hide_shutdown_button()
        self.countdown_start = time.monotonic()
        self.last_beep_remaining = None
        self.run_countdown()

    def run_countdown(self) -> None:
        assert self.message_label is not None
        assert self.preview_countdown_label is not None

        elapsed = time.monotonic() - self.countdown_start
        remaining = self.config.countdown_seconds - int(elapsed)

        if remaining > 0:
            text = str(remaining)

            if (
                self.config.countdown_beep_enabled
                and remaining != self.last_beep_remaining
            ):
                self.play_countdown_sound()
                self.last_beep_remaining = remaining

            self.message_label.config(text=text)

            center_x = self.preview_image_x + self.preview_image_width // 2
            center_y = self.preview_image_y + self.preview_image_height // 2

            if remaining > self.config.preview_countdown_hide_last_n_seconds:
                self.preview_countdown_label.config(text=text)
                self.preview_countdown_label.place(
                    x=center_x,
                    y=center_y,
                    anchor="center",
                )
                self.preview_countdown_label.lift()
            else:
                self.preview_countdown_label.place_forget()

            self.control_window.after(
                self.config.countdown_update_interval_ms,
                self.run_countdown,
            )
        else:
            self.preview_countdown_label.place_forget()
            self.capture_image()

    def flash_preview(self) -> None:
        assert self.preview_window is not None

        if self.flash_overlay is not None:
            self.flash_overlay.destroy()

        self.flash_overlay = tk.Frame(
            self.preview_window,
            bg=self.config.colors.flash_overlay,
        )
        self.flash_overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.flash_overlay.lift()

        self.preview_window.after(
            self.config.flash_duration_ms,
            self.clear_flash,
        )

    def clear_flash(self) -> None:
        if self.flash_overlay is not None:
            self.flash_overlay.destroy()
            self.flash_overlay = None

    def capture_image(self) -> None:
        assert self.message_label is not None

        if self.current_frame is None:
            self.message_label.config(text=self.config.text.camera_error_message)
            self.control_window.after(
                self.config.camera_error_retry_ms,
                self.start_preview_state,
            )
            return

        self.hide_shutdown_button()
        self.flash_preview()
        self.play_shutter_sound()

        self.captured_frame = self.current_frame.copy()

        self.state = KioskState.REVIEW

        self.message_label.config(text=self.config.text.review_message)
        self.clear_buttons()

        self.make_button(
            self.config.text.accept_button,
            self.accept_image,
            self.config.colors.accept_button,
        ).pack(pady=self.config.ui.button_pady)

        self.make_button(
            self.config.text.retake_button,
            self.start_preview_state,
            self.config.colors.retake_button,
        ).pack(pady=self.config.ui.button_pady)

        self.make_button(
            self.config.text.cancel_button,
            self.set_idle_state,
            self.config.colors.cancel_button,
        ).pack(pady=self.config.ui.button_pady)

    def accept_image(self) -> None:
        assert self.message_label is not None

        if self.captured_frame is None:
            self.message_label.config(text=self.config.text.no_image_message)
            self.control_window.after(
                self.config.no_image_retry_ms,
                self.start_preview_state,
            )
            return

        timestamp = datetime.now().astimezone().strftime("%Y-%m-%dT%H%M%S%z")

        username = (
            self.current_user.username
            if self.current_user is not None
            else self.current_uid or "unknown"
        )

        image_path = self.config.accepted_dir / f"{timestamp}_{username}.jpg"

        success = cv2.imwrite(str(image_path), self.captured_frame)

        if not success:
            self.message_label.config(text=self.config.text.save_error_message)
            self.control_window.after(
                self.config.save_error_reset_ms,
                self.set_idle_state,
            )
            return

        if self.config.email.enabled:
            try:
                self.email_image(image_path)
                self.message_label.config(
                    text=self.config.text.submitted_message
                )
            except Exception as exc:
                self.message_label.config(
                    text=f"Saved, but email failed:\n{exc}"
                )
        else:
            self.message_label.config(text=self.config.text.saved_message)

        self.clear_buttons()
        self.control_window.after(
            self.config.post_accept_reset_ms,
            self.set_idle_state,
        )

    def email_image(self, image_path: Path) -> None:
        email = self.config.email

        uid = self.current_uid or "unknown"

        username = (
            self.current_user.username
            if self.current_user is not None
            else uid
        )

        recipient = (
            self.current_user.email_address
            if (
                self.current_user is not None
                and self.current_user.email_address is not None
            )
            else str(email.to_address)
        )

        full_name = (
            self.current_user.cn
            if (
                self.current_user is not None
                and self.current_user.cn is not None
            )
            else "Unknown"
        )

        msg = EmailMessage()
        msg["Subject"] = self.config.text.email_subject
        msg["From"] = str(email.from_address)
        msg["To"] = recipient
        if email.bcc_address is not None:
            msg["Bcc"] = str(email.bcc_address)

        msg.set_content(
            f"{self.config.text.email_body_intro}\n\n"
            f"Name: {full_name}\n"
            f"Username: {username}\n"
            f"UID: {uid}\n"
            f"File: {image_path.name}\n\n"
        )

        with image_path.open("rb") as f:
            msg.add_attachment(
                f.read(),
                maintype="image",
                subtype="jpeg",
                filename=image_path.name,
            )

        with smtplib.SMTP(email.smtp_server, email.smtp_port) as smtp:
            smtp.send_message(msg)

    def update_video(self) -> None:
        assert self.cap is not None
        assert self.video_label is not None
        assert self.preview_window is not None

        ret, frame = self.cap.read()

        if ret:
            frame = self.transform_frame(frame)

            if self.config.square_output:
                frame = self.eye_square_crop(frame)

            self.current_frame = frame

            if (
                self.state is KioskState.REVIEW
                and self.captured_frame is not None
            ):
                display_frame = self.captured_frame
            else:
                display_frame = frame

            rgb_frame = cv2.cvtColor(display_frame, cv2.COLOR_BGR2RGB)
            image = Image.fromarray(rgb_frame)

            preview_w = max(1, self.preview_window.winfo_width())
            preview_h = max(1, self.preview_window.winfo_height())

            if self.config.scale_preview_to_fit:
                image = self.resize_image_to_fit(image, preview_w, preview_h)

            photo = ImageTk.PhotoImage(image=image)
            image_width = image.width
            image_height = image.height

            x = max(0, (preview_w - image_width) // 2)
            y = 0

            self.preview_image_x = x
            self.preview_image_y = y
            self.preview_image_width = image_width
            self.preview_image_height = image_height

            self.video_label.place(
                x=x,
                y=y,
                width=image_width,
                height=image_height,
            )

            self.video_label.configure(image=photo)
            self.video_label.image = photo

        self.control_window.after(
            self.config.video_update_interval_ms,
            self.update_video,
        )

    def prime_audio(self, silent: bool = True) -> None:
        if not self.config.countdown_beep_enabled:
            return

        try:
            system = platform.system()

            if silent and system == "Darwin":
                sound_path = self.resolve_sound_path(
                    self.config.countdown_sound_file
                )
                command = (
                    "afplay",
                    "-v",
                    "0",
                    str(sound_path),
                )
            else:
                command = self.build_sound_command(
                    self.config.countdown_sound_file
                )

            subprocess.run(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=2.0,
            )

        except (OSError, subprocess.TimeoutExpired):
            pass

    def play_countdown_sound(self) -> None:
        try:
            subprocess.Popen(
                self.build_sound_command(self.config.countdown_sound_file),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            self.control_window.bell()

    def play_shutter_sound(self) -> None:
        try:
            subprocess.Popen(
                self.build_sound_command(self.config.shutter_sound_file),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            pass

    def quit(self) -> None:
        if self.cap is not None:
            self.cap.release()

        self.control_window.destroy()


def load_config(config_path: Path) -> HeadshotConfig:
    with config_path.open("rb") as f:
        config_data = tomllib.load(f)

    return HeadshotConfig.model_validate(config_data)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the headshot kiosk application. All operational "
            "configuration is read from TOML."
        ),
    )
    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        required=True,
        help="Path to a complete TOML configuration file.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    root = tk.Tk()

    HeadshotKiosk(root, config)

    root.mainloop()


if __name__ == "__main__":
    main()

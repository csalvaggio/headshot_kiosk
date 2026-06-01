#!/usr/bin/env python3

"""
Headshot Kiosk System
=====================

Dependencies
------------

This application requires several third-party Python packages in addition
to the Python standard library.

Required third-party packages:

    pip install opencv-python numpy Pillow pydantic email-validator

These provide:

    opencv-python   - Camera access and image processing (cv2)
    numpy           - Numerical array support
    Pillow          - Tkinter-compatible image handling
    pydantic        - Data validation and typed configuration models
    email-validator - Validation backend required by pydantic.EmailStr

Python Version Requirements
---------------------------

This application requires Python 3.11 or newer because it utilizes:

    enum.StrEnum

Architecture / Platform Notes
-----------------------------

tkinter
~~~~~~~~

The tkinter GUI toolkit is part of the standard Python library, but some
platforms distribute it separately from the base interpreter.

Linux (Debian / Ubuntu / Raspberry Pi OS):

    sudo apt install python3-tk

macOS
~~~~~

If using the official Python.org installer, tkinter is usually included.

If using Homebrew Python, tkinter support may require:

    brew install python-tk

OpenCV (cv2)
~~~~~~~~~~~~

The OpenCV package may have additional native dependencies depending on
platform and camera backend support.

Linux systems may require:

    sudo apt install libopencv-dev

Camera Device Access
~~~~~~~~~~~~~~~~~~~~

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
~~~~~~~~~~~~~~~~~~~

Some Linux desktop environments using Wayland may exhibit differences in
camera access or Tkinter window behavior compared to X11.

Raspberry Pi Notes
~~~~~~~~~~~~~~~~~~

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
    pip install opencv-python numpy Pillow pydantic email-validator
"""

from __future__ import annotations

import re
import smtplib
import time
import platform
import tkinter as tk
from datetime import datetime
from email.message import EmailMessage
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable, Literal

import cv2
import numpy as np
from PIL import Image, ImageTk
from pydantic import BaseModel, ConfigDict, EmailStr, Field, computed_field


class KioskState(StrEnum):
    IDLE = "idle"
    PREVIEW = "preview"
    COUNTDOWN = "countdown"
    REVIEW = "review"


class WindowConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    debug_single_screen: bool = False
    debug_touchscreen_geometry: str = "500x700+50+50"
    debug_preview_geometry: str = "960x540+600+50"
    touchscreen_geometry: str = "600x1024+2160+1491"
    preview_geometry: str = "2160x3840+0+0"


class CameraConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    index: int = 0
    width: int = 1920
    height: int = 1080
    fps: int = 30


class ImageTransformConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    rotation_degrees: Literal[0, 90, 180, 270] = 270
    mirror: bool = True


class EmailConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    enabled: bool = False
    to_address: EmailStr = "cnspci@rit.edu"
    from_address: EmailStr = "cnspci@rit.edu"
    smtp_server: str = "mail.cis.rit.edu"
    smtp_port: int = 25


class HeadshotConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    window: WindowConfig = Field(default_factory=WindowConfig)
    camera: CameraConfig = Field(default_factory=CameraConfig)
    image_transform: ImageTransformConfig = Field(
        default_factory=ImageTransformConfig
    )
    email: EmailConfig = Field(default_factory=EmailConfig)

    scale_preview_to_fit: bool = False
    square_output: bool = True
    countdown_seconds: int = 5
    preview_countdown_hide_last_n_seconds: int = 2
    preview_countdown_font_size: int = 260
    countdown_beep_enabled: bool = True
    flash_duration_ms: int = 150

    uid_length: int = 9
    debug_card_swipe: str = ";000000000=0000?"

    output_dir: Path = Path.cwd() / "headshots"

    @computed_field
    @property
    def accepted_dir(self) -> Path:
        return self.output_dir / "accepted"


class HeadshotKiosk:
    def __init__(self, control_window: tk.Tk, config: HeadshotConfig) -> None:
        self.config = config
        self.control_window = control_window
        self.preview_window: tk.Toplevel | None = None

        self.state: KioskState = KioskState.IDLE
        self.cap: cv2.VideoCapture | None = None
        self.current_frame: np.ndarray | None = None
        self.captured_frame: np.ndarray | None = None

        self.current_uid: str | None = None
        self.uid_buffer: str = ""
        self.countdown_start: float = 0.0
        self.last_beep_remaining: int | None = None

        self.video_label: tk.Label | None = None
        self.message_label: tk.Label | None = None
        self.button_frame: tk.Frame | None = None
        self.preview_countdown_label: tk.Label | None = None
        self.flash_overlay: tk.Frame | None = None

        self.config.accepted_dir.mkdir(parents=True, exist_ok=True)

        self.setup_windows()
        self.setup_camera()
        self.setup_widgets()

        self.set_idle_state()
        self.update_video()

        self.control_window.focus_force()

    def setup_windows(self) -> None:
        self.control_window.configure(bg="black")
        self.control_window.title("Headshot Controls")

        if self.config.window.debug_single_screen:
            self.control_window.geometry(
                self.config.window.debug_touchscreen_geometry
            )
        else:
            self.control_window.geometry(
                    self.config.window.touchscreen_geometry)
            self.control_window.attributes("-fullscreen", True)

        self.preview_window = tk.Toplevel(self.control_window)
        self.preview_window.configure(bg="black")
        self.preview_window.title("Headshot Preview")

        if self.config.window.debug_single_screen:
            self.preview_window.geometry(
                    self.config.window.debug_preview_geometry)
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
            self.cap = cv2.VideoCapture(
                camera.index,
                cv2.CAP_V4L2,
            )

            self.cap.set(
                cv2.CAP_PROP_FOURCC,
                cv2.VideoWriter_fourcc(*"MJPG"),
            )
        elif system == "Darwin":
            self.cap = cv2.VideoCapture(
                camera.index,
                cv2.CAP_AVFOUNDATION,
            )
        else:
            self.cap = cv2.VideoCapture(camera.index)

        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, camera.width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, camera.height)
        self.cap.set(cv2.CAP_PROP_FPS, camera.fps)

        if not self.cap.isOpened():
            raise RuntimeError(f"Could not open camera index {camera.index}.")

    def setup_widgets(self) -> None:
        assert self.preview_window is not None

        self.video_label = tk.Label(self.preview_window, bg="black")

        self.preview_countdown_label = tk.Label(
            self.preview_window,
            text="",
            font=(
                "Helvetica",
                self.config.preview_countdown_font_size,
                "bold",
            ),
            fg="white",
            bg="black",
            anchor="center",
            justify="center",
            padx=self.config.preview_countdown_font_size // 2,
            pady=self.config.preview_countdown_font_size // 4,
        )

        self.message_label = tk.Label(
            self.control_window,
            text="Swipe ID Card\nto Begin",
            font=("Helvetica", 34, "bold"),
            fg="white",
            bg="black",
            wraplength=430,
            justify="center",
        )
        self.message_label.pack(
            fill=tk.X,
            padx=20,
            pady=(60, 20),
            anchor="n",
        )

        self.button_frame = tk.Frame(self.control_window, bg="black")
        self.button_frame.pack(pady=20)

    def extract_uid_from_card_swipe(self, raw_swipe: str) -> str | None:
        match = re.search(r";(\d{9})=", raw_swipe)

        if match is None:
            return None

        return match.group(1)

    def handle_keypress(self, event: Any) -> None:
        if event.keysym == "Escape":
            self.quit()
            return

        if (
            isinstance(event.char, str)
            and event.char.lower() == "u"
        ):
            uid = self.extract_uid_from_card_swipe(self.config.debug_card_swipe)

            if uid is not None:
                self.start_session_with_uid(uid)

            return

        if self.state is not KioskState.IDLE:
            return

        if isinstance(event.char, str) and event.char:
            self.uid_buffer += event.char

            if event.char == "?":
                uid = self.extract_uid_from_card_swipe(self.uid_buffer)
                self.uid_buffer = ""

                if uid is not None:
                    self.start_session_with_uid(uid)

        elif event.keysym in {"Return", "KP_Enter"}:
            uid = self.extract_uid_from_card_swipe(self.uid_buffer)
            self.uid_buffer = ""

            if uid is not None:
                self.start_session_with_uid(uid)

    def start_session_with_uid(self, uid: str) -> None:
        self.current_uid = uid
        self.uid_buffer = ""
        self.start_preview_state()

    def transform_frame(self, frame: np.ndarray) -> np.ndarray:
        transform = self.config.image_transform

        if transform.rotation_degrees == 90:
            frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
        elif transform.rotation_degrees == 180:
            frame = cv2.rotate(frame, cv2.ROTATE_180)
        elif transform.rotation_degrees == 270:
            frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)

        if transform.mirror:
            frame = cv2.flip(frame, 1)

        return frame

    def center_square_crop(self, frame: np.ndarray) -> np.ndarray:
        height, width = frame.shape[:2]
        size = min(width, height)

        x0 = (width - size) // 2
        y0 = (height - size) // 2

        return frame[y0 : y0 + size, x0 : x0 + size]

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
            font=("Helvetica", 24, "bold"),
            fg="white",
            bg=color,
            activebackground=color,
            activeforeground="white",
            width=12,
            height=2,
            bd=5,
        )

    def set_idle_state(self) -> None:
        assert self.message_label is not None
        assert self.preview_countdown_label is not None

        self.state = KioskState.IDLE
        self.current_uid = None
        self.uid_buffer = ""
        self.captured_frame = None

        self.preview_countdown_label.place_forget()
        self.message_label.config(text="Swipe ID Card\nto Begin")

        self.clear_buttons()

    def start_preview_state(self) -> None:
        assert self.message_label is not None
        assert self.preview_countdown_label is not None

        self.state = KioskState.PREVIEW
        self.captured_frame = None

        self.preview_countdown_label.place_forget()
        self.message_label.config(
            text="Position yourself, then touch\n'Take Photo'"
        )

        self.clear_buttons()

        self.make_button(
            "Take Photo",
            self.start_countdown_state,
            "#008844",
        ).pack(pady=10)

        self.make_button(
            "Cancel",
            self.set_idle_state,
            "#884400",
        ).pack(pady=10)

    def start_countdown_state(self) -> None:
        self.last_beep_remaining = None
        self.state = KioskState.COUNTDOWN
        self.clear_buttons()
        self.countdown_start = time.time()
        self.run_countdown()

    def run_countdown(self) -> None:
        assert self.message_label is not None
        assert self.preview_countdown_label is not None

        elapsed = time.time() - self.countdown_start
        remaining = self.config.countdown_seconds - int(elapsed)

        if remaining > 0:
            text = str(remaining)

            if (
                self.config.countdown_beep_enabled
                and remaining != self.last_beep_remaining
            ):
                self.control_window.bell()
                self.last_beep_remaining = remaining

            self.message_label.config(text=text)

            center_x = (
                self.preview_image_x
                + self.preview_image_width // 2
            )

            center_y = (
                self.preview_image_y
                + self.preview_image_height // 2
            )

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

            self.control_window.after(100, self.run_countdown)
        else:
            self.preview_countdown_label.place_forget()
            self.capture_image()

    def flash_preview(self) -> None:
        assert self.preview_window is not None

        if self.flash_overlay is not None:
            self.flash_overlay.destroy()

        self.flash_overlay = tk.Frame(self.preview_window, bg="white")
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
            self.message_label.config(text="Camera error. Try again.")
            self.control_window.after(2000, self.start_preview_state)
            return

        self.flash_preview()

        if self.config.square_output:
            self.captured_frame = self.center_square_crop(
                self.current_frame
            ).copy()
        else:
            self.captured_frame = self.current_frame.copy()

        self.state = KioskState.REVIEW

        self.message_label.config(text="Review your headshot")
        self.clear_buttons()

        self.make_button("Accept", self.accept_image, "#008844").pack(pady=10)
        self.make_button("Retake", self.start_preview_state, "#aa6600").pack(
            pady=10
        )
        self.make_button("Cancel", self.set_idle_state, "#884400").pack(pady=10)

    def accept_image(self) -> None:
        assert self.message_label is not None

        if self.captured_frame is None:
            self.message_label.config(text="No image captured. Try again.")
            self.control_window.after(2000, self.start_preview_state)
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        uid = self.current_uid or "unknown"

        image_path = \
                self.config.accepted_dir / f"headshot_{uid}_{timestamp}.jpg"

        success = cv2.imwrite(str(image_path), self.captured_frame)

        if not success:
            self.message_label.config(text="Could not save image.")
            self.control_window.after(3000, self.set_idle_state)
            return

        if self.config.email.enabled:
            try:
                self.email_image(image_path)
                self.message_label.config(text="Submitted. Thank you!")
            except Exception as exc:
                self.message_label.config(
                    text=f"Saved, but email failed:\n{exc}"
                )
        else:
            self.message_label.config(text="Saved")

        self.clear_buttons()
        self.control_window.after(3000, self.set_idle_state)

    def email_image(self, image_path: Path) -> None:
        uid = self.current_uid or "unknown"
        email = self.config.email

        msg = EmailMessage()
        msg["Subject"] = "New department headshot"
        msg["From"] = str(email.from_address)
        msg["To"] = str(email.to_address)

        msg.set_content(
            f"A new headshot was accepted.\n\n"
            f"UID: {uid}\n"
            f"File: {image_path.name}\n"
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
            self.current_frame = frame

            if (
                self.state is KioskState.REVIEW
                and self.captured_frame is not None
            ):
                display_frame = self.captured_frame
            else:
                display_frame = frame

            if self.config.square_output:
                display_frame = self.center_square_crop(display_frame)

            rgb_frame = cv2.cvtColor(display_frame, cv2.COLOR_BGR2RGB)
            image = Image.fromarray(rgb_frame)

            preview_w = max(1, self.preview_window.winfo_width())
            preview_h = max(1, self.preview_window.winfo_height())

            if self.config.scale_preview_to_fit:
                image = self.resize_image_to_fit(
                    image,
                    preview_w,
                    preview_h,
                )

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

        self.control_window.after(20, self.update_video)

    def quit(self) -> None:
        if self.cap is not None:
            self.cap.release()

        self.control_window.destroy()


def main() -> None:
    config = HeadshotConfig()
    root = tk.Tk()

    HeadshotKiosk(root, config)

    root.mainloop()


if __name__ == "__main__":
    main()

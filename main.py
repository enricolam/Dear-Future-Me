"""
main.py — OOP Tkinter GUI with two major UIs:
1) Settings UI
2) Recording UI

... (original docstring unchanged) ...
"""

import os
import sys
import io
import wave
import time
import shutil
import threading
import subprocess
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Optional, Tuple, Any, List

import tkinter as tk
from tkinter import ttk, messagebox

import psutil
import numpy as np
import sounddevice as sd


# ---------------------------
# Colors (Very Peri + Vanilla Ice vibe)
# ---------------------------
VERY_PERI = "#6667AB"     # Pantone 17-3938 Very Peri (approx)
VANILLA_ICE = "#F0EADA"   # cream
INK = "#1f2330"
WHITE = "#ffffff"
MUTED = "#6b7280"


# ---------------------------
# Settings Model
# ---------------------------
TRIGGER_MODES = ["Mode 1", "Mode 2", "Mode 3", "Mode 4", "Mode 5", "Mode 6"]


@dataclass
class Settings:
    record_duration_s: int = 10
    trigger_mode: str = TRIGGER_MODES[0]
    volume: int = 10
    level_revert: int = 0
    audio_output: int = 0          # dac(0), direct(1)
    detect_level_revert: int = 0
    sleep_enable: int = 0

    def clamp(self) -> None:
        self.record_duration_s = max(1, min(30, int(self.record_duration_s)))
        self.volume = max(0, min(30, int(self.volume)))
        self.level_revert = 1 if int(self.level_revert) else 0
        self.audio_output = 1 if int(self.audio_output) else 0
        self.detect_level_revert = 1 if int(self.detect_level_revert) else 0
        self.sleep_enable = 1 if int(self.sleep_enable) else 0
        if self.trigger_mode not in TRIGGER_MODES:
            self.trigger_mode = TRIGGER_MODES[0]


# ---------------------------
# UI State
# ---------------------------
class RecState(Enum):
    NO_DISK = auto()
    READY = auto()
    RECORDING = auto()
    WRITING = auto()


# ---------------------------
# Disk Service (unchanged)
# ---------------------------
class DiskService:
    MAX_TOTAL_BYTES = 32 * 1024 * 1024  # 32MB

    def __init__(self) -> None:
        self._last_mount: Optional[str] = None

    def find_target_disk(self) -> Optional[Tuple[Any, Any]]:
        parts = psutil.disk_partitions(all=False)

        sys_mount = self._system_mountpoint()
        exclude_mountpoints = set(self._common_excludes())
        if sys_mount:
            exclude_mountpoints.add(sys_mount)

        candidates: List[Tuple[Any, Any]] = []
        for p in parts:
            mp = getattr(p, "mountpoint", None)
            fstype = getattr(p, "fstype", "")

            if not mp:
                continue
            if mp in exclude_mountpoints:
                continue
            if fstype in ("", "squashfs"):
                continue

            try:
                usage = psutil.disk_usage(mp)
            except Exception:
                continue

            if usage.total >= self.MAX_TOTAL_BYTES:
                continue

            if not os.access(mp, os.W_OK):
                continue

            candidates.append((p, usage))

        if self._last_mount:
            for p, u in candidates:
                if getattr(p, "mountpoint", None) == self._last_mount:
                    return p, u

        if candidates:
            candidates.sort(key=lambda t: t[1].total)
            self._last_mount = getattr(candidates[0][0], "mountpoint", None)
            return candidates[0]

        self._last_mount = None
        return None

    def wipe_disk(self, mountpoint: str) -> None:
        root = Path(mountpoint)
        if not root.exists() or not root.is_dir():
            return

        for item in root.iterdir():
            try:
                if item.is_dir() and not item.is_symlink():
                    shutil.rmtree(item, ignore_errors=False)
                else:
                    item.unlink(missing_ok=True)
            except Exception:
                pass

    def write_config_and_audio(self, mountpoint: str, settings: Settings, mp3_bytes: bytes) -> None:
        root = Path(mountpoint)
        root.mkdir(parents=True, exist_ok=True)

        config_content = "2 30 1 1 1 0\n"
        cfg_path = root / "config.txt"
        cfg_path.write_text(config_content, encoding="utf-8")

        audio_path = root / "recording.mp3"
        audio_path.write_bytes(mp3_bytes)

        try:
            if hasattr(os, "sync"):
                os.sync()
        except Exception:
            pass

    def eject_disk(self, partition: Any) -> None:
        mp = getattr(partition, "mountpoint", "")
        dev = getattr(partition, "device", "")

        try:
            if sys.platform.startswith("win"):
                drive = mp.rstrip("\\/")
                cmd = [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    f"(New-Object -ComObject Shell.Application).NameSpace(17).ParseName('{drive}').InvokeVerb('Eject')"
                ]
                subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            elif sys.platform == "darwin":
                subprocess.run(["diskutil", "eject", mp], check=False,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                if dev:
                    subprocess.run(["udisksctl", "unmount", "-b", dev], check=False,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    subprocess.run(["udisksctl", "power-off", "-b", dev], check=False,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    subprocess.run(["umount", mp], check=False,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

    def _system_mountpoint(self) -> Optional[str]:
        try:
            if sys.platform.startswith("win"):
                return os.environ.get("SystemDrive", "C:") + "\\"
            return "/"
        except Exception:
            return None

    def _common_excludes(self) -> List[str]:
        if sys.platform.startswith("win"):
            return ["A:\\", "B:\\"]
        if sys.platform == "darwin":
            return ["/", "/System", "/Volumes/Macintosh HD", "/Volumes"]
        return ["/", "/proc", "/sys", "/dev", "/run"]


# ---------------------------
# Recorder (unchanged)
# ---------------------------
class RecorderService:
    def __init__(self, samplerate: int = 44100, channels: int = 1) -> None:
        self.samplerate = int(samplerate)
        self.channels = int(channels)
        self._stream: Optional[sd.InputStream] = None
        self._frames: List[np.ndarray] = []
        self._lock = threading.Lock()
        self._is_recording = False

    def start(self) -> None:
        with self._lock:
            self._frames = []
            self._is_recording = True

        def callback(indata, frames, time_info, status):
            if status:
                pass
            with self._lock:
                if not self._is_recording:
                    return
                self._frames.append(indata.copy())

        self._stream = sd.InputStream(
            samplerate=self.samplerate,
            channels=self.channels,
            dtype="int16",
            callback=callback,
        )
        self._stream.start()

    def stop(self) -> None:
        with self._lock:
            self._is_recording = False

        if self._stream is not None:
            try:
                self._stream.stop()
            except Exception:
                pass
            try:
                self._stream.close()
            except Exception:
                pass
        self._stream = None

    def export_mp3_bytes(self) -> bytes:
        with self._lock:
            frames = list(self._frames)

        if not frames:
            raise RuntimeError(
                "No audio captured.\n\n"
                "Check:\n"
                "1) Windows microphone permission\n"
                "2) Default input device is your mic\n"
                "3) Another app isn't blocking exclusive access"
            )

        if shutil.which("ffmpeg") is None:
            raise RuntimeError("ffmpeg not found on PATH.")

        pcm = np.concatenate(frames, axis=0)

        wav_buf = io.BytesIO()
        with wave.open(wav_buf, "wb") as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(2)
            wf.setframerate(self.samplerate)
            wf.writeframes(pcm.tobytes())
        wav_bytes = wav_buf.getvalue()

        proc = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel", "error",
                "-f", "wav",
                "-i", "pipe:0",
                "-f", "mp3",
                "-b:a", "128k",
                "pipe:1",
            ],
            input=wav_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        if proc.returncode != 0:
            err = proc.stderr.decode(errors="ignore").strip()
            raise RuntimeError(f"ffmpeg failed:\n{err}")

        mp3_bytes = proc.stdout
        if not mp3_bytes:
            raise RuntimeError("MP3 encoding produced empty output.")
        return mp3_bytes


# ---------------------------
# Widgets (unchanged)
# ---------------------------
class RoundButton(tk.Canvas):
    def __init__(self, master: tk.Misc, diameter: int, bg: str, fg: str, text: str, command):
        super().__init__(master, width=diameter, height=diameter,
                         highlightthickness=0, bg=master["bg"])
        self.command = command

        self._oval = self.create_oval(6, 6, diameter - 6, diameter - 6, fill=bg, outline="")
        self._label = self.create_text(diameter // 2, diameter // 2,
                                       text=text, fill=fg,
                                       font=("Helvetica", 18, "bold"))

        self.tag_bind(self._oval, "<Button-1>", self._clicked)
        self.tag_bind(self._label, "<Button-1>", self._clicked)

    def _clicked(self, event):
        self.command()
        return "break"

    def set_text(self, text: str) -> None:
        self.itemconfigure(self._label, text=text)

    def set_colors(self, bg: str, fg: str) -> None:
        self.itemconfigure(self._oval, fill=bg)
        self.itemconfigure(self._label, fill=fg)


# ---------------------------
# Frames
# ---------------------------
class SettingsFrame(tk.Frame):
    def __init__(self, master: tk.Misc, app: "App") -> None:
        super().__init__(master, bg=VANILLA_ICE)
        self.app = app

        self.v_duration = tk.IntVar(value=app.settings.record_duration_s)
        self.v_trigger = tk.StringVar(value=app.settings.trigger_mode)
        self.v_volume = tk.IntVar(value=app.settings.volume)

        self.v_level_revert = tk.IntVar(value=app.settings.level_revert)
        self.v_audio_output = tk.IntVar(value=app.settings.audio_output)
        self.v_detect_level_revert = tk.IntVar(value=app.settings.detect_level_revert)
        self.v_sleep_enable = tk.IntVar(value=app.settings.sleep_enable)

        self._build()

    def _build(self) -> None:
        tk.Label(self, text="Settings", bg=VANILLA_ICE, fg=INK,
                 font=("Helvetica", 20, "bold")).pack(pady=(18, 10))

        card = tk.Frame(self, bg=VANILLA_ICE)
        card.pack(padx=18, pady=10, fill="both", expand=True)

        def section(lbl: str) -> tk.Frame:
            f = tk.Frame(card, bg=WHITE)
            tk.Label(f, text=lbl, bg=WHITE, fg=INK, font=("Helvetica", 11, "bold")).pack(anchor="w")
            return f

        f = section("Record duration (1–30s)")
        tk.Scale(f, from_=1, to=30, orient="horizontal", variable=self.v_duration,
                 bg=WHITE, fg=INK, troughcolor=VANILLA_ICE, highlightthickness=0).pack(fill="x")
        f.pack(fill="x", padx=14, pady=(14, 6))

        f = section("Trigger mode")
        ttk.OptionMenu(f, self.v_trigger, self.v_trigger.get(), *TRIGGER_MODES).pack(anchor="w")
        f.pack(fill="x", padx=14, pady=6)

        f = section("Volume (00–30)")
        tk.Scale(f, from_=0, to=30, orient="horizontal", variable=self.v_volume,
                 bg=WHITE, fg=INK, troughcolor=VANILLA_ICE, highlightthickness=0).pack(fill="x")
        f.pack(fill="x", padx=14, pady=6)

        def radio01(lbl: str, var: tk.IntVar) -> None:
            f = section(lbl)
            row = tk.Frame(f, bg=WHITE)
            tk.Radiobutton(row, text="0", value=0, variable=var,
                           bg=WHITE, fg=INK, selectcolor=VANILLA_ICE).pack(side="left", padx=(0, 12))
            tk.Radiobutton(row, text="1", value=1, variable=var,
                           bg=WHITE, fg=INK, selectcolor=VANILLA_ICE).pack(side="left")
            row.pack(anchor="w", pady=(4, 0))
            f.pack(fill="x", padx=14, pady=6)

        radio01("Level revert (0/1)", self.v_level_revert)

        f = section("Audio output")
        row = tk.Frame(f, bg=WHITE)
        tk.Radiobutton(row, text="DAC (0)", value=0, variable=self.v_audio_output,
                       bg=WHITE, fg=INK, selectcolor=VANILLA_ICE).pack(side="left", padx=(0, 12))
        tk.Radiobutton(row, text="Direct (1)", value=1, variable=self.v_audio_output,
                       bg=WHITE, fg=INK, selectcolor=VANILLA_ICE).pack(side="left")
        row.pack(anchor="w", pady=(4, 0))
        f.pack(fill="x", padx=14, pady=6)

        radio01("Detect level revert (0/1)", self.v_detect_level_revert)
        radio01("Sleep enable (0/1)", self.v_sleep_enable)

        footer = tk.Frame(self, bg=VANILLA_ICE)
        footer.pack(fill="x", padx=18, pady=(0, 16))

        tk.Button(
            footer, text="Save", command=self._save,
            bg=VERY_PERI, fg=WHITE, relief="flat",
            padx=18, pady=10, font=("Helvetica", 11, "bold")
        ).pack(side="left")

        tk.Button(
            footer, text="Go to Recording →", command=lambda: self.app.show("recording"),
            bg=VANILLA_ICE, fg=INK, relief="flat",
            padx=10, pady=10, font=("Helvetica", 11, "bold")
        ).pack(side="right")

    def _save(self) -> None:
        s = self.app.settings
        s.record_duration_s = self.v_duration.get()
        s.trigger_mode = self.v_trigger.get()
        s.volume = self.v_volume.get()
        s.level_revert = self.v_level_revert.get()
        s.audio_output = self.v_audio_output.get()
        s.detect_level_revert = self.v_detect_level_revert.get()
        s.sleep_enable = self.v_sleep_enable.get()
        s.clamp()
        messagebox.showinfo("Saved", "Settings saved.")


class RecordingFrame(tk.Frame):
    SCAN_INTERVAL_MS = 700

    def __init__(self, master: tk.Misc, app: "App") -> None:
        super().__init__(master, bg=VERY_PERI)
        self.app = app

        self.state: RecState = RecState.NO_DISK
        self.partition: Optional[Any] = None
        self.usage: Optional[Any] = None

        self.seconds_left: int = 0
        self.countdown_job: Optional[str] = None

        self._build()
        self._scan_loop()

    def _build(self) -> None:
        top = tk.Frame(self, bg=VERY_PERI)
        top.pack(fill="x", padx=16, pady=(14, 8))

        tk.Button(
            top, text="← Settings", command=lambda: self.app.show("settings"),
            bg=VERY_PERI, fg=WHITE, relief="flat",
            font=("Helvetica", 11, "bold")
        ).pack(side="left")

        tk.Label(top, text="Recording", bg=VERY_PERI, fg=WHITE,
                 font=("Helvetica", 20, "bold")).pack(side="right")

        card = tk.Frame(self, bg=VANILLA_ICE)
        card.pack(fill="both", expand=True, padx=18, pady=18)

        self.status = tk.Label(card, text="", bg=VANILLA_ICE, fg=INK, font=("Helvetica", 14, "bold"))
        self.status.pack(pady=(24, 6))

        self.sub = tk.Label(card, text="", bg=VANILLA_ICE, fg=MUTED, font=("Helvetica", 11))
        self.sub.pack(pady=(0, 16))

        self.count = tk.Label(card, text="00:00", bg=VANILLA_ICE, fg=INK, font=("Helvetica", 26, "bold"))
        self.count.pack(pady=(0, 18))

        self.btn = RoundButton(card, diameter=180, bg=VERY_PERI, fg=WHITE, text="RECORD", command=self._on_button)
        self.btn.pack(pady=(6, 10))

        self.hint = tk.Label(card, text="", bg=VANILLA_ICE, fg=INK, font=("Helvetica", 11))
        self.hint.pack(pady=(8, 20))

        self._render()

    def trigger_record_stop(self):
        """Public method — called by space/enter key or button click"""
        self._on_button()

    def _render(self) -> None:
        if self.state == RecState.NO_DISK:
            self.status.config(text="No disk detected")
            self.sub.config(text="Insert a disk with total capacity < 32MB.")
            self.count.config(text="00:00")
            self.btn.set_text("RECORD")
            self.btn.set_colors(VERY_PERI, WHITE)
            self.hint.config(text="Waiting for disk…")

        elif self.state == RecState.READY:
            mp = getattr(self.partition, "mountpoint", "?")
            tot = getattr(self.usage, "total", 0)
            self.status.config(text="Disk detected — Ready")
            self.sub.config(text=f"Mount: {mp}   Total: {tot} bytes")
            self.count.config(text=self._fmt_time(self.app.settings.record_duration_s))
            self.btn.set_text("RECORD")
            self.btn.set_colors(VERY_PERI, WHITE)
            self.hint.config(text="Press RECORD or SPACE to start.")

        elif self.state == RecState.RECORDING:
            self.status.config(text="Recording…")
            self.sub.config(text="Press STOP or SPACE to end immediately.")
            self.btn.set_text("STOP")
            self.btn.set_colors("#D94B4B", WHITE)
            self.hint.config(text="Recording in progress…")

        elif self.state == RecState.WRITING:
            self.status.config(text="Writing to disk…")
            self.sub.config(text="Please wait patiently.")
            self.btn.set_text("WAIT")
            self.btn.set_colors(MUTED, WHITE)
            self.hint.config(text="Finalizing + ejecting (if possible)…")

    def _scan_loop(self) -> None:
        if self.state in (RecState.RECORDING, RecState.WRITING):
            self.after(self.SCAN_INTERVAL_MS, self._scan_loop)
            return

        found = self.app.disk_service.find_target_disk()
        if not found:
            self.partition, self.usage = None, None
            self.state = RecState.NO_DISK
            self._render()
            self.after(self.SCAN_INTERVAL_MS, self._scan_loop)
            return

        part, usage = found
        new_disk = (self.partition is None) or (
            getattr(part, "mountpoint", None) != getattr(self.partition, "mountpoint", None)
        )

        self.partition, self.usage = part, usage

        if new_disk:
            try:
                self.app.disk_service.wipe_disk(getattr(part, "mountpoint", ""))
            except Exception:
                pass

        self.state = RecState.READY
        self._render()
        self.after(self.SCAN_INTERVAL_MS, self._scan_loop)

    def _on_button(self) -> None:
        if self.state == RecState.NO_DISK:
            messagebox.showwarning("No disk", "No disk detected. Insert a disk (< 32MB).")
            return
        if self.state == RecState.WRITING:
            return

        if self.state == RecState.READY:
            self._start_recording()
        elif self.state == RecState.RECORDING:
            self._stop_and_write()

    def _start_recording(self) -> None:
        if not self.partition:
            self.state = RecState.NO_DISK
            self._render()
            return

        self.app.settings.clamp()
        self.seconds_left = self.app.settings.record_duration_s

        try:
            self.app.recorder.start()
        except Exception as e:
            messagebox.showerror("Recording error", f"Failed to start recording:\n{e}")
            self.state = RecState.READY
            self._render()
            return

        self.state = RecState.RECORDING
        self._render()
        self._tick()

    def _tick(self) -> None:
        if self.state != RecState.RECORDING:
            return

        self.count.config(text=self._fmt_time(self.seconds_left))

        if self.seconds_left <= 0:
            self._stop_and_write()
            return

        self.seconds_left -= 1
        self.countdown_job = self.after(1000, self._tick)

    def _stop_and_write(self) -> None:
        if self.countdown_job:
            try:
                self.after_cancel(self.countdown_job)
            except Exception:
                pass
            self.countdown_job = None

        try:
            self.app.recorder.stop()
        except Exception:
            pass

        self.state = RecState.WRITING
        self._render()

        threading.Thread(target=self._write_worker, daemon=True).start()

    def _write_worker(self) -> None:
        part = self.partition
        if not part:
            self.after(0, self._set_no_disk)
            return

        mp = getattr(part, "mountpoint", "")
        self.app.settings.clamp()

        try:
            mp3_bytes = self.app.recorder.export_mp3_bytes()
        except Exception as e:
            self.after(0, lambda: messagebox.showerror("Audio export failed", str(e)))
            self.after(0, self._set_ready_or_no_disk)
            return

        try:
            self.app.disk_service.write_config_and_audio(mp, self.app.settings, mp3_bytes)
        except Exception as e:
            self.after(0, lambda: messagebox.showerror("Write failed", str(e)))
            self.after(0, self._set_ready_or_no_disk)
            return

        try:
            self.app.disk_service.eject_disk(part)
        except Exception:
            pass

        self.after(0, self._set_ready_or_no_disk)

    def _set_ready_or_no_disk(self) -> None:
        found = self.app.disk_service.find_target_disk()
        if found:
            self.partition, self.usage = found
            self.state = RecState.READY
        else:
            self.partition, self.usage = None, None
            self.state = RecState.NO_DISK
        self._render()

    def _set_no_disk(self) -> None:
        self.partition, self.usage = None, None
        self.state = RecState.NO_DISK
        self._render()

    @staticmethod
    def _fmt_time(seconds: int) -> str:
        seconds = max(0, int(seconds))
        m, s = divmod(seconds, 60)
        return f"{m:02d}:{s:02d}"


# ---------------------------
# Main App — with key binding control
# ---------------------------
class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Cedars Station Recorder")
        self.geometry("700x520")
        self.attributes('-fullscreen', True)
        # Optional: still enforce a minimum size in case fullscreen is exited
        self.minsize(640, 460)
        self.minsize(640, 460)

        self.settings = Settings()
        self.disk_service = DiskService()
        self.recorder = RecorderService(samplerate=44100, channels=1)

        self._configure_ttk()

        container = tk.Frame(self, bg=VERY_PERI)
        container.pack(fill="both", expand=True)

        self.frames = {
            "settings": SettingsFrame(container, self),
            "recording": RecordingFrame(container, self),
        }

        for f in self.frames.values():
            f.place(relx=0, rely=0, relwidth=1, relheight=1)

        self.show("settings")

        # Make sure the window can receive key events
        self.focus_set()

    def _configure_ttk(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("TMenubutton", padding=6)
        style.configure("TButton", padding=6)

    def show(self, name: str) -> None:
        self.frames[name].tkraise()
        self.frames[name].focus_set()           # Helps key events reach the frame/window

        # Manage space/return binding only on recording screen
        if name == "recording":
            self.bind("<space>", self._on_space_or_enter)
            self.bind("<Return>", self._on_space_or_enter)
        else:
            # Clean up bindings when leaving recording screen
            self.unbind("<space>")
            self.unbind("<Return>")

    def _on_space_or_enter(self, event=None):
        # Safely call the recording frame's trigger method
        recording_frame = self.frames.get("recording")
        if recording_frame:
            recording_frame.trigger_record_stop()


if __name__ == "__main__":
    app = App()
    app.mainloop()

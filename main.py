#!/usr/bin/env python3
"""
Voice Input GUI - Record, Transcribe, Copy
"""

import sys
import subprocess
import threading
import tempfile
import os
import json
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QTextEdit,
    QFrame,
    QComboBox,
    QDialog,
    QMessageBox,
    QFileDialog,
    QScrollArea,
    QLineEdit,
)
from PyQt6.QtCore import Qt, QSize, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QAction, QIcon, QTextCursor, QKeySequence, QShortcut

# Config file path
CONFIG_DIR = os.path.expanduser("~/.config/whisper-im")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

# Default settings
DEFAULT_SETTINGS = {
    "models_dir": "whisper.cpp/models",
    "model": "base",
    "language": "zh",
    "threads": "4",
    "backend": "default",  # "default" or "openvino"
}

# Models for different backends
MODELS_DEFAULT = ["tiny", "base", "small", "medium", "large"]
MODELS_OPENVINO = ["tiny", "base", "small", "medium"]


def load_settings():
    """Load settings from config file"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                settings = json.load(f)
                return {**DEFAULT_SETTINGS, **settings}
        except:
            pass
    return DEFAULT_SETTINGS.copy()


def save_settings(settings):
    """Save settings to config file"""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(settings, f, indent=2)


class TranscribeWorker(QThread):
    """Worker thread for transcription"""

    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, audio_file, models_dir, model, threads, language, backend="default"):
        super().__init__()
        self.audio_file = audio_file
        self.models_dir = models_dir
        self.model = model
        self.threads = threads
        self.language = language
        self.backend = backend

    def run(self):
        txt_file = self.audio_file + ".txt"
        if os.path.exists(txt_file):
            os.remove(txt_file)

        # Find whisper-cli in PATH, fallback to relative path
        import shutil

        whisper_cli = shutil.which("whisper-cli")

        if not whisper_cli:
            self.error.emit(
                "whisper-cli not found.\nInstall whisper.cpp or add it to PATH."
            )
            return

        # Get models path from settings or default
        models_dir = self.models_dir if self.models_dir else "whisper.cpp/models"

        # Model file is always the ggml format, OpenVINO encoder is auto-loaded via -oved flag
        model_path = os.path.join(models_dir, f"ggml-{self.model}.bin")

        # Check if model exists
        if not os.path.exists(model_path):
            self.error.emit(
                f"Model not found:\n{model_path}\n\nConfigure models directory in Settings."
            )
            return

        try:
            # Build command arguments
            cmd = [
                whisper_cli,
                self.audio_file,
                "-m",
                model_path,
                "-t",
                self.threads,
                "-l",
                self.language,
                "-otxt",
                "-np",
            ]

            # Add OpenVINO device flag if using OpenVINO backend
            if self.backend == "openvino":
                cmd.extend(["-oved", "CPU"])

            whisper_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            stdout, stderr = whisper_process.communicate(timeout=120)

            # Check for errors in whisper output
            if whisper_process.returncode != 0:
                self.error.emit(f"Whisper error:\n{stderr}")
                return

            if os.path.exists(txt_file):
                with open(txt_file, "r", encoding="utf-8") as f:
                    final_text = f.read().strip()
            else:
                final_text = ""

            # Convert Traditional to Simplified Chinese
            if final_text and self.language in ["zh", "auto"]:
                try:
                    import opencc

                    converter = opencc.OpenCC("t2s")
                    final_text = converter.convert(final_text)
                except:
                    pass

            # Copy to clipboard
            if final_text:
                wl_copy_process = subprocess.Popen(
                    ["wl-copy"], stdin=subprocess.PIPE, text=True
                )
                wl_copy_process.communicate(input=final_text)

            self.finished.emit(final_text)

        except subprocess.TimeoutExpired:
            self.error.emit("Transcribe timeout")
        except Exception as e:
            self.error.emit(f"Error: {e}")


class SettingsDialog(QDialog):
    """Settings dialog"""

    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.setWindowTitle("Settings")
        self.setFixedSize(500, 380)
        self.setModal(True)

        layout = QVBoxLayout()

        # Backend mode selection
        backend_layout = QHBoxLayout()
        backend_layout.addWidget(QLabel("Backend:"))
        self.backend_combo = QComboBox()
        self.backend_combo.addItems(["Default (whisper.cpp)", "OpenVINO"])
        self.backend_combo.setCurrentText("Default (whisper.cpp)" if parent.backend_var == "default" else "OpenVINO")
        self.backend_combo.currentTextChanged.connect(self.on_backend_changed)
        backend_layout.addWidget(self.backend_combo)
        backend_layout.addStretch()
        layout.addLayout(backend_layout)

        # Model directory selection
        dir_layout = QHBoxLayout()
        dir_layout.addWidget(QLabel("Models Dir:"))
        self.dir_edit = QLineEdit(parent.models_dir_var)
        self.dir_edit.setPlaceholderText("whisper.cpp/models or ~/.cache/whisper")
        dir_layout.addWidget(self.dir_edit)
        layout.addLayout(dir_layout)

        # Model selection
        model_layout = QHBoxLayout()
        model_layout.addWidget(QLabel("Model:"))
        self.model_combo = QComboBox()
        self.update_model_list(parent.backend_var)
        self.model_combo.setCurrentText(parent.model_var)
        model_layout.addWidget(self.model_combo)
        model_layout.addStretch()
        layout.addLayout(model_layout)

        # Language selection
        lang_layout = QHBoxLayout()
        lang_layout.addWidget(QLabel("Language:"))
        self.lang_combo = QComboBox()
        self.lang_combo.addItems(["auto", "zh", "en", "ja", "ko"])
        self.lang_combo.setCurrentText(parent.lang_var)
        lang_layout.addWidget(self.lang_combo)
        lang_layout.addStretch()
        layout.addLayout(lang_layout)

        # Thread selection
        thread_layout = QHBoxLayout()
        thread_layout.addWidget(QLabel("Threads:"))
        self.thread_combo = QComboBox()
        self.thread_combo.addItems(["1", "2", "4", "8", "16"])
        self.thread_combo.setCurrentText(parent.thread_var)
        thread_layout.addWidget(self.thread_combo)
        thread_layout.addStretch()
        layout.addLayout(thread_layout)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        save_btn = QPushButton("Save & Close")
        save_btn.clicked.connect(self.save_and_close)
        btn_layout.addWidget(save_btn)
        layout.addLayout(btn_layout)

        self.setLayout(layout)

    def get_backend_value(self):
        """Get backend value from combo text"""
        text = self.backend_combo.currentText()
        return "openvino" if "OpenVINO" in text else "default"

    def update_model_list(self, backend):
        """Update model list based on backend"""
        models = MODELS_OPENVINO if backend == "openvino" else MODELS_DEFAULT
        current_model = self.model_combo.currentText() if self.model_combo.currentText() else self.parent.model_var
        self.model_combo.clear()
        self.model_combo.addItems(models)
        if current_model in models:
            self.model_combo.setCurrentText(current_model)
        elif backend == "openvino":
            self.model_combo.setCurrentText("base")

    def on_backend_changed(self):
        """Handle backend selection change"""
        backend = self.get_backend_value()
        self.update_model_list(backend)

    def save_and_close(self):
        self.parent.models_dir_var = self.dir_edit.text().strip()
        self.parent.model_var = self.model_combo.currentText()
        self.parent.lang_var = self.lang_combo.currentText()
        self.parent.thread_var = self.thread_combo.currentText()
        self.parent.backend_var = self.get_backend_value()
        save_settings(
            {
                "models_dir": self.parent.models_dir_var,
                "model": self.parent.model_var,
                "language": self.parent.lang_var,
                "threads": self.parent.thread_var,
                "backend": self.parent.backend_var,
            }
        )
        self.accept()


class VoiceInputWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Voice Input")
        self.setGeometry(100, 100, 900, 800)

        # Load settings
        self.settings = load_settings()
        self.models_dir_var = self.settings.get("models_dir", "whisper.cpp/models")
        self.model_var = self.settings["model"]
        self.lang_var = self.settings["language"]
        self.thread_var = self.settings["threads"]
        self.backend_var = self.settings.get("backend", "default")

        self.audio_file = tempfile.mktemp(suffix=".wav", dir="/tmp")
        self.recording = False
        self.recording_process = None
        self.transcribing = False

        self.setup_ui()

    def setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(20, 20, 20, 20)

        # Top section
        top_frame = QFrame()
        top_frame.setStyleSheet("background-color: #f0f0f0;")
        top_layout = QVBoxLayout(top_frame)

        # Menu bar with settings
        menubar = self.menuBar()
        settings_menu = menubar.addMenu("Settings")
        settings_action = QAction("Settings", self)
        settings_action.triggered.connect(self.open_settings)
        settings_menu.addAction(settings_action)

        # Title
        title = QLabel("Voice Input")
        title.setStyleSheet("font-size: 32px; font-weight: bold; color: #1976D2;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top_layout.addWidget(title)

        main_layout.addWidget(top_frame)

        # Buttons frame
        btn_frame = QFrame()
        btn_layout = QVBoxLayout(btn_frame)

        # Record button
        self.record_btn = QPushButton("[ START ]")
        self.record_btn.setFont(QFont("Arial", 20, QFont.Weight.Bold))
        self.record_btn.setStyleSheet(
            "background-color: #4CAF50; color: white; border-radius: 10px; padding: 15px; min-width: 200px;"
        )
        self.record_btn.clicked.connect(self.toggle_record)
        btn_layout.addWidget(self.record_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        # Status label
        self.status_label = QLabel("Ready")
        self.status_label.setFont(QFont("Arial", 18))
        self.status_label.setStyleSheet("color: gray;")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        btn_layout.addWidget(self.status_label)

        main_layout.addWidget(btn_frame)

        # Result area
        result_frame = QFrame()
        result_frame.setStyleSheet("border: 2px solid #1976D2; border-radius: 10px;")
        result_layout = QVBoxLayout(result_frame)

        result_label = QLabel("Result")
        result_label.setFont(QFont("Arial", 16))
        result_layout.addWidget(result_label)

        self.result_text = QTextEdit()
        self.result_text.setFont(QFont("Arial", 18))
        self.result_text.setReadOnly(True)
        result_layout.addWidget(self.result_text)

        main_layout.addWidget(result_frame, stretch=1)

        # Bottom section
        bottom_frame = QFrame()
        bottom_frame.setStyleSheet("background-color: #f0f0f0;")
        bottom_layout = QHBoxLayout(bottom_frame)

        # Copy button
        self.copy_btn = QPushButton("[ COPY TO CLIPBOARD ]")
        self.copy_btn.setFont(QFont("Arial", 14))
        self.copy_btn.setStyleSheet(
            "background-color: #FF9800; color: white; border-radius: 5px; padding: 10px;"
        )
        self.copy_btn.setEnabled(False)
        self.copy_btn.clicked.connect(self.copy_to_clipboard)
        bottom_layout.addWidget(self.copy_btn)

        bottom_layout.addStretch()

        # Hint
        hint = QLabel("Press SPACE to start/stop recording")
        hint.setFont(QFont("Arial", 12))
        hint.setStyleSheet("color: gray;")
        bottom_layout.addWidget(hint)

        main_layout.addWidget(bottom_frame)

        # Space key shortcut to toggle recording
        self.space_shortcut = QShortcut(Qt.Key.Key_Space, self)
        self.space_shortcut.activated.connect(self.toggle_record)

    def closeEvent(self, event):
        """Handle window close event to clean up resources"""
        # Stop recording process if running
        if self.recording_process and self.recording_process.poll() is None:
            self.recording_process.terminate()
            self.recording_process.wait()
        event.accept()

    def open_settings(self):
        dialog = SettingsDialog(self)
        dialog.exec()

    def toggle_record(self):
        if not self.recording:
            self.start_recording()
        else:
            self.stop_recording()

    def start_recording(self):
        self.recording = True
        self.record_btn.setText("[ STOP ]")
        self.record_btn.setStyleSheet(
            "background-color: #f44336; color: white; border-radius: 10px; padding: 15px; min-width: 200px;"
        )
        self.status_label.setText("Recording...")
        self.status_label.setStyleSheet("color: red;")
        self.result_text.clear()
        self.copy_btn.setEnabled(False)

        if os.path.exists(self.audio_file):
            os.remove(self.audio_file)

        self.recording_thread = threading.Thread(target=self._record_audio)
        self.recording_thread.daemon = True
        self.recording_thread.start()

    def _record_audio(self):
        try:
            self.recording_process = subprocess.Popen(
                ["arecord", "-f", "cd", "-d", "0", self.audio_file],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.recording_process.wait()
        except Exception as e:
            self.status_label.setText(f"Error: {e}")

    def stop_recording(self):
        self.recording = False
        self.record_btn.setText("[ START ]")
        self.record_btn.setStyleSheet(
            "background-color: #4CAF50; color: white; border-radius: 10px; padding: 15px; min-width: 200px;"
        )

        if self.recording_process:
            self.recording_process.terminate()
            self.recording_process.wait()

        if os.path.exists(self.audio_file):
            file_size = os.path.getsize(self.audio_file)
            if file_size > 1000:
                self.status_label.setText("Recording done, transcribing...")
                self.status_label.setStyleSheet("color: blue;")
                self.transcribe()
            else:
                self.status_label.setText("Invalid recording")
                self.status_label.setStyleSheet("color: orange;")
        else:
            self.status_label.setText("Recording failed")
            self.status_label.setStyleSheet("color: red;")

    def transcribe(self):
        if self.transcribing:
            return
        self.transcribing = True
        self.status_label.setText("Transcribing...")
        self.status_label.setStyleSheet("color: blue;")
        self.record_btn.setEnabled(False)

        # Create worker thread
        self.worker = TranscribeWorker(
            audio_file=self.audio_file,
            models_dir=self.models_dir_var,
            model=self.model_var,
            threads=self.thread_var,
            language=self.lang_var,
            backend=self.backend_var,
        )
        self.worker.finished.connect(self.on_transcribe_finished)
        self.worker.error.connect(self.on_transcribe_error)
        self.worker.start()

    def on_transcribe_finished(self, text):
        self.show_result(text)
        self.transcribing = False
        self.record_btn.setEnabled(True)

    def on_transcribe_error(self, error_msg):
        self.status_label.setText(error_msg)
        self.status_label.setStyleSheet("color: red;")
        self.transcribing = False
        self.record_btn.setEnabled(True)

    def show_result(self, text):
        if text:
            self.result_text.clear()
            self.result_text.insertPlainText(text)
            self.status_label.setText("Done")
            self.status_label.setStyleSheet("color: green;")
            self.copy_btn.setEnabled(True)
            # Auto close after a short delay
            QTimer.singleShot(500, self.close)
        else:
            self.status_label.setText("No text detected")
            self.status_label.setStyleSheet("color: orange;")

    def copy_to_clipboard(self):
        text = self.result_text.toPlainText().strip()
        if text:
            clipboard = QApplication.clipboard()
            clipboard.setText(text)
            self.status_label.setText("Copied!")
            self.status_label.setStyleSheet("color: green;")


def main():
    # Add common whisper-cli paths to PATH if not already present
    app = QApplication(sys.argv)
    app.setStyle("Fusion")  # Use Fusion style for better look

    # Add whisper.cpp paths to PATH for GUI launcher
    home = os.path.expanduser("~")
    whisper_paths = [
        os.path.join(home, "code/python/whisper-im/whisper.cpp/build/bin"),
        os.path.join(home, ".local/bin"),
        "/usr/local/bin",
        "/usr/bin",
    ]
    current_path = os.environ.get("PATH", "")
    new_paths = [p for p in whisper_paths if p not in current_path]
    if new_paths:
        os.environ["PATH"] = ":".join(new_paths) + ":" + current_path

    # Set application-wide font
    font = QFont("Arial", 12)
    app.setFont(font)

    window = VoiceInputWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()

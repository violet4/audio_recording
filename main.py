#!/home/violet/git/bitboundary/audio_recording/.venv/bin/python
import sys
from pathlib import Path
from datetime import datetime
import numpy as np
import sounddevice as sd
import soundfile as sf
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QComboBox, QPushButton)
from PySide6.QtCore import Qt, QThread, Signal

from threading import Thread

from dasbus.server.interface import dbus_interface
from dasbus.typing import Str, Bool
from dasbus.connection import SessionMessageBus

from dasbus.loop import EventLoop

from controller_client import setup_parser


SAMPLE_RATE = 44100
CHANNELS = 1
DTYPE = 'float32'


class AudioThread(QThread):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.active = False
        self.recording = []

    def run(self):
        with sd.Stream(channels=CHANNELS, dtype=DTYPE, 
                      samplerate=SAMPLE_RATE,
                      device=(self.input_device, self.output_device)) as stream:
            while self.active:
                data, overflowed = stream.read(1024)
                if self.mode == 'playthrough':
                    stream.write(data)
                elif self.mode == 'record':
                    self.recording.extend(data)

    def start_stream(self, mode, input_device, output_device=None):
        self.mode = mode
        self.input_device = input_device
        self.output_device = output_device
        self.active = True
        self.start()

    def stop_stream(self):
        self.active = False
        self.wait()


class AudioRecorderCore(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Audio Recorder")
        self.setMinimumSize(300, 200)

        self.audio_thread = AudioThread()
        self.setup_ui()
        self.toggle_recording_active = False

    def setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        # Input device dropdown
        self.input_combo = QComboBox()
        self.populate_devices(self.input_combo, True)
        layout.addWidget(self.input_combo)

        # Output device dropdown
        self.output_combo = QComboBox()
        self.populate_devices(self.output_combo, False)
        layout.addWidget(self.output_combo)

        # Direct playback button
        self.play_button = QPushButton("Hold to Play")
        self.play_button.pressed.connect(self.start_playback)
        self.play_button.released.connect(self.stop_playback)
        layout.addWidget(self.play_button)

        # Hold-to-record button
        self.hold_record_button = QPushButton("Hold to Record")
        self.hold_record_button.pressed.connect(lambda: self.start_recording(True))
        self.hold_record_button.released.connect(self.stop_recording)
        layout.addWidget(self.hold_record_button)

        # Toggle record button
        self.toggle_record_button = QPushButton("Toggle Recording")
        self.toggle_record_button.clicked.connect(self.toggle_recording)
        layout.addWidget(self.toggle_record_button)


    def populate_devices(self, combo: QComboBox, is_input: bool):
        combo.clear()
        devices = sd.query_devices()
        default_device = sd.default.device[0 if is_input else 1]

        for i, device in enumerate(devices):
            if is_input and device['max_input_channels'] > 0:
                combo.addItem(f"{device['name']}", i)
            elif not is_input and device['max_output_channels'] > 0:
                combo.addItem(f"{device['name']}", i)

        if not is_input:
            default_index = combo.findData(default_device)
            if default_index >= 0:
                combo.setCurrentIndex(default_index)

    def start_playback(self):
        input_device = self.input_combo.currentData()
        output_device = self.output_combo.currentData()
        self.audio_thread.start_stream('playthrough', input_device, output_device)

    def stop_playback(self):
        self.audio_thread.stop_stream()

    def start_recording(self, is_hold_mode=False):
        if not is_hold_mode and self.toggle_recording_active:
            return

        input_device = self.input_combo.currentData()
        self.audio_thread.recording = []
        self.audio_thread.start_stream('record', input_device)

        if not is_hold_mode:
            self.toggle_recording_active = True
            self.toggle_record_button.setText("Stop Recording")

    def stop_recording(self):
        self.audio_thread.stop_stream()

        if len(self.audio_thread.recording) > 0:
            recording_array = np.array(self.audio_thread.recording)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = Path('data') / f"recording_{timestamp}.wav"
            sf.write(str(filename), recording_array, SAMPLE_RATE)

        if self.toggle_recording_active:
            self.toggle_recording_active = False
            self.toggle_record_button.setText("Toggle Recording")

    def closeEvent(self, event):
        if self.audio_thread.isRunning():
            self.audio_thread.stop_stream()
        super().closeEvent(event)

    def toggle_recording(self) -> bool:
        if not self.toggle_recording_active:
            self.start_recording()
        else:
            self.stop_recording()
        return self.toggle_recording_active


@dbus_interface("com.violet.AudioRecorder")
class AudioRecorderDBUS(object):
    def __init__(self, core: AudioRecorderCore):
        super().__init__()
        self.core = core

    def ReloadDevices(self):
        self.core.populate_devices(self.core.input_combo, True)
        self.core.populate_devices(self.core.output_combo, False)
        return

    def ToggleRecording(self) -> Bool:
        return self.core.toggle_recording()


def main():
    pargs = setup_parser()

    try:
        bus = SessionMessageBus()
        proxy = bus.get_proxy('com.violet.AudioRecorder', "/com/violet/AudioRecorder")
        # print(proxy.Introspect())
    except Exception as e:
        print(e)

    if pargs.toggle_recording:
        print(proxy.ToggleRecording())
        exit()

    app = QApplication(sys.argv)
    window = AudioRecorderCore()
    window.show()

    bus = SessionMessageBus()
    audio_recorder_dbus = AudioRecorderDBUS(window)
    bus.publish_object("/com/violet/AudioRecorder", audio_recorder_dbus)
    bus.register_service("com.violet.AudioRecorder")

    loop = EventLoop()
    thread = Thread(target=loop.run, daemon=True)
    thread.start()
    app.exec()
    thread.join(0.1)


if __name__ == '__main__':
    main()


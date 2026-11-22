# Study Timer
 
A smart stopwatch that counts only your **effective working time**, using your webcam and computer vision.
 
The timer runs while you are at your desk, and stops the moment you leave or pick up your phone.
 
> Being at your desk doesn't necessarily mean working. You can only improve what you measure.
 
## Features
 
- **Face presence detection** – the timer runs only when your face is in front of the camera.
- **Phone-in-hand detection** – the timer stops as soon as you hold a phone (a phone lying on the desk is ignored).
- **Floating widget** – small, borderless, always on top, draggable: Start / Stop, Statistics, today's time and a status light (green = counting, red = not counting, with the reason).
- **Live camera view (optional)** – shows the webcam feed with a green frame when you are working and a red frame when you are not.
- **Statistics** – study time per day, week and month, plus your current streak of study days.
- **Daily goal** – progress bar toward your daily target.
- **100% local and private** – no cloud, no API. No image or video is ever saved: only time intervals are stored.
## How it works
 
```
Webcam → camera.py → detection.py → engine.py → database.py
                                        ↓
                    ui_widget.py / ui_camera.py / ui_stats.py
                                        ↑
                        main.py connects everything
```
 
| File | Role |
|------|------|
| `main.py` | Entry point. Wires the interface, the analysis thread, the engine and the database. |
| `camera.py` | Webcam capture and a background thread that analyses frames at a fixed rate. |
| `detection.py` | Runs the three AI models and decides whether a phone is held in hand. |
| `engine.py` | State machine: counting or not counting, with anti-flicker filtering. |
| `database.py` | Stores study intervals in SQLite (split at midnight) and computes statistics. |
| `ui_widget.py` | The floating widget. |
| `ui_camera.py` | The optional live camera window. |
| `ui_stats.py` | The statistics window (matplotlib charts). |
| `config.py` / `config.json` | Settings. |
| `tests/` | Automated tests (engine and database). |
 
### Counting rule
 
```
counting = face detected AND no forbidden object in hand
```
 
- Starting requires a few consecutive good frames, to avoid false starts.
- Stopping is immediate.
### Models (all run locally)
 
| Model | Purpose | File |
|-------|---------|------|
| MediaPipe Face Detector | Finds your face | `models/blaze_face_short_range.tflite` |
| MediaPipe Hand Landmarker | Finds your hands (21 points each) | `models/hand_landmarker.task` |
| YOLOv8n | Detects phones | `yolov8n.pt` |
 
A phone counts as "in hand" when enough hand landmarks fall inside the (slightly enlarged) phone bounding box.
 
## Installation
 
Requirements: Windows, Python 3.11 or 3.12, a webcam.
 
```bash
git clone https://github.com/ayoub-kochtben/study-timer.git
cd study-timer
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```
 
## Usage
 
```bash
.venv\Scripts\python main.py
```
 
1. Click **Start** (models load in a few seconds).
2. Sit in front of the webcam: the light turns green and the timer runs.
3. Pick up your phone or leave: the light turns red and the timer stops.
4. Click **Statistics** to see your progress.
## Configuration
 
Edit `config.json`:
 
| Setting | Meaning |
|---------|---------|
| `blacklist` | Objects that stop the timer (default: `["cell phone"]`) |
| `analysis_fps` | Analysis rate, images per second |
| `frames_to_start_counting` | Consecutive good frames needed to start |
| `frames_to_stop_counting` | Bad frames needed to stop (1 = immediate) |
| `database_path` | Location of the SQLite file |
 
Detection thresholds (confidence, overlap between hand and phone) can be tuned in the same file.
 
## Tests
 
```bash
.venv\Scripts\python -m pytest
```
 
## Tech stack
 
Python, OpenCV, MediaPipe, Ultralytics YOLOv8, PyQt6, matplotlib, SQLite.
 
## Limitations
 
- A phone almost fully hidden by the hand may be missed.
- Accuracy depends on lighting and camera quality.
- A phone held outside the camera's field of view cannot be seen.
## Privacy
 
All processing happens on your computer. Frames are analysed in memory and discarded. Only start and end times of study intervals are stored in the local database.
 

# Dear Future Me

**A charming little time-capsule audio recorder handcrafted with 3D printing and Python**

Record a short voice message today… plug the tiny USB drive into a 3D-printed "time capsule" station sometime in the future… and hear your own voice from the past.  
A playful way to send love, reminders, warnings, secrets, jokes, or hopes to your future self.

https://github.com/enricolam/Dear-Future-Me

## ✨ What it does

1. Insert a very small USB flash drive (< 32 MB total capacity)
2. A custom Python + Tkinter GUI automatically detects it
3. Wipe the drive (best-effort)
4. Press the big round **RECORD** button (or press **SPACE** / **Enter**)
5. Speak into your microphone for up to 30 seconds
6. The software records high-quality PCM audio → encodes it to MP3 using **ffmpeg**
7. Writes a fixed `config.txt` + `recording.mp3` to the drive
8. Safely ejects the drive (best-effort on Windows/macOS/Linux)
9. Take the drive out → hide it somewhere safe → rediscover it years later!

When you plug it back in years from now, any media player will play your own voice saying…  
**"Dear future me…"**

## Why this project exists

This is a love letter to three things:

- **3D printing** — design & print your own beautiful/useful/time-capsule-shaped enclosure
- **Python** — accessible, powerful, fun scripting + great audio & GUI libraries
- **The slightly sentimental, slightly silly joy** of talking to your future self

It's meant to be a beginner-to-intermediate showcase project showing how everyday tools (Python, Tkinter, sounddevice, ffmpeg, psutil) can create something meaningful and shareable.

## Features

- Modern purple-cream aesthetic ("Very Peri" + "Vanilla Ice" vibe)
- Live disk scanning for tiny USB drives (< 32 MB)
- Real microphone recording (44.1 kHz, mono, int16 PCM)
- In-memory WAV → MP3 encoding via **ffmpeg** (no temporary files)
- Fixed config file writing (easy to change later if desired)
- Countdown timer + big friendly RECORD / STOP button
- Spacebar & Enter key support for hands-free operation
- Attempts to auto-eject the drive after writing
- Graceful error messages & permission checks

## Requirements

### Hardware
- Computer with microphone
- **ffmpeg** installed and on PATH (`ffmpeg -version` should work)
- Very small USB flash drive (< 32 MB — old MP3 players, tiny promotional drives, etc.)
- (Optional but recommended) 3D printer + filament for a custom enclosure

### Software
- Python 3.8+
- Dependencies:
  ```bash
  pip install psutil sounddevice numpy
  ```

## Installation & Quick Start

1. Clone the repo
   ```bash
   git clone https://github.com/YOUR_USERNAME/dear-future-me.git
   cd dear-future-me
   ```

2. Install dependencies
   ```bash
   pip install -r requirements.txt   # create this file if needed
   ```

3. (Optional) Print a nice case!  
   Look in `/designs/` or `/stl/` folder (add your models here)

4. Run
   ```bash
   python main.py
   ```

5. Go to **Recording** tab → insert tiny USB drive → press RECORD or SPACE

## Project Structure

```
dear-future-me/
├── main.py               # main GUI + logic
├── STL/              
├── CAD/
├── IMG/
├── requirements.txt
├── LICENSE               # GPL-3.0
└── README.md
```

## License

**GNU General Public License v3.0**  
See [LICENSE](./LICENSE) for full text.

You are free to use, modify, share — just keep it open source and give credit where due.

## Contributing

Love the idea? Want to:

- Improve the GUI
- Add real dynamic config writing
- Create nice 3D-printable case designs
- Support longer recordings / better compression
- Add voice activity detection / auto-trim silence

→ Pull requests welcome!

## Acknowledgments

Built with love using:

- [Tkinter](https://docs.python.org/3/library/tkinter.html)
- [sounddevice](https://python-sounddevice.readthedocs.io/)
- [numpy](https://numpy.org/)
- [psutil](https://psutil.readthedocs.io/)
- [ffmpeg](https://ffmpeg.org/) (must be installed separately)

Inspired by the simple joy of physical time capsules + the question:  
"What would I like to hear from past-me in 5, 10, 20 years?"

Happy recording — and see you in the future!  
🌌✨

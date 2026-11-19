# Zelmu Clipping ⚡

Autonomous local pipeline for generating, editing, and uploading viral GTA 6 YouTube Shorts.

## Features
- **Top Sticky Command Bar**: Instant Produce & Upload navigation, real-time binary diagnostics (FFmpeg, yt-dlp, Ollama, YouTube), and quick watermark overlay setup.
- **Dual Pipeline Modes**:
  - **Mode A (Highlight + Karaoke)**: High-energy clips with word-level karaoke caption animations.
  - **Mode B (Transformative + Voiceover)**: Deep analysis, commentary, and Piper neural TTS voiceover.
- **Labor Illusion Telemetry**: Real-time progress bar, throughput metrics, elapsed timer, and subtask tracking.
- **Safe YouTube Batch Upload**: Google OAuth 2.0 integration with automatic private upload, batch caps (≤25), metadata safety, and upload archiving.

## Prerequisites
- Python 3.10+
- [FFmpeg](https://ffmpeg.org/download.html) (add to PATH or place in `bin/`)
- [Ollama](https://ollama.com/) with `qwen2.5:3b` model: `ollama run qwen2.5:3b`
- [Piper Voice Model](https://github.com/rhasspy/piper) (`en_US-ryan-high.onnx` & `en_US-ryan-high.onnx.json`)
- Google Cloud Console Project with YouTube Data API v3 enabled (save OAuth client ID as `client_secrets.json`)

## Setup
```bash
# Clone repository
git clone https://github.com/THEabhikmaitra/zelmu-clipping.git
cd zelmu-clipping

# Create and activate virtual environment
python -m venv venv
venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt

# Configure YouTube credentials
cp client_secrets.json.example client_secrets.json
# Add your Google OAuth credentials to client_secrets.json

# Launch application
streamlit run app.py
```

# Reader App

A web application that converts XML (JATS format), PDF, and TXT files into audio using the Kokoro TTS engine.

## Prerequisites

- Docker installed on your system (Raspberry Pi, Linux, Windows, or Mac).

## Building the Docker Image

Navigate to the project directory and run:

```bash
docker build -t reader-app .
```

This process may take a few minutes as it installs system dependencies, Python packages, and the spaCy model.

## Running the Container

### Quick Start (No Persistence)

To run the application quickly without saving data permanently:

```bash
docker run -d -p 5000:5000 --name reader-app reader-app
```

### Production Run (With Persistence)

To ensure your uploaded files, generated audio, and downloaded model weights persist across container restarts, use Docker volumes:

```bash
docker run -d -p 5000:5000 \
  -v reader_uploads:/app/uploads \
  -v reader_audio:/app/audio \
  -v reader_data:/app/data \
  -v reader_cache:/root/.cache \
  --name reader-app reader-app
```

*   `reader_uploads`: Stores uploaded files.
*   `reader_audio`: Stores generated WAV files.
*   `reader_data`: Stores the SQLite database (`app.db`).
*   `reader_cache`: Stores downloaded Kokoro model weights (saves bandwidth and startup time).

## Accessing the App

Once the container is running, open your web browser and navigate to:

```
http://<your-device-ip>:5000
```

If running locally, use: [http://localhost:5000](http://localhost:5000)

## Development

To run locally without Docker:

1.  Create a virtual environment:
    ```bash
    python -m venv .venv
    source .venv/bin/activate
    ```
2.  Install dependencies:
    ```bash
    pip install -r requirements.txt
    python -m spacy download en_core_web_sm
    ```
3.  Run the app:
    ```bash
    python app.py
    ```

"""Stand-in servers that speak the VEXYL-STT and F5-TTS wire protocols.

They let the voice service be tested end to end over real HTTP without the
3 GB of model weights the real servers need.
"""

import base64
import socket
import struct
import threading
import time
from typing import Optional

import uvicorn
from fastapi import FastAPI, File, Form, Header, UploadFile
from fastapi.responses import JSONResponse, Response


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def make_wav(seconds: float = 0.5, sample_rate: int = 16000) -> bytes:
    """A silent but structurally valid mono 16-bit WAV."""
    frames = int(seconds * sample_rate)
    data = b"\x00\x00" * frames
    header = b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
    header += b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16)
    header += b"data" + struct.pack("<I", len(data))
    return header + data


class ThreadedServer:
    """Runs a FastAPI app on a free localhost port in a background thread."""

    def __init__(self, app: FastAPI):
        self.app = app
        self.port = free_port()
        self._server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="warning")
        )
        self._thread = threading.Thread(target=self._server.run, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> "ThreadedServer":
        self._thread.start()
        deadline = time.time() + 20
        while not self._server.started and time.time() < deadline:
            if not self._thread.is_alive():
                raise RuntimeError("Test server thread died during startup.")
            time.sleep(0.02)
        if not self._server.started:
            raise RuntimeError("Test server failed to start in time.")
        return self

    def stop(self) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=10)


def make_fake_vexyl_stt(
    transcript: str = "छात्रावास के नियम क्या हैं",
    api_key: Optional[str] = None,
    polls_before_ready: int = 1,
) -> FastAPI:
    """A VEXYL-STT batch API: submit returns a job id, results 202 then 200."""
    app = FastAPI()
    app.state.jobs = {}
    app.state.received = []

    def authorized(supplied: Optional[str]) -> bool:
        return api_key is None or supplied == api_key

    @app.get("/health")
    def health(x_api_key: Optional[str] = Header(None)):
        if not authorized(x_api_key):
            return JSONResponse({"detail": "unauthorized"}, status_code=401)
        return {
            "status": "ok",
            "model": "indic-conformer-600m-multilingual",
            "device": "cpu",
            "decode_mode": "ctc",
            "active_sessions": 0,
        }

    @app.post("/batch/transcribe", status_code=201)
    async def submit(
        file: UploadFile = File(...),
        language_code: str = Form("hi-IN"),
        x_api_key: Optional[str] = Header(None),
    ):
        if not authorized(x_api_key):
            return JSONResponse({"detail": "unauthorized"}, status_code=401)

        audio = await file.read()
        app.state.received.append(
            {"filename": file.filename, "size": len(audio), "audio": audio, "language": language_code}
        )

        job_id = f"batch_{len(app.state.jobs) + 1:04d}"
        app.state.jobs[job_id] = {"polls": 0, "language": language_code}
        return {
            "job_id": job_id,
            "status": "queued",
            "language": language_code,
            "audio_duration": round(len(audio) / 32000, 2),
        }

    @app.get("/batch/result/{job_id}")
    def result(job_id: str, x_api_key: Optional[str] = Header(None)):
        if not authorized(x_api_key):
            return JSONResponse({"detail": "unauthorized"}, status_code=401)

        job = app.state.jobs.get(job_id)
        if job is None:
            return JSONResponse({"detail": "unknown job"}, status_code=404)

        job["polls"] += 1
        if job["polls"] <= polls_before_ready:
            return JSONResponse({"status": "processing"}, status_code=202)

        return {
            "job_id": job_id,
            "status": "completed",
            "text": transcript,
            "language": job["language"],
            "audio_duration": 1.5,
        }

    return app


def make_fake_hindi_tts(as_base64: bool = False) -> FastAPI:
    """An F5-TTS style server hosting Futurix-AI/Hindi-TTS at 24 kHz."""
    app = FastAPI()
    app.state.requests = []

    @app.get("/health")
    def health():
        return {"status": "ok", "model": "Futurix-AI/Hindi-TTS", "sample_rate": 24000}

    @app.post("/tts")
    async def tts(payload: dict):
        app.state.requests.append(payload)
        audio = make_wav(seconds=0.4, sample_rate=24000)
        if as_base64:
            return {"audio": base64.b64encode(audio).decode("ascii"), "sample_rate": 24000}
        return Response(content=audio, media_type="audio/wav")

    return app

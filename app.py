import os
import base64
import json
import threading
from flask import Flask, render_template_string
from flask_sockets import Sockets
import requests
import websocket # websocket-client

# --- Configuration ---
# The API key is loaded from an environment variable for security.
# Set this in your Render dashboard.
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")

if not ELEVENLABS_API_KEY:
    raise ValueError("ELEVENLABS_API_KEY environment variable not set. Please set it in your deployment environment.")

# ElevenLabs Voice ID and API URLs
VOICE_ID = "21m00Tcm4TlvDq8ikWAM" # A default voice, e.g., "Rachel"
TTS_URL = f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}/stream"
STT_URL = "wss://api.elevenlabs.io/v1/speech-to-text/stream-v2"

# --- Flask App Initialization ---
app = Flask(__name__)
sockets = Sockets(app)

# --- Frontend HTML, CSS, JavaScript (Embedded) ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Live AI Voice Chat</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@400;600&display=swap');
        :root {
            --bg-color: #1a1a2e; --primary-color: #16213e; --secondary-color: #0f3460;
            --accent-color: #e94560; --text-color: #dcdcdc; --font-family: 'Poppins', sans-serif;
        }
        body {
            font-family: var(--font-family); background: var(--bg-color); color: var(--text-color);
            display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0;
            -webkit-font-smoothing: antialiased; -moz-osx-font-smoothing: grayscale;
        }
        .container {
            background: var(--primary-color); padding: 2rem; border-radius: 20px;
            box-shadow: 0 10px 40px rgba(0, 0, 0, 0.4); width: 100%; max-width: 600px;
            text-align: center; border: 1px solid var(--secondary-color);
        }
        h1 { font-size: 2.2rem; color: #fff; margin-bottom: 1rem; }
        .status-container {
            background: var(--secondary-color); border-radius: 10px; padding: 1rem;
            margin: 1.5rem 0; min-height: 50px; display: flex; align-items: center;
            justify-content: center; transition: background 0.3s;
        }
        #status { font-size: 1.1rem; font-weight: 600; }
        .dot-flashing {
            position: relative; width: 10px; height: 10px; border-radius: 5px;
            background-color: var(--accent-color); color: var(--accent-color);
            animation: dotFlashing 1s infinite linear alternate; animation-delay: .5s;
        }
        .dot-flashing::before, .dot-flashing::after {
            content: ''; display: inline-block; position: absolute; top: 0;
        }
        .dot-flashing::before {
            left: -15px; width: 10px; height: 10px; border-radius: 5px;
            background-color: var(--accent-color); color: var(--accent-color);
            animation: dotFlashing 1s infinite alternate; animation-delay: 0s;
        }
        .dot-flashing::after {
            left: 15px; width: 10px; height: 10px; border-radius: 5px;
            background-color: var(--accent-color); color: var(--accent-color);
            animation: dotFlashing 1s infinite alternate; animation-delay: 1s;
        }
        @keyframes dotFlashing { 0% { background-color: var(--accent-color); } 50%, 100% { background-color: rgba(233, 69, 96, 0.2); } }
        #recordButton {
            background: var(--accent-color); color: white; border: none; padding: 1rem 2.5rem;
            border-radius: 50px; font-size: 1.2rem; font-weight: 600; cursor: pointer;
            transition: all 0.3s ease; box-shadow: 0 4px 15px rgba(233, 69, 96, 0.4);
        }
        #recordButton:hover { transform: translateY(-3px); box-shadow: 0 6px 20px rgba(233, 69, 96, 0.6); }
        #recordButton.recording { background: #0f3460; box-shadow: inset 0 4px 10px rgba(0,0,0,0.4); }
    </style>
</head>
<body>
    <audio id="audioPlayer" autoplay></audio>
    <div class="container">
        <h1>Live AI Voice Chat</h1>
        <div class="status-container" id="statusContainer">
            <div id="status">Press and Hold to Speak</div>
        </div>
        <button id="recordButton">Hold to Speak</button>
    </div>

    <script>
        document.addEventListener('DOMContentLoaded', () => {
            const recordButton = document.getElementById('recordButton');
            const statusDiv = document.getElementById('status');
            const audioPlayer = document.getElementById('audioPlayer');

            let isRecording = false;
            let mediaRecorder;
            let socket;
            let mediaSource = new MediaSource();
            let sourceBuffer;
            let audioQueue = [];
            let isPlaying = false;
            
            const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const wsURL = `${wsProtocol}//${location.host}/ws/live-chat`;

            audioPlayer.src = URL.createObjectURL(mediaSource);
            mediaSource.addEventListener('sourceopen', () => {
                try {
                    sourceBuffer = mediaSource.addSourceBuffer('audio/mpeg');
                    sourceBuffer.addEventListener('updateend', processAudioQueue);
                } catch (e) { console.error('Error adding source buffer:', e); }
            });

            const connectWebSocket = () => {
                socket = new WebSocket(wsURL);
                socket.binaryType = 'arraybuffer';

                socket.onopen = () => console.log("WebSocket connected.");
                socket.onclose = () => console.log("WebSocket disconnected.");
                socket.onerror = (err) => console.error("WebSocket error:", err);

                socket.onmessage = (event) => {
                    if (typeof event.data === 'string') {
                        const message = JSON.parse(event.data);
                        if (message.status) {
                            updateStatus(message.status, message.indicator);
                        }
                    } else if (event.data instanceof ArrayBuffer) {
                        audioQueue.push(event.data);
                        if (!isPlaying) {
                            isPlaying = true;
                            processAudioQueue();
                        }
                    }
                };
            };

            const processAudioQueue = () => {
                if (!sourceBuffer || sourceBuffer.updating || audioQueue.length === 0) {
                    if (audioQueue.length === 0) isPlaying = false;
                    return;
                }
                sourceBuffer.appendBuffer(audioQueue.shift());
            };
            
            const updateStatus = (text, indicator = false) => {
                statusDiv.innerHTML = indicator ? '<div class="dot-flashing"></div>' : text;
            };

            const startRecording = () => {
                if (!socket || socket.readyState !== WebSocket.OPEN) connectWebSocket();
                
                navigator.mediaDevices.getUserMedia({ audio: true })
                    .then(stream => {
                        mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm; codecs=opus' });
                        mediaRecorder.ondataavailable = event => {
                            if (event.data.size > 0 && socket && socket.readyState === WebSocket.OPEN) {
                                socket.send(event.data);
                            }
                        };
                        mediaRecorder.start(250); // Send audio chunks every 250ms
                        isRecording = true;
                        recordButton.classList.add('recording');
                        recordButton.textContent = 'Release to Stop';
                        updateStatus('Listening...', true);
                    }).catch(err => {
                        console.error('Error getting media stream:', err);
                        updateStatus('Error: Microphone access denied.');
                    });
            };

            const stopRecording = () => {
                if (mediaRecorder && isRecording) {
                    mediaRecorder.stop();
                    isRecording = false;
                    recordButton.classList.remove('recording');
                    recordButton.textContent = 'Hold to Speak';
                    if (socket && socket.readyState === WebSocket.OPEN) {
                        socket.send(JSON.stringify({ "end_stream": true }));
                    }
                }
            };
            
            recordButton.addEventListener('mousedown', startRecording);
            recordButton.addEventListener('mouseup', stopRecording);
            recordButton.addEventListener('touchstart', startRecording, { passive: false });
            recordButton.addEventListener('touchend', stopRecording);
            
            connectWebSocket();
        });
    </script>
</body>
</html>
"""

# --- Backend WebSocket Logic ---
class SpeechToTextHandler:
    """Manages the connection to ElevenLabs STT WebSocket."""
    def __init__(self, client_ws):
        self.client_ws = client_ws
        self.stt_ws = None
        self.transcript_buffer = []
        self.stt_thread = threading.Thread(target=self._run_stt)

    def connect(self):
        """Establishes the connection to ElevenLabs STT."""
        self.stt_ws = websocket.create_connection(STT_URL)
        auth_message = { "xi_api_key": ELEVENLABS_API_KEY, "model_id": "eleven_multilingual_v2" }
        self.stt_ws.send(json.dumps(auth_message))
        self.stt_thread.start()

    def send_audio(self, audio_chunk):
        """Sends an audio chunk to ElevenLabs."""
        if self.stt_ws:
            payload = json.dumps({"audio": base64.b64encode(audio_chunk).decode()})
            self.stt_ws.send(payload)

    def _run_stt(self):
        """Listens for messages from ElevenLabs and processes them."""
        while True:
            try:
                message = self.stt_ws.recv()
                data = json.loads(message)
                if data.get("is_final"):
                    full_transcript = "".join(self.transcript_buffer) + data.get("text", "")
                    if full_transcript.strip():
                        self.client_ws.send(json.dumps({"status": "Thinking...", "indicator": True}))
  

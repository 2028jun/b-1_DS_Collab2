#STT.py
from openai import OpenAI
import sounddevice as sd
import scipy.io.wavfile as wav
import numpy as np
import tempfile
import os

from ament_index_python.packages import get_package_share_directory
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(".env"))
openai_api_key = os.getenv("OPENAI_API_KEY")

class STT:
    def __init__(self, openai_api_key):
        self.client = OpenAI(api_key=openai_api_key)
        self.openai_api_key = openai_api_key
        self.duration = 5  # seconds
        self.samplerate = 16000  # Whisper는 16kHz를 선호

    def speech2text(self):
        # 녹음 설정
        audio = sd.rec(
            int(self.duration * self.samplerate),
            samplerate=self.samplerate,
            channels=1,
            dtype="int16",
        )
        sd.wait()

        # 임시 WAV 파일 저장
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_wav:
            wav.write(temp_wav.name, self.samplerate, audio)

            # Whisper API 호출
            with open(temp_wav.name, "rb") as f:
                transcript = self.client.audio.transcriptions.create(
                    model="whisper-1", file=f)

        return transcript.text

if __name__ == "__main__":
    stt = STT(openai_api_key)
    output_message = stt.speech2text()

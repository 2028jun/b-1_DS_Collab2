#vad_stt.py
import os
import tempfile
from collections import deque

import numpy as np
import scipy.io.wavfile as wav
import sounddevice as sd
from openai import OpenAI

MIN_NOISE_THRESHOLD = 300

class VadSTT:
    def __init__(
        self,
        openai_api_key,
        device_index=None,     # 마이크 index
        samplerate=16000,      # 주파수
        chunk_sec=0.2,         # 청크 조각 0.1초
        silence_sec=0.3,       # 0.3초 동안 조용하면 녹음이 끝난 것으로 판단
        max_record_sec=8.0,    # 녹음이 8초를 넘으면 강제 종료
        start_timeout_sec=12.0,  # 12초 동안 녹음이 시작 안 되면 빈 결과 반환
    ):
        self.client = OpenAI(api_key=openai_api_key)
        self.device_index = device_index       # 마이크 index
        self.samplerate = samplerate           # 주파수 16000
        self.chunk_sec = chunk_sec             # 청크 조각 0.1초
        self.chunk_size = int(samplerate * chunk_sec)       # 0.1초의 청크 사이즈 = 1600
        self.silence_chunks = max(1, int(silence_sec / chunk_sec))  # 3청크 (0.3초)
        self.max_chunks = max(1, int(max_record_sec / chunk_sec))   # 80 청크(8초)
        self.start_timeout_chunks = max(1, int(start_timeout_sec / chunk_sec))  # 120 청크(12초)
        self.preroll = deque(maxlen=max(1, int(0.4 / chunk_sec)))   # 4개의 청크를 담을 덱 생성

        if self.device_index is not None:           # 마이크 장치 index를 지정해두지 않으면 기본 장치로 사용(스피커 장치는 None -> 기본장치 사용)
            sd.default.device = (self.device_index, None)

    def speech2text(self) -> str:
        audio = self._record_until_silence()     # 오디오 데이터 받아옴
        if audio is None or len(audio) == 0:     # 녹음이 안됬을 경우
            return ""

        temp_path = None

        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_wav:      # 오디오 데이터 임시 파일 생성
                wav.write(temp_wav.name, self.samplerate, audio)
                temp_path = temp_wav.name

            with open(temp_path, "rb") as f:        # whosper-1 모델을 불러와서 입력된 오디오 데이터를 텍스트로 변환
                transcript = self.client.audio.transcriptions.create(
                    model="whisper-1",
                    file=f,
                    language="ko",
                )
            return transcript.text      # 변환된 텍스트를 return

        except Exception as e:
            print(f"❌ Whisper 변환 실패: {e}")
            return ""

        finally:
            if temp_path is not None:
                try:
                    os.unlink(temp_path)    # 임시 파일 삭제
                except OSError:
                    pass

    def _record_until_silence(self):
        threshold = MIN_NOISE_THRESHOLD  # 변경 지점: noise_floor 기반 계산 → 고정 상수

        frames = []
        silence_count = 0
        started = False
        total_chunks = 0

        with sd.InputStream(
            samplerate=self.samplerate,
            channels=1,
            dtype="int16",
            blocksize=self.chunk_size,
            device=self.device_index,
        ) as stream:
            while total_chunks < self.start_timeout_chunks + self.max_chunks:   # 200 청크 이하 시(20초 동안)
                chunk, _ = stream.read(self.chunk_size)     #  0.1초 분량 오디오 데이터(2차원)
                chunk = chunk.reshape(-1).copy()        # 1차원으로 변환
                level = float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2)))  # 오디오 샘플의 실효값 계산

                print(f"\r레벨: {level:7.1f}  기준(threshold): {threshold:.1f}  {'🔊 음성 녹음중' if level >= threshold else '   '}", end="", flush=True)

                if not started:
                    self.preroll.append(chunk)  # 0.1초 오디오 데이터를 덱에 추가
                    total_chunks += 1

                    if level >= threshold:      # 0.1초 오디오 데이터의 실효값이 기준값을 넘으면(소리가 클 때)
                        started = True          # 음성 녹음 시작
                        frames.extend(self.preroll)     # 오디오 데이터를 리스트에 추가
                        silence_count = 0       # 음성 녹음 X 카운트 초기화(음성 녹음을 시작했으므로)
                    elif total_chunks >= self.start_timeout_chunks:
                        # 제한 시간 안에 음성 녹음이 시작되지 않음
                        return None
                    continue

                frames.append(chunk)    # 오디오 데이터를 리스트에 추가
                total_chunks += 1

                if level < threshold:   # 기준값보다 실효값이 낮을때(소리가 작을 때)
                    silence_count += 1  # 음성 녹음 X 카운트 증가
                else:                   # 기준값보다 실효값이 클 때(계속 말하고 있을 때)
                    silence_count = 0   # 음성 녹음 X 카운트 초기화(말하는 중이므로)

                if silence_count >= self.silence_chunks:    # 0.3초 동안 말이 없으면
                    break   

                if len(frames) >= self.max_chunks:      # 음성 녹음이 8초를 넘으면
                    break

        if not frames:
            return None

        return np.concatenate(frames).astype(np.int16)  # 쪼개진 청크들을 합쳐 오디오 데이터로 return
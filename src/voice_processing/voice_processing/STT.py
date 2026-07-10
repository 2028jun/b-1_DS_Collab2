#vad_stt.py
"""에너지 기반 VAD(Voice Activity Detection) 녹음 + Whisper STT.

기존 STT.py(고정 5초 스냅샷)의 문제(발화가 경계에서 잘림, 긴 문장이 잘림)를
해결하기 위해 발화 시작을 실시간으로 감지해서 녹음을 시작하고,
일정 시간 무음이 이어지면 녹음을 종료하는 방식으로 동작한다.


"""
import os
import tempfile
from collections import deque

import numpy as np
import scipy.io.wavfile as wav
import sounddevice as sd
from openai import OpenAI

# 이 크기(RMS) 이상이어야 "발화"로 인정한다.
# 값을 낮추면 더 작은 소리도 발화로 인식(민감), 높이면 더 큰 소리만 인식(둔감).
# 튜닝할 때는 이 숫자 하나만 고치면 된다.
MIN_NOISE_THRESHOLD = 150.0


class VadSTT:
    """발화 구간만 녹음해서 Whisper로 변환하는 STT."""

    def __init__(
        self,
        openai_api_key,
        device_index=None,
        samplerate=16000,
        chunk_sec=0.1,
        silence_sec=0.3,       # 이 시간 동안 조용하면 발화가 끝난 것으로 판단
        max_record_sec=8.0,    # 한 발화가 이 시간을 넘으면 강제 종료 (기존 5초 제한 완화)
        start_timeout_sec=12.0,  # 이 시간 동안 발화가 시작 안 되면 포기하고 빈 결과 반환
    ):
        self.client = OpenAI(api_key=openai_api_key)
        self.device_index = device_index
        self.samplerate = samplerate
        self.chunk_sec = chunk_sec
        self.chunk_size = int(samplerate * chunk_sec)
        self.silence_chunks = max(1, int(silence_sec / chunk_sec))
        self.max_chunks = max(1, int(max_record_sec / chunk_sec))
        self.start_timeout_chunks = max(1, int(start_timeout_sec / chunk_sec))
        # 발화 시작 직전 오디오도 놓치지 않도록 0.4초 분량을 미리 버퍼링
        self.preroll = deque(maxlen=max(1, int(0.4 / chunk_sec)))

        if self.device_index is not None:
            sd.default.device = (self.device_index, None)

        # 노이즈 플로어는 노드 시작 시 1회만 측정한다.
        # (매 발화마다 재측정하면 사이클마다 0.5초씩 불필요한 지연이 생긴다)
        # 참고: 지금은 판단에 직접 쓰이지 않고, 실제 배경소음 수준을 파악해서
        # MIN_NOISE_THRESHOLD 값을 얼마로 잡을지 정하는 데 참고용으로만 사용한다.
        self._noise_floor = self._estimate_noise_floor()
        print(f"[VadSTT] 측정된 noise_floor={self._noise_floor:.1f}  적용 threshold(고정값)={MIN_NOISE_THRESHOLD:.1f}")

    def refresh_noise_floor(self):
        """주변 소음 수준이 크게 바뀐 것 같을 때 수동으로 재측정하고 싶으면 호출."""
        self._noise_floor = self._estimate_noise_floor()
        print(f"[VadSTT] noise_floor 재측정: {self._noise_floor:.1f}")

    def speech2text(self) -> str:
        """발화 구간을 녹음해서 텍스트로 변환. 실패/무음이면 빈 문자열 반환."""
        audio = self._record_until_silence()
        if audio is None or len(audio) == 0:
            return ""

        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_wav:
                wav.write(temp_wav.name, self.samplerate, audio)
                temp_path = temp_wav.name

            with open(temp_path, "rb") as f:
                transcript = self.client.audio.transcriptions.create(
                    model="whisper-1",
                    file=f,
                    language="ko",
                )
            return transcript.text

        except Exception as e:
            # Whisper API 호출 실패(네트워크 오류 등)로 노드 전체가 죽지 않도록 방어.
            # TODO: ROS2 노드 컨텍스트에서 사용할 때는 print 대신 get_logger().error()로 교체 권장
            print(f"❌ Whisper 변환 실패: {e}")
            return ""

        finally:
            if temp_path is not None:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass

    def _record_until_silence(self):
        """발화 시작을 감지하고, 무음이 일정 시간 이어지면 녹음을 마친다."""
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
            while total_chunks < self.start_timeout_chunks + self.max_chunks:
                chunk, _ = stream.read(self.chunk_size)
                chunk = chunk.reshape(-1).copy()
                level = float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2)))

                print(f"\r레벨: {level:7.1f}  기준(threshold): {threshold:.1f}  {'🔊 발화중' if level >= threshold else '   '}", end="", flush=True)

                if not started:
                    self.preroll.append(chunk)
                    total_chunks += 1

                    if level >= threshold:
                        started = True
                        frames.extend(self.preroll)
                        silence_count = 0
                    elif total_chunks >= self.start_timeout_chunks:
                        # 제한 시간 안에 발화가 시작되지 않음
                        return None
                    continue

                frames.append(chunk)
                total_chunks += 1

                if level < threshold:
                    silence_count += 1
                else:
                    silence_count = 0

                if silence_count >= self.silence_chunks:
                    break

                if len(frames) >= self.max_chunks:
                    break

        if not frames:
            return None

        return np.concatenate(frames).astype(np.int16)

    def _estimate_noise_floor(self):
        """0.5초간 오디오를 측정해서 현재 주변 소음 수준(중앙값)을 추정."""
        levels = []
        with sd.InputStream(
            samplerate=self.samplerate,
            channels=1,
            dtype="int16",
            blocksize=self.chunk_size,
            device=self.device_index,
        ) as stream:
            for _ in range(max(1, int(0.5 / self.chunk_sec))):
                chunk, _ = stream.read(self.chunk_size)
                chunk = chunk.reshape(-1)
                level = float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2)))
                levels.append(level)

        return float(np.median(levels)) if levels else 100.0
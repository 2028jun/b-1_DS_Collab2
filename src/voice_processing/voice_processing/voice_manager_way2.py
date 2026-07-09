#voice_manager_way2.py
import os
import tempfile
from collections import deque

import numpy as np
import rclpy
import scipy.io.wavfile as wav
import sounddevice as sd
from openai import OpenAI
from rclpy.node import Node

from store_interfaces.srv import OrderProduct, StartAdminAuth
from voice_processing.env_utils import load_openai_api_key
from voice_processing.ModeClassifier import ModeClassifier
from voice_processing.OrderProcessor import OrderProcessor
from voice_processing.wakeup_word import WakeupWord


class VadSTT:
    """Simple energy-based VAD recorder followed by Whisper transcription."""

    def __init__(
        self,
        openai_api_key,
        device_index=None,
        samplerate=16000,
        chunk_sec=0.1,
        silence_sec=0.8,
        max_record_sec=6.0,
        start_timeout_sec=12.0,
    ):
        self.client = OpenAI(api_key=openai_api_key)
        self.device_index = device_index
        self.samplerate = samplerate
        self.chunk_sec = chunk_sec
        self.chunk_size = int(samplerate * chunk_sec)
        self.silence_chunks = max(1, int(silence_sec / chunk_sec))
        self.max_chunks = max(1, int(max_record_sec / chunk_sec))
        self.start_timeout_chunks = max(1, int(start_timeout_sec / chunk_sec))
        self.preroll = deque(maxlen=max(1, int(0.4 / chunk_sec)))

        if self.device_index is not None:
            sd.default.device = (self.device_index, None)

    def speech2text(self):
        audio = self._record_until_silence()
        if audio is None or len(audio) == 0:
            return ""

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_wav:
            wav.write(temp_wav.name, self.samplerate, audio)
            temp_path = temp_wav.name

        try:
            with open(temp_path, "rb") as f:
                transcript = self.client.audio.transcriptions.create(
                    model="whisper-1",
                    file=f,
                    language="ko",
                )
            return transcript.text
        finally:
            try:
                os.unlink(temp_path)
            except OSError:
                pass

    def _record_until_silence(self):
        noise_floor = self._estimate_noise_floor()
        threshold = max(300.0, noise_floor * 3.0)

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

                if not started:
                    self.preroll.append(chunk)
                    total_chunks += 1

                    if level >= threshold:
                        started = True
                        frames.extend(self.preroll)
                        silence_count = 0
                    elif total_chunks >= self.start_timeout_chunks:
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

        return np.concatenate(frames).astype(np.int16)

    def _estimate_noise_floor(self):
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


class VoiceManagerWay2Node(Node):
    """VAD voice loop version.

    The microphone waits for speech, records until silence, and then sends only
    that speech segment to Whisper. This reduces timing burden for the user.
    """

    def __init__(self):
        super().__init__("voice_manager_way2_node")

        openai_api_key = load_openai_api_key()
        if openai_api_key is None:
            raise ValueError("OPENAI_API_KEY가 .env 파일에서 로드되지 않았습니다.")

        self.declare_parameter("mic_device_index", -1)
        self.declare_parameter("vad_silence_sec", 0.8)
        self.declare_parameter("vad_start_timeout_sec", 12.0)
        self.declare_parameter("vad_max_record_sec", 6.0)

        mic_device_index = self.get_parameter("mic_device_index").value
        device_index = None if mic_device_index < 0 else mic_device_index

        self.stt = VadSTT(
            openai_api_key=openai_api_key,
            device_index=device_index,
            silence_sec=self.get_parameter("vad_silence_sec").value,
            start_timeout_sec=self.get_parameter("vad_start_timeout_sec").value,
            max_record_sec=self.get_parameter("vad_max_record_sec").value,
        )
        self.wakeup = WakeupWord()
        self.mode_classifier = ModeClassifier()
        self.order_processor = OrderProcessor()

        self.cli_admin_auth = self.create_client(StartAdminAuth, "/start_admin_auth")
        self.cli_order_product = self.create_client(OrderProduct, "/order_product")

        self.get_logger().info("Voice manager way2 시작: 말소리 구간만 녹음해서 인식합니다.")

    def run_forever(self):
        while rclpy.ok():
            rclpy.spin_once(self, timeout_sec=0.0)

            self.get_logger().info("호출어 대기 중입니다. 편돌아라고 말해주세요.")
            wake_text = self.stt.speech2text().strip()
            self.get_logger().info(f"호출어 STT 결과: {wake_text}")

            if not wake_text:
                self.get_logger().warn("제한 시간 안에 호출어 음성이 들어오지 않았습니다.")
                continue

            if not self.wakeup.is_wakeup(wake_text):
                self.get_logger().info("호출어가 아니므로 다시 대기합니다.")
                continue

            self.get_logger().info("편돌아 호출어 감지됨. 명령어를 말해주세요.")
            command_text = self.stt.speech2text().strip()
            self.get_logger().info(f"명령어 STT 결과: {command_text}")

            if not command_text:
                self.get_logger().warn("명령어 음성이 인식되지 않았습니다.")
                continue

            self.handle_command(command_text)

    def handle_command(self, command_text):
        mode = self.mode_classifier.classify(command_text)

        if mode == "ADMIN":
            self.get_logger().info("관리자 모드로 전환합니다.")
            self.request_admin_auth_manager("관리자")
        elif mode == "SERVICE":
            self.get_logger().info("서비스 모드로 전환합니다.")
            self.request_admin_auth_manager("사용자")
        else:
            self.request_main_order_manager(command_text)

    def request_admin_auth_manager(self, voice_text):
        if not self.cli_admin_auth.wait_for_service(timeout_sec=3.0):
            self.get_logger().error("관리자 인증 매니저 노드가 켜져있지 않습니다.")
            return

        req = StartAdminAuth.Request()
        req.voice_text = voice_text
        self.cli_admin_auth.call_async(req)

    def request_main_order_manager(self, voice_text):
        if not self.cli_order_product.wait_for_service(timeout_sec=3.0):
            self.get_logger().error("메인 매니저 노드가 오프라인 상태입니다.")
            return

        parsed_order = self.order_processor.run(voice_text)
        self.get_logger().info(f"주문 목록: {parsed_order}")

        if not parsed_order:
            self.get_logger().warn("인식된 상품명이 없습니다. 주문을 취소합니다.")
            return

        req = OrderProduct.Request()
        req.product_name = list(parsed_order.keys())
        req.quantity = list(parsed_order.values())
        self.cli_order_product.call_async(req)


def main(args=None):
    rclpy.init(args=args)
    node = VoiceManagerWay2Node()
    try:
        node.run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()

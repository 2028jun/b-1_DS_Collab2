#voice_manager.py
"""편의점 로봇 음성 매니저 노드 (VAD 업그레이드 버전).
 
변경 사항 (기존 voice_manager.py 대비):
1. STT.py(고정 5초 스냅샷) → vad_stt.VadSTT(발화 감지 기반 가변 길이 녹음)
   - "편돌아" 호출어가 5초 경계에서 잘려 인식 안 되던 문제
   - 긴 주문 문장이 5초에서 잘리던 문제
   두 가지를 모두 근본 원인(고정 길이 녹음)에서 해결.
2. create_timer(0.1, ...) 기반 콜백 루프 → 별도 데몬 스레드에서 음성 루프 실행
   - VadSTT.speech2text()는 발화가 끝날 때까지 블로킹되는 함수라
     timer 콜백 안에 있으면 그 동안 ROS2 executor가 다른 콜백을
     전혀 처리하지 못한다 (서비스 응답 등을 놓칠 수 있음).
   - 음성 루프를 별도 스레드로 분리하고, 메인 스레드는 정상적으로
     rclpy.spin()을 돌려 ROS2 통신을 처리하도록 구조를 바꿨다.
"""
import os
import threading
from pathlib import Path
 
import rclpy
from rclpy.node import Node
from dotenv import load_dotenv
 
from voice_processing.wakeup_word import WakeupWord
from voice_processing.STT import VadSTT
from voice_processing.ModeClassifier import ModeClassifier
from voice_processing.OrderProcessor import OrderProcessor
 
from store_interfaces.srv import StartAdminAuth, OrderProduct
 
 
class VoiceManagerNode(Node):
    def __init__(self):
        super().__init__('voice_manager_node')
 
        # 1. 환경 변수 로드
        #    (기존에 이미 이 폴더에서 돌리던 .env를 그대로 사용.
        #     wakeup_word.py / ModeClassifier.py / Order_Extractor.py 등
        #     다른 모듈들과 동일한 방식으로 통일)
        current_dir = Path(__file__).resolve().parent
        env_path = current_dir / ".env"
        load_dotenv(dotenv_path=env_path)
 
        openai_api_key = os.getenv("OPENAI_API_KEY")
        if openai_api_key is None:
            raise ValueError("OPENAI_API_KEY가 .env 파일에서 로드되지 않았습니다.")
 
        # 2. 마이크 인덱스를 하드코딩(PC_MIC_INDEX = 5) 대신 파라미터로 관리
        #    → launch 파일에서 환경별로 다르게 지정 가능
        self.declare_parameter("mic_device_index", 5)
        self.declare_parameter("vad_silence_sec", 0.8)
        self.declare_parameter("vad_max_record_sec", 8.0)
        self.declare_parameter("vad_start_timeout_sec", 12.0)
 
        mic_device_index = self.get_parameter("mic_device_index").value
        device_index = None if mic_device_index < 0 else mic_device_index
 
        # 3. 모듈 초기화
        self.stt = VadSTT(
            openai_api_key,
            device_index=device_index,
            silence_sec=self.get_parameter("vad_silence_sec").value,
            max_record_sec=self.get_parameter("vad_max_record_sec").value,
            start_timeout_sec=self.get_parameter("vad_start_timeout_sec").value,
        )
        self.wakeup = WakeupWord()
        self.mode_classifier = ModeClassifier()
        self.order_processor = OrderProcessor()
 
        # 4. 서비스 클라이언트
        self.cli_admin_auth = self.create_client(StartAdminAuth, '/start_admin_auth')
        self.cli_order_product = self.create_client(OrderProduct, '/order_product')
 
        # 5. 음성 루프는 별도 데몬 스레드에서 실행
        self._voice_thread = threading.Thread(target=self._voice_loop, daemon=True)
        self._voice_thread.start()
 
        self.get_logger().info("음성 매니저 노드 시작 (VAD 기반)")
 
    # ------------------------------------------------------------------
    # 음성 루프 (별도 스레드에서 실행됨)
    # ------------------------------------------------------------------
    def _voice_loop(self):
        while rclpy.ok():
            wake_text = self.stt.speech2text().strip()
 
            if not wake_text:
                # 제한 시간 안에 발화가 없었음 → 다시 대기
                continue
 
            if not self.wakeup.is_wakeup(wake_text):
                # 발화는 있었지만 "편돌아"가 아님 → 다시 대기
                continue
 
            self.get_logger().info("✅ 편돌아 호출어 감지됨")
 
            command_text = self.stt.speech2text().strip()
            if not command_text:
                self.get_logger().warn("음성이 인식되지 않았습니다.")
                continue
 
            self._handle_command(command_text)
 
    def _handle_command(self, command_text: str):
        mode = self.mode_classifier.classify(command_text)  # 주문 or 모드 변경 판별
 
        if mode == "SERVICE":
            self.get_logger().info("서비스 모드로 전환합니다.")
            self.request_admin_auth_manager("사용자")       # 사용자 모드로 변경 요청
        elif mode == "WAREHOUSING":
            self.get_logger().info("입고 모드로 전환합니다.")
            self.request_admin_auth_manager("입고")       # 입고 모드로 변경 요청
        else:
            self.request_main_order_manager(command_text)
 
    # ------------------------------------------------------------------
    # 서비스 요청 (기존 로직과 동일, 변경 없음)
    # ------------------------------------------------------------------
    def request_admin_auth_manager(self, voice_text):
        if not self.cli_admin_auth.wait_for_service(timeout_sec=3.0):
            self.get_logger().error("관리자 인증 매니저 노드가 켜져있지 않습니다.")
            return
 
        req = StartAdminAuth.Request()
        req.voice_text = voice_text
        self.cli_admin_auth.call_async(req)     # 모드 변환 요청
 
    def request_main_order_manager(self, voice_text):
        if not self.cli_order_product.wait_for_service(timeout_sec=3.0):
            self.get_logger().error("메인 매니저 노드가 오프라인 상태입니다.")
            return
 
        parsed_order = self.order_processor.run(voice_text)     # 주문 목록 인식
        self.get_logger().info(f"주문 목록: {parsed_order}")
 
        if not parsed_order:
            self.get_logger().warn("❌ 인식된 상품명이 없습니다. 주문을 취소합니다.")
            return
 
        # 메인 매니저 노드의 규격에 맞게 리스트 형태로 포장
        req = OrderProduct.Request()
        req.product_name = list(parsed_order.keys())     # ['과자', '물']
        req.quantity = list(parsed_order.values())        # [2, 1]
 
        self.cli_order_product.call_async(req)  # 비동기로 던지기
 
 
def main(args=None):
    rclpy.init(args=args)
    node = VoiceManagerNode()
    try:
        # 음성 루프는 별도 스레드에서 이미 돌고 있으므로,
        # 메인 스레드는 정상적으로 spin해서 서비스 응답 등 ROS2 통신을 처리한다.
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()
 
 
if __name__ == '__main__':
    main()
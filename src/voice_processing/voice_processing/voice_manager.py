import os
import rclpy
from rclpy.node import Node
from dotenv import load_dotenv
from pathlib import Path

from voice_processing.wakeup_word import WakeupWord
from voice_processing.STT import STT
from voice_processing.ModeClassifier import ModeClassifier
from voice_processing.OrderProcessor import OrderProcessor

from store_interfaces.srv import StartAdminAuth, OrderProduct

class VoiceManagerNode(Node):
    def __init__(self):
        super().__init__('voice_manager_node')

        current_dir = Path(__file__).resolve().parent
        env_path = current_dir / ".env"
        
        # 1. 환경 변수 세팅 및 오디오 모듈 초기화
        load_dotenv(dotenv_path=env_path)
        openai_api_key = os.getenv("OPENAI_API_KEY")
        if openai_api_key is None:
            raise ValueError("OPENAI_API_KEY가 .env 파일에서 로드되지 않았습니다.")
            
        self.stt = STT(openai_api_key)
        self.wakeup = WakeupWord()
        self.mode_classifier = ModeClassifier()
        self.order_processor = OrderProcessor() 

        self.cli_admin_auth = self.create_client(StartAdminAuth, '/start_admin_auth')

        self.cli_order_product = self.create_client(OrderProduct, '/order_product')

        self.is_woken_up = False
        
        self.timer = self.create_timer(0.1, self.voice_lifecycle_loop)  # 0.1초마다 음성 인식 -> 음성이 쌓여서 텍스트 체크 가능

        self.get_logger().info("메인 매니저 노드 시작") # 음성 인식 노드 시작

    def voice_lifecycle_loop(self):
        if not self.is_woken_up:
            wake_text = self.stt.speech2text()
            if wake_text:   # 음성을 인식하면
                if self.wakeup.is_wakeup(wake_text):
                    self.get_logger().info("✅ 편돌아 호출어 감지됨")
                    self.is_woken_up = True
                    
        else:
            command_text = self.stt.speech2text()   # 음성 명령 인식
            
            if not command_text:
                self.get_logger().warn("음성이 인식되지 않았습니다.")
                self.is_woken_up = False
                return
            
            mode = self.mode_classifier.classify(command_text)  # 주문 or 모드 변경 판별
            
            if mode == "ADMIN":
                self.get_logger().info("관리자 모드로 전환합니다.")
                self.request_admin_auth_manager("관리자")       # 관리자 모드로 변경 요청
            elif mode == "SERVICE":
                self.get_logger().info("서비스 모드로 전환합니다.")
                self.request_admin_auth_manager("사용자")       # 사용자 모드로 변경 요청
            else:
                self.request_main_order_manager(command_text)

            # '편돌아' 호출어 대기 상태
            self.is_woken_up = False

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
        req.quantity = list(parsed_order.values())       # [2, 1]
        
        self.cli_order_product.call_async(req) # 비동기로 던지기

def main(args=None):
    rclpy.init(args=args)
    node = VoiceManagerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()

#voice_manager_way1.py
import os

import rclpy
from rclpy.node import Node

from store_interfaces.srv import OrderProduct, StartAdminAuth
from voice_processing.env_utils import load_openai_api_key
from voice_processing.ModeClassifier import ModeClassifier
from voice_processing.OrderProcessor import OrderProcessor
from voice_processing.STT import STT
from voice_processing.wakeup_word import WakeupWord


class VoiceManagerWay1Node(Node):
    """Blocking voice loop version.

    This removes the 0.1 second timer because the current STT implementation
    records for 5 seconds and blocks until transcription is complete.
    """

    def __init__(self):
        super().__init__("voice_manager_way1_node")

        openai_api_key = load_openai_api_key()
        if openai_api_key is None:
            raise ValueError("OPENAI_API_KEY가 .env 파일에서 로드되지 않았습니다.")

        self.declare_parameter("mic_device_index", -1)
        mic_device_index = self.get_parameter("mic_device_index").value
        device_index = None if mic_device_index < 0 else mic_device_index

        self.stt = STT(openai_api_key, device_index=device_index)
        self.wakeup = WakeupWord()
        self.mode_classifier = ModeClassifier()
        self.order_processor = OrderProcessor()

        self.cli_admin_auth = self.create_client(StartAdminAuth, "/start_admin_auth")
        self.cli_order_product = self.create_client(OrderProduct, "/order_product")

        self.get_logger().info("Voice manager way1 시작: 5초 녹음 단위로 호출어를 확인합니다.")

    def run_forever(self):
        while rclpy.ok():
            rclpy.spin_once(self, timeout_sec=0.0)

            self.get_logger().info("호출어를 말해주세요. 5초 동안 녹음합니다.")
            wake_text = self.stt.speech2text().strip()
            self.get_logger().info(f"호출어 STT 결과: {wake_text}")

            if not wake_text:
                self.get_logger().warn("호출어 음성이 인식되지 않았습니다.")
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
    node = VoiceManagerWay1Node()
    try:
        node.run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()

import rclpy
from rclpy.node import Node
from store_interfaces.srv import AdminAuth, StartAdminAuth
from std_msgs.msg import Bool

class AdminAuthManagerNode(Node):
    def __init__(self):
        super().__init__('admin_auth_manager_node')
        
        self.is_auth_active = False 

        self.cli_main_mode = self.create_client(AdminAuth, '/set_system_mode')  # 모드 변경 요청

        self.scan_key_card = self.create_subscription(Bool, 'key_card', self.key_card_scan_callback, 10)

        self.srv_start_auth = self.create_service(StartAdminAuth, '/start_admin_auth', self.start_auth_callback)    # 음성 인식 노드로부터 모드 변경 요청을 받았을 때

        self.get_logger().info("관리자 노드 시작")

    def start_auth_callback(self, request, response):       # 음성 인식 노드로부터 모드 변경 요청을 받았을 때
        req = AdminAuth.Request()

        if not self.cli_main_mode.wait_for_service(timeout_sec=2.0):
            self.get_logger().error("❌ 메인 매니저 모드 변경 서버가 응답하지 않습니다.")
            response.success = False
            return response

        if "사용자" in request.voice_text:      # 음성으로 사용자 모드 수신
            req.requested_mode = "SERVICE"
            self.is_auth_active = False
            self.cli_main_mode.call_async(req)
        else:
            self.get_logger().warn(f"알 수 없는 보안 명령문: '{request.voice_text}'")
            response.success = False
            return response

        response.success = True 
        return response
    
    def key_card_scan_callback(self, msg):       # 키 카드 스캔 결과
        req = AdminAuth.Request()
        if not self.is_auth_active:
            self.is_auth_active = msg.data
            req.requested_mode = "ADMIN"
            self.cli_main_mode.call_async(req)

def main(args=None):
    rclpy.init(args=args)
    node = AdminAuthManagerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
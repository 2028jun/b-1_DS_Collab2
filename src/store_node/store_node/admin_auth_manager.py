import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from store_interfaces.srv import AdminAuth, DetectProduct, StartAdminAuth
from store_interfaces.action import RobotPickPlace

class AdminAuthManagerNode(Node):
    def __init__(self):
        super().__init__('admin_auth_manager_node')
        
        self.is_auth_active = False 
        
        self.srv_start_auth = self.create_service(StartAdminAuth, '/start_admin_auth', self.start_auth_callback)    # 음성 인식 노드로부터 모드 변경 요청을 받았을 때

        self.cli_main_mode = self.create_client(AdminAuth, '/set_system_mode')  # 모드 변경 요청
        self.srv_scan = self.create_client(DetectProduct, '/scan_counter')      # 카드 키 스캔 요청

        self.robot_action_client = ActionClient(self, RobotPickPlace, '/pickup_and_place')  # 로봇의 동작 요청

        self.get_logger().info("관리자 노드 시작")

    def start_auth_callback(self, request, response):       # 음성 인식 노드로부터 모드 변경 요청을 받았을 때
        req = AdminAuth.Request()
        if "사용자" in request.voice_text:      # 음성으로 사용자 모드 수신
            req.requested_mode = "SERVICE"
            self.cli_main_mode.call_async(req)
        elif "관리자" in request.voice_text:        # 음성으로 관리자 모드 수신
            self.trigger_move_robot(behavior_name="MOVE_HOME", next_step_callback=self.trigger_key_card_scan)
        else:
            self.get_logger().warn(f"알 수 없는 보안 명령문: '{request.voice_text}'")
            response.success = False
            return response

        response.success = True 
        return response
        
    def trigger_key_card_scan(self):        # 키 카드 스캔 요청
        request = DetectProduct.Request()
        request.product_name = "KEY_CARD"
        scan_future = self.srv_scan.call_async(request)   
        scan_future.add_done_callback(self.key_card_scan_callback)  
    
    def key_card_scan_callback(self, future):       # 키 카드 스캔 결과
        try:
            response = future.result()      
            if response.success:
                self.get_logger().info("키 카드 스캔 완료")
                req = AdminAuth.Request()
                req.requested_mode = "ADMIN"
                self.get_logger().info("관리자 모드로 전환합니다.")
                self.cli_main_mode.call_async(req)
            else:
                self.get_logger().error("유효하지 않은 키 카드입니다.")
        except Exception as e:
            self.get_logger().error(f"스캔 서비스 통신 중 오류 발생: {e}")

    def trigger_move_robot(self, behavior_name, next_step_callback, object_name=""):  # 로봇 동작 액션 요청
        goal_msg = RobotPickPlace.Goal()
        goal_msg.behavior_name = behavior_name
        goal_msg.object_name = object_name
        
        self.get_logger().info(f"'{behavior_name}' 동작 실행...")
        
        future = self.robot_action_client.send_goal_async(goal_msg, feedback_callback=self.robot_feedback)
        
        future.add_done_callback(
            lambda f: self.action_response_handler(f, behavior_name, next_step_callback)
        )

    def robot_feedback(self, feedback_msg):    # 로봇 동작 중 피드백 처리
        message = feedback_msg.feedback.status
        self.get_logger().info(f"{message}")    # 이동 중..., 작업 중...

    def action_response_handler(self, future, action_name, next_step_callback):   # 로봇 동작 완료 후 다음 단계로 넘어가기 위한 처리
        goal_handle = future.result()
        if not goal_handle.accepted:
            self.get_logger().error(f"로봇 {action_name} 요청 거부됨")
            return

        # 수락되었다면 완료 결과에 콜백 연결
        goal_handle.get_result_async().add_done_callback(
            lambda f: next_step_callback() if f.result().status == 4 else self.get_logger().error(f"{action_name} 실패")
        )

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
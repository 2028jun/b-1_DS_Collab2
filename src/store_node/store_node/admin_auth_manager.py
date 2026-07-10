import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from store_interfaces.srv import AdminAuth, StartAdminAuth, CheckStock
from store_interfaces.action import RobotPickPlace
from std_msgs.msg import Bool, String, Empty
import time
import json
try:
    from dsr_msgs2.srv import MoveStop
    MOVE_STOP_IMPORT_ERROR = None
except ImportError as exc:
    MoveStop = None
    MOVE_STOP_IMPORT_ERROR = exc

class AdminAuthManagerNode(Node):
    def __init__(self):
        super().__init__('admin_auth_manager_node')
        
        self.is_auth_active = False 

        self.cli_main_mode = self.create_client(AdminAuth, '/set_system_mode')  # 모드 변경 요청

        self.scan_key_card = self.create_subscription(Bool, 'key_card', self.key_card_scan_callback, 10)

        self.srv_start_auth = self.create_service(StartAdminAuth, '/start_admin_auth', self.start_auth_callback)    # 음성 인식 노드로부터 모드 변경 요청을 받았을 때

        self.auth_sub = self.create_subscription(String, '/store_state', self.auth_sub_callback, 10)

        self.robot_action_client = ActionClient(self, RobotPickPlace, '/pickup_and_place')  # 로봇의 동작 요청
        
        self.admin_state_pub = self.create_publisher(Bool, '/admin_state', 10)

        self.check_stock = self.create_client(CheckStock, '/check_stock')  # 재고 확인 요청

        self.publish_cooldown = 0.5  
        self.admin_timer = self.create_timer(
            self.publish_cooldown, 
            self.publish_auth_admin_callback
        )

        self.get_logger().info("관리자 노드 시작")
        self.auth_status = "SERVICE"
        self.emergency_mode = False
        self.admin_is_robot_busy = False
        self.found_object = None

    def publish_auth_admin_callback(self):
        """타이머 주기에 맞춰 현재 관리자 로봇 상태를 상시 퍼블리시합니다."""
        msg = Bool()
        msg.data = self.admin_is_robot_busy
        self.admin_state_pub.publish(msg)
    
    def auth_sub_callback(self, msg):
        parts = msg.data.split(',')
        self.auth_status = parts[0].strip()

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
        elif "입고" in request.voice_text:      # 음성으로 사용자 모드 수신
            if self.auth_status == "ADMIN":
                self.trigger_warehousing_product_loop()
            else:
                self.get_logger().warn(f"관리자 모드가 아니므로 입고 할 수 없습니다.")
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

    def trigger_warehousing_product_loop(self):
        self.admin_is_robot_busy = True
        # 입고 물품 스캔 지점 이동
        self.trigger_move_robot(behavior_name="MOVE_SCAN_BASKET", 
                                next_step_callback=lambda: self.trigger_pick_object(object_name="all"))
    
    def trigger_pick_object(self, object_name):     # 로봇 물품 잡기 요청
        self.trigger_move_robot(behavior_name="SCAN_AND_PICK_WAREHOUSE", next_step_callback=self.trigger_scan_qr, object_name=object_name)

    def trigger_scan_qr(self):      # QR 스캔 요청
        self.trigger_move_robot(behavior_name="QR_SCAN", next_step_callback=self.trigger_drop_temp)
    
    def trigger_drop_temp(self):    
        req = CheckStock.Request()
        check_stock = self.check_stock.call_async(req)
        check_stock.add_done_callback(self.check_stock_callback)
    
    def check_stock_callback(self, future):
        try:
            response = future.result()
            
            if response.success:
                # 4. 수신된 JSON 문자열을 파이썬 객체(리스트/딕셔너리)로 파싱
                inventory_list = json.loads(response.inventory_json)

                is_exist = any(item.get('name') == self.found_object for item in inventory_list)
                
                if not is_exist:
                    self.trigger_restock()
                else:
                    self.trigger_move_robot(behavior_name="DROP_TEMP1", next_step_callback = self.trigger_move_scan)
                
            else:
                self.get_logger().error("❌ 데이터베이스 노드가 재고 데이터를 정상적으로 긁어오지 못했습니다.")
                
        except Exception as e:
            self.get_logger().error(f"❌ 재고 확인 서비스 비동기 콜백 처리 중 예외 발생: {e}")
    
    def trigger_move_scan(self):
        self.trigger_move_robot(behavior_name="MOVE_SCAN", next_step_callback=lambda: self.trigger_pick_for_drop(self.found_object))
    
    def trigger_pick_for_drop(self, object_name):
        self.trigger_move_robot(behavior_name="SCAN_AND_PICK", next_step_callback=self.trigger_drop_temp2, object_name=object_name)
    
    def trigger_drop_temp2(self):
        self.trigger_move_robot(behavior_name="DROP_TEMP2", next_step_callback=self.trigger_restock)

    def trigger_restock(self):
        pass     

    def trigger_move_robot(self, behavior_name, next_step_callback, object_name=""):
        goal_msg = RobotPickPlace.Goal()
        goal_msg.behavior_name = behavior_name
        goal_msg.object_name = object_name
        
        self.get_logger().info(f"'{behavior_name}' 동작 실행...")
        
        future = self.robot_action_client.send_goal_async(goal_msg)
        
        future.add_done_callback(
            lambda f: self.action_response_handler(f, behavior_name, next_step_callback)
        ) 
        
    def action_response_handler(self, future, action_name, next_step_callback):   
        # 로봇 동작 완료 후 다음 단계로 넘어가기 위한 처리
        goal_handle = future.result()
        if not goal_handle.accepted:
            self.get_logger().error(f"로봇 {action_name} 요청 거부됨")
            return

        # 현재 실행 중인 핸들을 저장 (긴급 정지 시 취소하기 위함)
        self.current_goal_handle = goal_handle

        goal_handle.get_result_async().add_done_callback(
            lambda f: self.action_result_handler(f, action_name, next_step_callback)
        )
    
    def action_result_handler(self, future, action_name, next_step_callback):
        # 추가: 비상 모드라면 콜백을 그냥 무시하고 종료
        if self.emergency_mode:
            return
        
        action_result = future.result()
        
        if action_result.status == 4:
            self.get_logger().info(f"✔ '{action_name}' 동작 완료!")
            
            # 1. 확정된 액션 스펙에 맞춰 결과 객체(result) 참조
            result_data = action_result.result
            
            # 2. [창고 입고 모드] found_object 필드 매칭
            if action_name == "SCAN_AND_PICK_WAREHOUSE":
                if hasattr(result_data, 'found_object') and result_data.found_object:
                    # 🔥 스펙 명칭에 맞춰 self.found_object에 정확히 동기화
                    self.found_object = result_data.found_object
            
            # 3. [일반 QR 스캔 모드] qr_data 필드 매칭
            elif action_name == "QR_SCAN":
                if hasattr(result_data, 'qr_data') and result_data.qr_data:
                    self.qr_data = result_data.qr_data

            # 다음 시퀀스 밟기 (예: DB 입고/출고 트랜잭션 단계로 이동)
            next_step_callback()
        else:
            self.get_logger().error(f"'{action_name}' 동작 실패 (Status: {action_result.status})")
            self.robot_busy = False

    def emergency_stop_callback(self, msg):
        self.last_hand_detected_time = time.time()
        if not self.emergency_mode:
            self.get_logger().warn("손 감지! 로봇 동작 일시 정지")
            self.emergency_mode = True
            
            # 1. 물리적 긴급 정지 (즉시 모터 멈춤)
            self.request_motion_stop()
            
            # 2. 로봇 제어부에 '일시 정지' 신호 전달 (로봇이 상태를 기억하게 함)
            self.pause_pub.publish(Empty())

    def request_motion_stop(self):
        for service_name, client in self.move_stop_clients:
            if client.service_is_ready():
                req = MoveStop.Request()
                req.stop_mode = 0
                client.call_async(req)
                self.get_logger().error(
                    f"{service_name} 즉시 정지 요청을 전송했습니다."
                )
                return

        self.get_logger().error(
            "move_stop 서비스가 준비되지 않아 즉시 정지 요청을 보내지 "
            "못했습니다. (/motion, /dsr01/motion 모두 실패)"
        )
    
    def check_resume_condition(self):
        if self.emergency_mode and (time.time() - self.last_hand_detected_time > 3.0):
            self.get_logger().info("손 사라짐. 로봇 동작 재개")
            self.emergency_mode = False
            self.robot_busy = False
            
            # 3. 로봇 제어부에 '재개' 신호 전달
            self.resume_pub.publish(Empty())



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
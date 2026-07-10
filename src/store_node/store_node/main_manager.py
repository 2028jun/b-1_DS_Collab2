import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from store_interfaces.srv import OrderProduct, UpdateInventory, AdminAuth
from store_interfaces.action import RobotPickPlace
from std_msgs.msg import String, Empty
from time import time
try:
    from dsr_msgs2.srv import MoveStop
    MOVE_STOP_IMPORT_ERROR = None
except ImportError as exc:
    MoveStop = None
    MOVE_STOP_IMPORT_ERROR = exc

class MainManagerNode(Node):
    def __init__(self):
        super().__init__('main_manager_node')
        self.order_items_list = []  # 주문 상품 목록 
        self.order_quantities_list = []  # 주문 수량 목록
        self.current_loop_index = 0  # 현재 주문 처리 중인 인덱스
        self.total_target_list = [] # 처리해야할 남은 물품
        self.system_mode = "SERVICE"  # 주문 모드
        self.qr_data = None # QR 데이터
        self.robot_busy = False
        self.current_goal_handle = None
        self.create_subscription(Empty, '/emergency_stop', self.emergency_stop_callback, 1)
        self.move_stop_clients = self.create_move_stop_clients()
        self.emergency_mode = False
        self.last_hand_detected_time = 0.0 # 손이 마지막으로 감지된 시간
        self.resume_timer = self.create_timer(1.0, self.check_resume_condition)
        self.pause_pub = self.create_publisher(Empty, '/robot_pause', 10)
        self.resume_pub = self.create_publisher(Empty, '/robot_resume', 10)
        self.has_sent_resume = False

        # 현재 사용자 / 관리자 모드 퍼블리시
        self.auth_pub = self.create_publisher(String, '/store_state', 10)

        # 퍼블리시 타이머
        self.publish_cooldown = 0.5  
        self.auth_timer = self.create_timer(
            self.publish_cooldown, 
            self.publish_auth_mode_callback
        )
        # ---------------------------------------------------------------------------------------------------------
        # 서비스 서버
        self.srv_kiosk = self.create_service(     # 주문 접수
            OrderProduct, 
            '/order_product', 
            self.order_product_callback  
        )

        self.srv_mode_control = self.create_service(    # 시스템 모드 변경
            AdminAuth, 
            '/set_system_mode',
            self.AdminAuth_callback
        )
        # -----------------------------------------------------------------------------------------------------
        self.srv_database = self.create_client(     # 데이터베이스에 재고 업데이트 요청
            UpdateInventory, 
            '/update_stock', 
        )
        # -----------------------------------------------------------------------------------------------------
        # 액션 클라이언트
        self.robot_action_client = ActionClient(self, RobotPickPlace, '/pickup_and_place')  # 로봇의 동작 요청

        self.get_logger().info("메인 매니저 노드 시작")
    def create_move_stop_clients(self):
        if MoveStop is None:
            self.get_logger().warn(
                f"MoveStop 서비스를 사용할 수 없습니다: {MOVE_STOP_IMPORT_ERROR}"
            )
            return []

        return [
            ('/motion/move_stop', self.create_client(MoveStop, '/motion/move_stop')),
            (
                '/dsr01/motion/move_stop',
                self.create_client(MoveStop, '/dsr01/motion/move_stop'),
            ),
        ]
    
    def publish_auth_mode_callback(self):
        """타이머 주기에 맞춰 현재 시스템 모드를 상시 퍼블리시합니다."""
        msg = String()
        msg.data = f'{self.system_mode}, {self.robot_busy}'
        self.auth_pub.publish(msg)
    
    def AdminAuth_callback(self, request, response):    # 음성 비밀번호 일치 및 키 카드 인식 성공(다른 노드에서 진행) 후 모드 변경
        if request.requested_mode == "ADMIN":
            if self.system_mode == "ADMIN":
                response.success = True
                return response

            self.system_mode = "ADMIN"
            self.get_logger().info("관리자 모드로 전환되었습니다.")
            response.success = True      

        elif request.requested_mode == "SERVICE":
            if self.system_mode == "SERVICE":
                response.success = True
                return response

            self.system_mode = "SERVICE"
            self.get_logger().info("관리자 모드가 해제되었습니다.")
            response.success = True
        
        else:
            response.success = False
        
        return response
        
    def order_product_callback(self, request, response):    # 키오스크 화면 및 음성 주문 접수시 실행
        if self.emergency_mode:
            self.get_logger().warn("비상 정지 상태입니다. 주문을 접수할 수 없습니다.")
            response.success = False
            return response
        if self.system_mode == "SERVICE" and not self.robot_busy :       # 주문 모드일 때
            self.order_items_list = request.product_name  # 주문 상품 목록 저장
            self.order_quantities_list = request.quantity  # 주문 수량 목록 저장
            self.current_loop_index = 0     # 주문 처리 인덱스 초기화
            self.total_target_list = []     # 처리해야할 남은 물품 초기화

            for name, qty in zip(self.order_items_list, self.order_quantities_list):    # 주문 물품을 처리 물품 목록에 추가(과자, 과자, 담배, 물, 물)
                self.total_target_list.extend([name] * qty)

            order_dict = dict(zip(request.product_name, request.quantity)) # 주문 상품과 개수를 딕셔너리 형태로 묶기
            order_items = [f"{name}:{qty}개" for name, qty in order_dict.items()]   # 주문 접수 목록을 문자열로 변환(과자 : 1개)
            self.get_logger().info(f"키오스크 주문 접수 : {', '.join(order_items)}")  # 주문 접수 목록 출력 (주문 접수: 과자 1개, 음료 2개)

            if not self.robot_action_client.wait_for_server(timeout_sec=5.0):       # 액션 서버 연결 확인
                self.get_logger().error('주문 서버가 응답하지 않습니다.')
                response.success = False
                return response

            self.robot_busy = True
            
            self.process_next_item_loop()  # 주문 처리 루프 시작

            response.success = True     # 주문 접수 완료 

            return response
        else:           # 관리자 모드일 때
            if self.robot_busy is True:
                self.get_logger().warn("로봇이 다른 작업 중입니다.")
            else:
                self.get_logger().warn("관리자 모드이므로 주문을 접수할 수 없습니다.")
            response.success = False
            return response
    
    def process_next_item_loop(self):   # 주문 처리 루프 : 스캔지점 이동 -> 물품 스캔 -> 물품 옮기기 -> QR 스캔 -> 장바구니 놓기 -> 재고 업데이트
        self.qr_data = None
        if self.current_loop_index >= len(self.total_target_list):  # 모든 물품 처리를 완료했을 때
            self.get_logger().info("모든 물품을 장바구니에 담았습니다")
            self.trigger_move_robot(behavior_name="MOVE_HOME", next_step_callback=self.move_home_done)
            self.robot_busy = False
            return

        current_target_name = self.total_target_list[self.current_loop_index]   # 현재 처리할 물품 이름
        self.get_logger().info(f"[{self.current_loop_index + 1}/{len(self.total_target_list)}] '{current_target_name}' 처리 시작...")
        
        # 스캔 지점 이동
        self.trigger_move_robot(behavior_name="MOVE_SCAN", 
                                next_step_callback=lambda: self.trigger_pick_object(self.total_target_list[self.current_loop_index])) 

    def trigger_pick_object(self, object_name):     # 로봇 물품 잡기 요청
        self.trigger_move_robot(behavior_name="SCAN_AND_PICK", next_step_callback=self.trigger_scan_qr, object_name=object_name)
    
    def trigger_scan_qr(self):      # QR 스캔 요청
        self.trigger_move_robot(behavior_name="QR_SCAN", next_step_callback=self.trigger_place_basket)
    
    def trigger_place_basket(self):     # 장바구니에 물품 놓기
        self.trigger_move_robot(behavior_name="PLACE_BASKET", next_step_callback=self.trigger_update_inventory)

    def trigger_update_inventory(self):    # 재고 업데이트 요청
        if not self.srv_database.wait_for_service(timeout_sec=3.0):
            self.get_logger().error("재고 업데이트 서버가 켜져있지 않습니다.")
            return

        self.get_logger().info("재고 업데이트 요청 중...")
        request = UpdateInventory.Request()
        request.qr_data = self.qr_data
        
        update_future = self.srv_database.call_async(request)
        update_future.add_done_callback(self.update_inventory_callback)
    
    def update_inventory_callback(self, future):    # 재고 업데이트 결과
        try:
            response = future.result()
            if response.success:
                self.get_logger().info("재고 업데이트 완료")
                self.complete_item_loop()  # 모든 물품 처리 완료 후 다음 단계로 넘어가기
            else:
                self.get_logger().error("재고 업데이트 실패")
        except Exception as e:
            self.get_logger().error(f"재고 업데이트 서비스 통신 중 오류 발생: {e}")
    
    def complete_item_loop(self):    # 현재 물품 처리 완료 후 다음 물품 처리로 넘어가기
        current_target_name = self.total_target_list[self.current_loop_index]
        self.get_logger().info(f"'{current_target_name}' 처리 완료")

        self.current_loop_index += 1  # 다음 물품 처리 인덱스로 이동
        self.process_next_item_loop()  # 다음 물품 처리 루프 시작

    def trigger_move_to_home(self):
        self.trigger_move_robot(behavior_name="MOVE_HOME", next_step_callback=self.move_home_done)

    def move_home_done(self):
        self.get_logger().info(f"초기 위치 이동 완료")
        self.robot_busy = False

    def trigger_move_robot(self, behavior_name, next_step_callback, object_name=""):
        goal_msg = RobotPickPlace.Goal()
        goal_msg.behavior_name = behavior_name
        goal_msg.object_name = object_name
        
        self.get_logger().info(f"'{behavior_name}' 동작 실행...")
        
        future = self.robot_action_client.send_goal_async(goal_msg)
        
        future.add_done_callback(
            lambda f: self.action_response_handler(f, behavior_name, next_step_callback)
        )

    def action_response_handler(self, future, action_name, next_step_callback):   # 로봇 동작 완료 후 다음 단계로 넘어가기 위한 처리
        goal_handle = future.result()
        if not goal_handle.accepted:
            self.get_logger().error(f"로봇 {action_name} 요청 거부됨")
            return

        # 수락되었다면 완료 결과에 콜백 연결def action_response_handler(self, future, action_name, next_step_callback):   
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
        # 1. 비상 정지 중이면 콜백을 아예 처리하지 않고 종료 (재개 시 자동으로 다시 처리됨)
        if self.emergency_mode:
            return
        
        try:
            action_result = future.result()
        except Exception as e:
            self.get_logger().error(f"결과 수신 오류: {e}")
            return

        # 2. 성공한 경우
        if action_result.status == 4:
            self.get_logger().info(f"'{action_name}' 동작 완료!")
            if hasattr(action_result.result, 'qr_data') and action_result.result.qr_data:
                self.qr_data = action_result.result.qr_data
            next_step_callback()

        # 3. 비상 정지로 인해 취소된 경우
        elif action_result.status == 2:
            self.get_logger().warn(f"'{action_name}' 동작이 비상 정지로 인해 취소되었습니다.")

        # 4. 진짜 실패인 경우
        else:
            self.get_logger().error(f"'{action_name}' 동작 실패 (Status: {action_result.status})")
            self.robot_busy = False # 실제 오류일 때만 작업을 종료시킴
            
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
        if self.emergency_mode:
            if (time.time() - self.last_hand_detected_time > 3.0):
                self.get_logger().info("비상 정지 해제: 작업 재개...")
                
                # 1. 로봇 제어부 재개 신호
                if not self.has_sent_resume:
                    self.resume_pub.publish(Empty())
                    self.has_sent_resume = True
                
                # 2. 비상 모드 해제
                self.emergency_mode = False
                
        else:
            self.has_sent_resume = False

def main(args=None):
    rclpy.init(args=args)
    node = MainManagerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
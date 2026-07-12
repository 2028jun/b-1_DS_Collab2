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
        
        # 퍼블리셔
        self.admin_state_pub = self.create_publisher(Bool, '/admin_state', 10)

        # 타이머
        self.admin_timer = self.create_timer(0.5, self.publish_auth_admin_callback)

        # 서브스크라이버
        self.scan_key_card = self.create_subscription(Bool, 'key_card', self.key_card_scan_callback, 10)        # 키 카드 스캔 여부 구독
        self.auth_sub = self.create_subscription(String, '/store_state', self.auth_sub_callback, 10)            # 

        # 서비스 서버
        self.srv_start_auth = self.create_service(StartAdminAuth, '/start_admin_auth', self.start_auth_callback)    # 음성 인식 노드로부터 모드 변경 요청을 받았을 때

        # 서비스 클라이언트
        self.cli_main_mode = self.create_client(AdminAuth, '/set_system_mode')  # 모드 변경 요청
        self.check_stock = self.create_client(CheckStock, '/check_stock')  # 재고 확인 요청
        self.expiry_cli = self.create_client(CheckStock, '/check_expiry_date')  # 유통기한 확인 요청

        # 액션 클라이언트
        self.robot_action_client = ActionClient(self, RobotPickPlace, '/pickup_and_place')  # 로봇의 동작 요청
     
        self.is_auth_active = False         # 관리자 모드 여부
        self.auth_status = "SERVICE"        # 현재 모드
        self.emergency_mode = False
        self.admin_is_robot_busy = False
        self.found_object = None
        self.is_exist = True

        self.get_logger().info("관리자 노드 시작")

    def publish_auth_admin_callback(self):      # 0.5초 마다 현재 로봇이 동작 중인지 퍼블리시
        msg = Bool()
        msg.data = self.admin_is_robot_busy
        self.admin_state_pub.publish(msg)
    
    def auth_sub_callback(self, msg):           # 현재 모드 상태를 저장
        parts = msg.data.split(',')
        self.auth_status = parts[0].strip()

    def start_auth_callback(self, request, response):       # 음성 인식 노드로부터 모드 변경 요청을 받았을 때
        req = AdminAuth.Request()

        if not self.cli_main_mode.wait_for_service(timeout_sec=2.0):
            self.get_logger().error("❌ 메인 매니저 모드 변경 서버가 응답하지 않습니다.")
            response.success = False
            return response

        if "사용자" in request.voice_text:      # 사용자 모드 변경 요청
            req.requested_mode = "SERVICE"
            self.is_auth_active = False
            self.cli_main_mode.call_async(req)
        elif "입고" in request.voice_text:      # 입고 실행
            if self.auth_status == "ADMIN":     # 관리자 모드 일때만 입고 실행
                self.trigger_warehousing_product_loop()     # 입고 루프 시작
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
        if not self.is_auth_active:     # 관리자 모드가 아니면
            self.is_auth_active = msg.data
            req.requested_mode = "ADMIN"
            self.cli_main_mode.call_async(req)      # 관리자 모드 변경 요청

    def trigger_warehousing_product_loop(self):     
        self.admin_is_robot_busy = True
        self.trigger_move_robot(behavior_name="MOVE_SCAN_BASKET",       # 입고 물품 스캔 지점 이동
                                next_step_callback=lambda: self.trigger_pick_object(object_name="all"))
    
    def trigger_pick_object(self, object_name):     # 로봇 물품 잡기 요청
        self.trigger_move_robot(behavior_name="SCAN_AND_PICK_WAREHOUSE", next_step_callback=self.trigger_scan_qr, object_name=object_name)

    def trigger_scan_qr(self):      # QR 스캔 요청
        self.trigger_move_robot(behavior_name="QR_SCAN", next_step_callback=self.trigger_drop_temp)
    
    def trigger_drop_temp(self):    # 유통기한 비교해서 입고하기
        req = CheckStock.Request()
        check_stock = self.check_stock.call_async(req)      # 재고 확인 요청
        check_stock.add_done_callback(self.check_stock_callback)    # 재고 확인 결과
    
    def check_stock_callback(self, future):
        try:
            response = future.result()
            
            if response.success:
                # 4. 수신된 JSON 문자열을 파이썬 객체(리스트/딕셔너리)로 파싱
                inventory_list = json.loads(response.inventory_json)

                self.is_exist = sum(1 for item in inventory_list if item.get('name') == self.found_object) >= 2  # 진열대에 물품이 있는지 확인
                
                if not self.is_exist:        # 진열대에 입고할 물품이 없을 때 
                    self.trigger_restock("back0")      # 상품 진열(뒤쪽)
                    return
                else:       # 진열대에 입고할 물품이 있을 때 
                    request = CheckStock.Request()
                    request.current_name = self.found_object
                    request.current_expiry = self.qr_data.get("expiry_date", "")

                    if not self.expiry_cli.service_is_ready():
                        self.get_logger().error("❌ 유통기한 조회 서비스(/check_expiry)가 준비되지 않았습니다.")
                        return
                    
                    if self.found_object == "smoke":
                        self.trigger_restock("front0")  # 상춤 진열(앞쪽)
                        return
                    
                    expiry_future = self.expiry_cli.call_async(request)     # 유통기한 정보 요청
                    expiry_future.add_done_callback(self.expiry_response_callback)         
            else:
                self.get_logger().error("❌ 데이터베이스 노드가 재고 데이터를 정상적으로 긁어오지 못했습니다.")
                
        except Exception as e:
            self.get_logger().error(f"❌ 재고 확인 서비스 비동기 콜백 처리 중 예외 발생: {e}")

    def expiry_response_callback(self, future):
        try:
            response = future.result()
            if response.success:

                raw_json = response.closest_expiry_list.strip() if response.closest_expiry_list else "[]"
                
                # 데이터가 텅 비어 있다면 json.loads에서 char 0 에러가 나므로 사전 차단
                if not raw_json or raw_json == "":
                    self.get_logger().error("수신된 JSON 데이터가 비어 있습니다. 선입선출 분기를 기본값(DROP_TEMP1)으로 처리합니다.")
                    self.trigger_move_robot(behavior_name="DROP_TEMP1", next_step_callback=self.trigger_move_scan)
                    return

                # DB 노드가 요약해 준 [{'name': '상품명', 'expiry_date': '기한'}, ...] 파싱
                closest_expiry_list = json.loads(response.closest_expiry_list)
                
                # 전체 목록 중 현재 로봇이 다루고 있는 물품(self.found_object) 정보만 추출
                target_db_item = next((item for item in closest_expiry_list if item['name'] == self.found_object), None)
                
                # 날짜 문자열 추출 (형식: YYYY-MM-DD)
                db_closest_date = target_db_item['expiry_date']     # 진열대 상품 중 가장 임박한 유통기한
                current_scanned_date = self.qr_data.get("expiry_date")  # 입고 상품의 유통기한
                
                self.get_logger().info(f"진열대 최단 유총기한: {db_closest_date} / 입고된 유총기한: {current_scanned_date}")
                
                if current_scanned_date < db_closest_date:
                    self.get_logger().warn("새로 입고하려는 물품의 유통기한이 더 짧습니다! 그대로 진열합니다.")
                    self.trigger_restock("front0")   # 앞쪽에 진열
                else:
                    self.get_logger().info("신규 물품의 유통기한이 더 넉넉합니다. 선입선출을 실시합니다.")
                    self.trigger_move_robot(behavior_name="DROP_TEMP1", next_step_callback = self.trigger_move_scan)     # 선입선출 실행
            else:
                self.get_logger().error("❌ 데이터베이스 노드로부터 유통기한 데이터를 수신하지 못했습니다.")
        except Exception as e:
            self.get_logger().error(f"❌ 유통기한 응답 처리 중 예외 발생: {e}")
    
    def trigger_move_scan(self):        # 물품 스캔 지점 이동
        self.trigger_move_robot(behavior_name="MOVE_SCAN", next_step_callback=lambda: self.trigger_pick_for_drop(self.found_object))
    
    def trigger_pick_for_drop(self, object_name):       # 스캔 후 물품을 잡기
        self.trigger_move_robot(behavior_name="SCAN_AND_PICK", next_step_callback=self.trigger_drop_temp2, object_name=object_name)
    
    def trigger_drop_temp2(self):       # 2번 지점에 물품을 두기
        self.trigger_move_robot(behavior_name="DROP_TEMP2", next_step_callback=lambda: self.trigger_restock("back1"))

    def trigger_restock(self, place):       # 물품을 진열
        if place == "front0":
            self.trigger_move_robot(behavior_name="INSERT_TO_FRONT", next_step_callback=self.trigger_warehousing_product_loop, 
                                    place=0, object_found=self.found_object)  # 앞쪽에 물품 두기 -> 다른 물품 입고 진헹
        elif place == "front2":
            self.trigger_move_robot(behavior_name="INSERT_TO_FRONT", next_step_callback=self.trigger_warehousing_product_loop, 
                                    place=2, object_found=self.found_object)  # 2번 물품 앞똑에 두기 -> 다른 물품 입고 진행
        elif place == "back0":
                self.trigger_move_robot(behavior_name="INSERT_TO_BACK", next_step_callback=self.trigger_warehousing_product_loop, 
                                        place=0, object_found=self.found_object)   # 물품을 뒤쪽에 두기 -> 다른 물품 입고 진행
        elif place == "back1":
                self.trigger_move_robot(behavior_name="INSERT_TO_BACK", next_step_callback=lambda: self.trigger_restock("front2"), 
                                        place=1, object_found=self.found_object)   # 2번 물품 뒤쪽에 두기 -> 1번 물품 앞쪽에 두가
    
    def done_warehousing(self):     
        self.get_logger().info(f"'입고 완료")
        self.trigger_move_robot(behavior_name="MOVE_HOME", next_step_callback=self.move_home_done)
        
    def move_home_done(self):
        self.get_logger().info(f"초기 위치 이동 완료")
        self.admin_is_robot_busy = False  

    def trigger_move_robot(self, behavior_name, next_step_callback, object_name="", place=-1, object_found=""):
        goal_msg = RobotPickPlace.Goal()
        goal_msg.behavior_name = behavior_name
        goal_msg.object_name = object_name
        goal_msg.place = place
        goal_msg.object_found = object_found

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
                    self.qr_data = json.loads(result_data.qr_data)

            # 다음 시퀀스 밟기 (예: DB 입고/출고 트랜잭션 단계로 이동)
            next_step_callback()
        else:
            if action_name == "SCAN_AND_PICK_WAREHOUSE":  
                self.done_warehousing()
                return
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
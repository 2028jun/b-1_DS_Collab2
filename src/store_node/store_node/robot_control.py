import os
from dsr_msgs2.srv import MoveStop
from std_msgs.msg import Empty
import rclpy
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.action import ActionServer
from store_interfaces.srv import FineTuneQr, ScanCounterQr
from store_node.realsense import ImgNode
from scipy.spatial.transform import Rotation
from store_node.onrobot import RG
from store_interfaces.action import RobotPickPlace
from std_msgs.msg import String 

import time
import numpy as np
import DR_init

# 두산 로봇 설정 전역 변수
ROBOT_ID = "dsr01"
ROBOT_MODEL = "m0609"
VELOCITY, ACC = 75, 100

GRIPPER_NAME = "rg2"
TOOLCHARGER_IP = "192.168.1.1"
TOOLCHARGER_PORT = "502"

class RoobotControlNode(Node):
    def __init__(self):
        super().__init__("robot_control_node")

        # 서브스크라이버
        self.create_subscription(Empty, '/robot_pause', self.pause_callback, 10)         # 일시 정지 신호
        self.create_subscription(Empty, '/robot_resume', self.resume_callback, 10)       # 재개 신호
        self.qr_sub_robot = self.create_subscription(String, '/counter_qr_data_robot', self.qr_sub_robot_callback, 10)      # QR 데이터 받기
        # ----------------------------------------------------------------------------
        # 서비스 클라이언트
        self.get_camera_coord = self.create_client(     # 비전 노드(YOLO)에 3D 좌표 요청
            FineTuneQr,
            'fine_tune_qr',
        )

        self.scan_qr = self.create_client(      # QR 코드 인식 요청
            ScanCounterQr,
            'scan_counter_qr',
        )

        self.move_stop_client = self.create_client(MoveStop, '/dsr01/motion/move_stop')   # 하드웨어 긴급 정지 서비스 요청
        # ----------------------------------------------------------------------------
        # 액션 서버
        self.robot_action_server = ActionServer(    # 로봇 액션 명령을 수신 받을 서버
            self,
            RobotPickPlace,
            '/pickup_and_place',
            self.execute_callback
        )
        
        self.img_node = ImgNode()
        rclpy.spin_once(self.img_node)
        time.sleep(1)       # 카메라 센서 작동 대기
        self.intrinsics = self.img_node.get_camera_intrinsic()   # 카메라 정보
        
        current_dir = os.path.dirname(os.path.abspath(__file__))
        npy_path = os.path.join(current_dir, "T_gripper2camera.npy")
        self.gripper2cam = np.load(npy_path)    # 카메라 캘리브레이션 파일 로드
        self.gripper = RG(GRIPPER_NAME, TOOLCHARGER_IP, TOOLCHARGER_PORT)
        
        self.is_processing = False  # 작업 중 중복 요청 방지용 플래그
        self.object = None
        self.found_object = None
        self.last_qr_data = ""
        self.qr_data = ""
        self.behavior = ""
        self.is_paused = False # 비상 정지 상태 플래그
        
        self.home = posj([0, 0, 90, 0, 90, 0])  # 초기 위치
        self.basket_up = posx([336, 427.5, 125.02, 46.75, -180, 140])   # 장바구니 위
        self.basket_down = posx([336, 427.5, -150, 46.75, -180, 140])   # 장바구니 아래
        self.qr_home = posx([615.5, 0.13, 80.89, 138.88, -180, -130])   # QR 스캔 지점
        self.scan_home_waypoint = posj([16.62, 24.93, 98.92, 105.82, -102.11, 33.04])   # 물품 전체 스캔 지점 중간 
        self.scan_home = posx([485.63, -12.59, 167.73, 88.87, -87.93, -90.68])      # 물품 전체 스캔 위치
        self.scan_basket_home = posx([244.37, 455.97, 122.31, 44.25, -179.9, 137.25])   # 입고할 물품 스캔 위치
        self.drop_temp1 = posx([571.59, 218.6, 70, 5.56, -177.47, -176.95])          # 유통기한 비교할 위치(입고 상품)
        self.drop_temp2 = posx([269.39, 246.35, 70, 7.23, -177.79, -175.19 ])        # 유통기한 비교할 위치2(기존 상품)
        self.drop_center1 = posx([539.25, -468.67, 138.77, 88.99, -88.01, -90.77])  # 진열대 가운데 아래 안쪽 위치
        self.drop_center2 = posx([543.36, -409.59, 138.30, 89.00, -88.00, -90.88])  # 진열대 가운데 아래 바깥쪽

        self.drop_jjolbyung = posx([727, -330, 165, 89.00, -88.00, -90.88])  # 쫄병 
        self.drop_coffee = posx([727, -330, 365, 89.00, -88.00, -90.88])  # 커피
        self.drop_smoke = posx([527, -330, 365, 89.00, -88.00, -90.88])  # 담배
        self.drop_drink = posx([527, -330, 165, 89.00, -88.00, -90.88])  # 음료수
        self.drop_cup_noodle = posx([327, -330, 165, 89.00, -88.00, -90.88])  # 컵라면
        self.drop_choco = posx([327, -330, 365, 89.00, -88.00, -90.88])  # 초코송이

        movej(self.home, vel=VELOCITY, acc=ACC) # 로봇 가동시 초기 자세로 이동
        self.gripper.open_gripper()     # 그리퍼 열기

        self.get_logger().info("robot_control_node 실행")
    
    def get_safe_current_posx(self, max_retries=5, delay=0.1):
        """두산 로봇 직교 좌표([X,Y,Z,A,B,C])를 안전하게 읽어오며, 예외 발생 시 재시도합니다."""
        for i in range(max_retries):
            try:
                pos_data = get_current_posx()
                if pos_data and len(pos_data) > 0:
                    return pos_data[0]
            except IndexError:
                # self.get_logger().warn(f"⚠️ 직교 좌표(posx) 수신 지연... 재시도 중 ({i+1}/{max_retries})")
                time.sleep(delay)
            except Exception as e:
                self.get_logger().error(f"posx 읽기 중 예외 발생: {e}")
                break
        return None

    def get_safe_current_posj(self, max_retries=5, delay=0.1):
        """두산 로봇 관절 각도(J1~J6)를 안전하게 읽어오며, 예외 발생 시 재시도합니다."""
        for i in range(max_retries):
            try:
                joint_data = get_current_posj()
                if joint_data is not None:
                    # get_current_posj() 반환 형태가 리스트의 리스트일 경우[0] 처리, 단일 리스트면 데이터 검증 후 리턴
                    if isinstance(joint_data, list) and len(joint_data) > 0:
                        return joint_data[0] if isinstance(joint_data[0], list) else joint_data
                    return joint_data
            except (IndexError, TypeError):
                # self.get_logger().warn(f"⚠️ 관절 각도(posj) 수신 지연... 재시도 중 ({i+1}/{max_retries})")
                time.sleep(delay)
            except Exception as e:
                self.get_logger().error(f"posj 읽기 중 예외 발생: {e}")
                break
        return None
    
    def safe_movel(self, target_pos, vel=VELOCITY, acc=ACC, mod=0, ref=None):
        is_relative_move = (mod == DR_MV_MOD_REL) or (ref is not None)      # 상대좌표 or ref에 값이 있으면 True
        command_sent = False  # 💡 [안전핀] 명령 난사 방지 가드독 플래그

        while True:
            if self.is_paused:      # 정지 명령이 있으면 while문 반복 -> 로봇 정지
                if command_sent:
                    command_sent = False # 정지가 풀리면 명령을 새로 쏴야 하므로 초기화
                time.sleep(0.5)
                continue
            
            # 2. 절대 좌표(ABS) 도착 판정
            if not is_relative_move:
                current_pos = self.get_safe_current_posx()    # 현재 위치 받아오기

                if current_pos is None:
                    self.get_logger().warn("⚠️ safe_movel: 로봇 좌표가 일시적으로 None입니다. 다음 루프에서 재시도합니다.")
                    time.sleep(0.1) # 소켓 병목이 풀릴 시간을 의도적으로 제공
                    continue

                dist = np.linalg.norm(np.array(list(target_pos)[:3]) - np.array(list(current_pos)[:3]))     # 목표 위치까지 남은 거리
                if dist < 3.0:  # 로봇이 목표위치에 거의 도착하면 동작 완료
                    break
            
            # 3. 이동 명령 실행
            if not command_sent:
                movel(target_pos, vel=vel, acc=acc, mod=mod, ref=ref)   
                command_sent = True # 래칭 가드 동작
            
            # 4. 상대 좌표(REL/TOOL)는 한 번만 수행하고 종료
            if is_relative_move:
                break
                
            time.sleep(0.1)

    def safe_movej(self, pos, vel=VELOCITY, acc=ACC):
        command_sent = False 
        while True:
            if self.is_paused:   # 정지 명령이 있으면 while문 반복 -> 로봇 정지
                if command_sent:
                    command_sent = False # 정지가 풀리면 명령을 새로 쏴야 하므로 초기화
                time.sleep(0.5)
                continue
            
            current_joints = self.get_safe_current_posj()     # 현재 관절 각도 값 받아오기

            if current_joints is None:
                    self.get_logger().warn("⚠️ safe_movel: 로봇 좌표가 일시적으로 None입니다. 다음 루프에서 재시도합니다.")
                    time.sleep(0.1) # 소켓 병목이 풀릴 시간을 의도적으로 제공
                    continue

            joint_dist = np.linalg.norm(np.array(list(pos)) - np.array(list(current_joints)))   # 목표 각도와 현재 관절 각도의 차이

            if joint_dist < 1.0:    # 차이가 1도 이하면 동작 완료
                break
            if not command_sent:
                movej(pos, vel=vel, acc=acc)    # 이동 명령 실행
                command_sent = True

            time.sleep(0.1)

    def qr_sub_robot_callback(self, msg):   # 받아온 QR 데이터 저장
        self.qr_data = msg.data

    def trigger_scan_and_pick(self, object):    # 물품 스캔하고 잡기
        if self.is_processing:      # 로봇이 이미 동작중이면 실행 X
            return

        if not self.get_camera_coord.wait_for_service(timeout_sec=1.0):     # YOLO와 서버 연결 실패 시
            self.get_logger().error("YOLO 비전 서버가 켜져있지 않습니다.")
            return
            
        self.is_processing = True       # 로봇 동작 시작
        self.object = object        # 현재 처리하는 물품

        request = FineTuneQr.Request()
        request.start = True
        request.object = object     # 스캔할 물품    
        
        self.get_logger().info("YOLO 비전 노드에 상품 3D 좌표 스캔 요청 전송...")      

        self.wait_with_pause(1)     # 비상 정지 상황을 감시하며 대기(하드웨어 흔들림 방지)
        future = self.get_camera_coord.call_async(request)      # 물품 스캔 후 좌표 요청

        while rclpy.ok() and not future.done():     # 좌표를 받아올 때 까지 대기
            self.wait_with_pause(0.1)
    
        camera_center_pos = None
        try:
            response = future.result()  
            if response and response.found:     # 물품 스캔 성고 시
                camera_center_pos = (response.offset.x, response.offset.y, response.offset.z)       # 물품의 정중앙 좌표
                self.found_object = response.detected_name      # 스캔 성공한 물품
                self.get_logger().info(f"비전 수신 성공 -> 카메라 기준 좌표: {camera_center_pos}")
            else:       # 스캔 실패 시
                self.get_logger().warn("YOLO가 화면에서 상품을 검출하지 못했습니다.")
                self.is_processing = False
                return False
        except Exception as e:
            self.get_logger().error(f"스캔 서비스 통신 중 오류 발생: {e}")
            self.is_processing = False
            return False

        # 실제 물리 제어 및 좌표 변환
        if camera_center_pos is not None:
            robot_coordinate = self.transform_to_base(camera_center_pos)        # YOLO 박스의 정중앙 좌표를 베이스 좌표계로 변환
            self.get_logger().info(f"변환된 로봇 절대 좌표 (Base): {robot_coordinate}")

            self.pick_and_move(*robot_coordinate)   # 베이스 좌표계로 이동해서 물품 집기
            
        self.is_processing = False      # 스캔 및 물품 집기 완료
        return True

    def get_robot_pose_matrix(self, x, y, z, rx, ry, rz):
        """현재 로봇의 포즈를 4x4 동차 변환 행렬로 만듭니다."""
        R = Rotation.from_euler("ZYZ", [rx, ry, rz], degrees=True).as_matrix()
        T = np.eye(4)
        T[:3, :3] = R
        T[:3, 3] = [x, y, z]
        return T

    def transform_to_base(self, camera_coords):
        """카메라 기준 3D 좌표에 로봇 포즈와 Hand-Eye 행렬을 곱해 베이스 좌표로 변환"""
        coord = np.append(np.array(camera_coords), 1)  # 4차원 동차 좌표 변환
        base2gripper = self.get_robot_pose_matrix(*self.get_safe_current_posx())

        base2cam = base2gripper @ self.gripper2cam
        td_coord = np.dot(base2cam, coord)

        return td_coord[:3]

    def wait_with_pause(self, seconds):
        for _ in range(int(seconds * 10)):
            if self.is_paused:
                time.sleep(0.5) # 정지 중이면 0.5초 간격으로 확인
            else:
                time.sleep(0.1) # 정상 중이면 0.1초 간격으로 확인

    def pick_and_move(self, x, y, z):
        """계산된 절대 좌표로 이동하여 물체를 잡고 놓는 함수"""
        current_pos = self.get_safe_current_posx()
        pick_pos1 = posx([x, y+200, z, current_pos[3], current_pos[4], current_pos[5]])    # 평면으로 이동(진열대와 부딪힘 방지)
        pick_pos2 = posx([x, y, z, current_pos[3], current_pos[4], current_pos[5]])     # 물품 잡기 위치 이동

        self.get_logger().info("목표 위치로 이동합니다.")
        self.gripper.open_gripper() 

        if self.behavior == "SCAN_AND_PICK_WAREHOUSE":      # 입고 모드 시(바구니에서 물품 잡기)
            self.safe_movel(pick_pos2, vel=VELOCITY, acc=ACC)
            if self.found_object == "smoke":
                pick_pos_down = posx(0, 0, -55, 0, 0, 0)
            elif self.found_object == "cup_noodle":
                pick_pos_down = posx(0, 0, -85, 0, 0, 0)
            else:
                pick_pos_down = posx(0, 0, -70, 0, 0, 0)
            self.safe_movel(pick_pos_down, vel=VELOCITY, acc=ACC, mod=DR_MV_MOD_REL)
            self.gripper.close_gripper()
            self.wait_with_pause(2)
            self.safe_movel(self.basket_up, vel=VELOCITY, acc=ACC)
        else:       # 진열대 상품을 잡을 시
            self.safe_movel(pick_pos1, vel=VELOCITY, acc=ACC)
            self.safe_movel(pick_pos2, vel=VELOCITY, acc=ACC)

            if self.object == "cup_noodle":     # 컵라면은 조금 더 앞으로 가서 잡기(너무 큼)
                pick_pos_front = posx(0, -100, 0, 0, 0, 0)
            else:
                pick_pos_front = posx(0, -70, 0, 0, 0, 0)
            self.safe_movel(pick_pos_front, vel=VELOCITY, acc=ACC, mod=DR_MV_MOD_REL)

            self.gripper.close_gripper()
            self.wait_with_pause(2)

            pick_pos_up = posx(0, 0, 20, 0, 0, 0)
            self.safe_movel(pick_pos_up, vel=VELOCITY, acc=ACC, mod=DR_MV_MOD_REL)

            pick_pos_back = posx(0, 200, 0, 0, 0, 0)
            self.safe_movel(pick_pos_back, vel=VELOCITY, acc=ACC, mod=DR_MV_MOD_REL)

    def trigger_qr_scan(self):
        self.get_logger().info("📸 QR 스캔 위치로 이동합니다.")
        self.safe_movel(self.qr_home, vel=VELOCITY, acc=ACC)

        num = 0
        self.qr_data = ""

        while rclpy.ok():
            self.wait_with_pause(2)
            if self.qr_data != "" and self.qr_data != self.last_qr_data:   # QR 인식 성공
                break

            if num == 0:
                self.safe_movel(
                    [0, 60, 0, 0, 0, 0],
                    vel=VELOCITY,
                    acc=ACC,
                    mod=DR_MV_MOD_REL,
                    ref=DR_TOOL,
                )
                num = 1
            else:
                self.safe_movel(
                    [0, -60, 0, 0, 0, 0],
                    vel=VELOCITY,
                    acc=ACC,
                    mod=DR_MV_MOD_REL,
                    ref=DR_TOOL,
                )
                num = 0

            self.wait_with_pause(3)
            if self.qr_data != "" and self.qr_data != self.last_qr_data:
                break
            self.safe_movel(
                [0, 0, 0, 0, 0, 179],
                vel=VELOCITY,
                acc=ACC,
                mod=DR_MV_MOD_REL,
                ref=DR_TOOL,
            )
            self.wait_with_pause(3)
            if self.qr_data != "" and self.qr_data != self.last_qr_data:
                break
            self.safe_movel(
                [0, 0, 0, 0, 0, -179],
                vel=VELOCITY,
                acc=ACC,
                mod=DR_MV_MOD_REL,
                ref=DR_TOOL,
            )

        self.last_qr_data = self.qr_data    # QR 데이터 업데이트
        result = True

        return result, self.qr_data

    def execute_callback(self, goal_handle):
        result = RobotPickPlace.Result()

        self.behavior = goal_handle.request.behavior_name   # 실행해야하는 동작
        object = goal_handle.request.object_name            # 처리해야하는 물품
        place = goal_handle.request.place
        object_found = goal_handle.request.object_found

        if self.behavior == "MOVE_HOME":     # 초기 위치 이동
            self.safe_movej(self.home, vel=VELOCITY, acc=ACC)   
            result.success = True
            goal_handle.succeed()
            return result
        
        elif self.behavior == "MOVE_SCAN":   # 물품 스캔 지점 이동
            self.safe_movej(self.scan_home_waypoint, vel=VELOCITY, acc=ACC)
            self.safe_movel(self.scan_home, vel=VELOCITY, acc=ACC)
            result.success = True
            goal_handle.succeed()
            return result
        
        elif self.behavior == "SCAN_AND_PICK":  # 물품을 스캔하고 잡기
            success = self.trigger_scan_and_pick(object)
            if success:
                result.success = True
                goal_handle.succeed()
            else:
                result.success = False
                goal_handle.abort()
            return result
        
        elif self.behavior == "QR_SCAN":        # QR 스캔하기
            success, qr_data = self.trigger_qr_scan()
            if success:
                result.success = True
                result.qr_data = qr_data    # 인식한 QR 데이터 반환
                goal_handle.succeed()
            else:
                result.success = False
                goal_handle.abort()
            return result
        
        elif self.behavior == "PLACE_BASKET":   # 장바구니에 물품 놓기
            self.safe_movel(self.basket_up, vel=VELOCITY, acc=ACC)
            self.safe_movel(self.basket_down, vel=VELOCITY, acc=ACC)
            self.gripper.open_gripper()
            self.safe_movel(self.basket_up, vel=VELOCITY, acc=ACC)
            result.success = True
            goal_handle.succeed()
            return result

        elif self.behavior == "MOVE_SCAN_BASKET":   # 바구니 위 물품 스캔 위치로 이동(입고)
            self.safe_movej(self.scan_home_waypoint, vel=VELOCITY, acc=ACC)
            self.safe_movel(self.scan_basket_home, vel=VELOCITY, acc=ACC)
            result.success = True
            goal_handle.succeed()
            return result
        
        elif self.behavior == "SCAN_AND_PICK_WAREHOUSE":    # 스캔하고 물품 잡기(입고)
            success = self.trigger_scan_and_pick(object="all")
            if success:
                result.success = True
                result.found_object = self.found_object     # 스캔한 물품 반환
                goal_handle.succeed()
            else:
                result.success = False
                goal_handle.abort()
            return result
        
        elif self.behavior == "DROP_TEMP1":     # QR 스캔한 물품 놓기(입고 / 유통기한 비교)
            self.safe_movel(self.drop_temp1, vel=VELOCITY, acc=ACC)
            self.safe_movel([0, 0, -50, 0, 0, 0], vel=VELOCITY, acc=ACC, mod=DR_MV_MOD_REL)
            self.gripper.open_gripper()
            self.wait_with_pause(2)
            self.safe_movel([0, 0, 50, 0, 0, 0], vel=VELOCITY, acc=ACC, mod=DR_MV_MOD_REL)
            result.success = True
            goal_handle.succeed()
            return result
        
        elif self.behavior == "DROP_TEMP2":     # 진열대 위치한 물품 놓기(입고 / 유통기한 비교)
            self.safe_movel(self.drop_temp2, vel=VELOCITY, acc=ACC)
            self.safe_movel([0, 0, -50, 0, 0, 0], vel=VELOCITY, acc=ACC, mod=DR_MV_MOD_REL)
            self.gripper.open_gripper()
            self.wait_with_pause(2)
            self.safe_movel([0, 0, 50, 0, 0, 0], vel=VELOCITY, acc=ACC, mod=DR_MV_MOD_REL)
            result.success = True
            goal_handle.succeed()
            return result

        elif self.behavior == "INSERT_TO_FRONT":     
            self.process_insert_behavior(goal_handle, result, place, is_front=True)
            return result

        elif self.behavior == "INSERT_TO_BACK":    
            self.process_insert_behavior(goal_handle, result, place, is_front=False)
            return result
        
        elif self.behavior == "DISPOSE_OBJECT": 
            self.safe_movel(self.basket_up, vel=VELOCITY, acc=ACC)
            self.safe_movel(self.basket_down, vel=VELOCITY, acc=ACC)
            self.gripper.open_gripper()
            self.safe_movel(self.basket_up, vel=VELOCITY, acc=ACC)
            result.success = True
            goal_handle.succeed()
            return result
        
        else:
            self.get_logger().warn("알 수 없는 명령입니다.")
            result.success = False
            goal_handle.abort()
            return result 
        
    def process_insert_behavior(self, goal_handle, result, place, is_front=True):
        
        # 앞/뒤 모드에 따른 가변 매개변수 매pping
        config = {
            True: {  # FRONT 모드
                "check_place": 2,
                "temp_pos": self.drop_temp2,
                "restock_y": -70,
                "retreat_y": 200
            },
            False: { # BACK 모드
                "check_place": 1,
                "temp_pos": self.drop_temp1,
                "restock_y": -150,
                "retreat_y": 210
            }
        }[is_front]

        # 1. 임시 적재함 회수 단계
        if place == 0:
            self.safe_movel(self.scan_home, vel=VELOCITY, acc=ACC)
        elif place == config["check_place"]:
            self.safe_movel(config["temp_pos"], vel=VELOCITY, acc=ACC)
            self.gripper.open_gripper()
            self.wait_with_pause(2)
            self.safe_movel([0, 0, -50, 0, 0, 0], vel=VELOCITY, acc=ACC, mod=DR_MV_MOD_REL)
            self.gripper.close_gripper()
            self.wait_with_pause(2)
            self.safe_movel([0, 0, 150, 0, 0, 0], vel=VELOCITY, acc=ACC, mod=DR_MV_MOD_REL)
            self.safe_movel(self.scan_home, vel=VELOCITY, acc=ACC)

        # 2. 본 매대 진열 단계 (기존 매핑 함수 coord_products 활용)
        position = self.coord_products(self.found_object)
        self.safe_movel(position, vel=VELOCITY, acc=ACC)
        
        # 앞/뒤 오프셋 반영하여 밀어넣기
        restock_offset = posx([0, config["restock_y"], 0, 0, 0, 0])
        self.safe_movel(restock_offset, vel=VELOCITY, acc=ACC, mod=DR_MV_MOD_REL)
        self.safe_movel([0, 0, -20, 0, 0, 0], vel=VELOCITY, acc=ACC, mod=DR_MV_MOD_REL)
        
        self.gripper.open_gripper()
        self.wait_with_pause(2)

        # 진열 후 뒤로 안전 퇴각 후 홈 복귀
        pick_pos_back = posx([0, config["retreat_y"], 0, 0, 0, 0])
        self.safe_movel(pick_pos_back, vel=VELOCITY, acc=ACC, mod=DR_MV_MOD_REL)
        self.safe_movel(self.scan_home, vel=VELOCITY, acc=ACC)
        
        # 액션 성공 깃발 세우기
        result.success = True
        goal_handle.succeed()

    def coord_products(self, object_found):     
        if object_found == "drink":
            return self.drop_drink
        elif object_found == "jjolbyung":
            return self.drop_jjolbyung    
        elif object_found == "coffee":
            return self.drop_coffee   
        elif object_found == "smoke":
            return self.drop_smoke 
        elif object_found == "cup_noodle":
            return self.drop_cup_noodle
        elif object_found == "choco":
            return self.drop_choco

    def pause_callback(self, msg):
        self.is_paused = True       # 정지 명령
        self.get_logger().error("로봇 제어부: 일시 정지 명령 수신!")

    def resume_callback(self, msg):
        if not self.is_paused:
            return 
            
        # 처음 한 번만 실행됨
        self.is_paused = False      # 재개 명령
        self.get_logger().info("로봇 제어부: 동작 재개!")

def main(args=None):
    """프로그램 실행의 핵심 진입점이 되는 메인 함수"""
    rclpy.init(args=args)
    
    node = rclpy.create_node("dsr_example_demo_py", namespace=ROBOT_ID)
    DR_init.__dsr__id = ROBOT_ID
    DR_init.__dsr__model = ROBOT_MODEL
    DR_init.__dsr__node = node

    try:
        global get_current_posx, get_current_posj, movej, movel, wait, DR_MV_MOD_REL, posx, posj, DR_TOOL
        from DSR_ROBOT2 import get_current_posx, get_current_posj, movej, movel, wait, DR_MV_MOD_REL, DR_TOOL
        from DR_common2 import posx, posj
    except ImportError as e:
        print(f"두산로봇 라이브러리(DSR_ROBOT2) 임포트 오류 발생: {e}")
        return

    robot_control_node = RoobotControlNode()
    executor = MultiThreadedExecutor()
    executor.add_node(robot_control_node)

    try:
        executor.spin()
    except KeyboardInterrupt:
        print("\n[INFO] 사용자의 인터럽트 신호로 안전 종료를 시작합니다.")
    finally:
        robot_control_node.destroy_node()
        node.destroy_node()
        rclpy.shutdown()

if __name__ == "__main__":
    main()
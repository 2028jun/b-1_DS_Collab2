import os
import rclpy
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.action import ActionServer
from store_interfaces.srv import FineTuneQr, ScanCounterQr
from store_node.realsense import ImgNode
from scipy.spatial.transform import Rotation
from store_node.onrobot import RG
from store_interfaces.action import RobotPickPlace

import time
import numpy as np
import DR_init

# 두산 로봇 설정 전역 변수
ROBOT_ID = "dsr01"
ROBOT_MODEL = "m0609"
VELOCITY, ACC = 50, 50

GRIPPER_NAME = "rg2"
TOOLCHARGER_IP = "192.168.1.1"
TOOLCHARGER_PORT = "502"

class RoobotControlNode(Node):
    def __init__(self):
        super().__init__("robot_control_node")

        # 비전 노드(YOLO)에 3D 좌표를 요청할 서비스 클라이언트 
        self.get_camera_coord = self.create_client(
            FineTuneQr,
            'fine_tune_qr',
        )

        self.robot_action_server = ActionServer(    # 로봇 액션 명령을 수신 받을 서버
            self,
            RobotPickPlace,
            '/pickup_and_place',
            self.execute_callback
        )

        self.scan_qr = self.create_client(      # QR 코드 인식 요청
            ScanCounterQr,
            'scan_counter_qr',
        )

        self.img_node = ImgNode()
        rclpy.spin_once(self.img_node)
        time.sleep(1)
        self.intrinsics = self.img_node.get_camera_intrinsic()
        
        current_dir = os.path.dirname(os.path.abspath(__file__))
        npy_path = os.path.join(current_dir, "T_gripper2camera.npy")

        self.get_logger().info(f"캘리브레이션 파일 로드 시도: {npy_path}")
        self.gripper2cam = np.load(npy_path)
        self.gripper = RG(GRIPPER_NAME, TOOLCHARGER_IP, TOOLCHARGER_PORT)
        
        self.is_processing = False  # 작업 중 중복 요청 방지용 플래그
        
        self.basket_up = posx([336, 427.5, 125.02, 46.75, -180, 140])
        self.basket_down = posx([336, 427.5, -150, 46.75, -180, 140])
        self.qr_home = posx([615.5, 0.13, 80.89, 138.88, -180, -130])
        self.scan_home_waypoint = posj([16.62, 24.93, 98.92, 105.82, -102.11, 33.04]) 
        self.home = posj([0, 0, 90, 0, 90, 0]) 
        self.scan_home = posx([485.63, -12.59, 167.73, 88.87, -87.93, -90.68])

        movej(self.home, vel=VELOCITY, acc=ACC) # 로봇 가동시 초기 자세로 이동
        self.gripper.open_gripper()
        self.get_logger().info("robot_control_node 실행")

    def trigger_scan_and_pick(self, object):
        if self.is_processing:
            return

        if not self.get_camera_coord.wait_for_service(timeout_sec=1.0):
            self.get_logger().error("YOLO 비전 서버가 켜져있지 않습니다.")
            return
            
        self.is_processing = True
        request = FineTuneQr.Request()
        request.start = True
        request.object = object
        
        self.get_logger().info("YOLO 비전 노드에 상품 3D 좌표 스캔 요청 전송...")       # 물품 스캔 요청

        wait(1)
        future = self.get_camera_coord.call_async(request)

        while rclpy.ok() and not future.done():  
            time.sleep(0.05)
                
    
        camera_center_pos = None
        try:
            response = future.result()  
            if response and response.found:
                camera_center_pos = (response.offset.x, response.offset.y, response.offset.z)
                self.get_logger().info(f"비전 수신 성공 -> 카메라 기준 좌표: {camera_center_pos}")
            else:
                self.get_logger().warn("YOLO가 화면에서 상품을 검출하지 못했습니다.")
                self.is_processing = False
                return False
        except Exception as e:
            self.get_logger().error(f"스캔 서비스 통신 중 오류 발생: {e}")
            self.is_processing = False
            return False

        # 실제 물리 제어 및 좌표 변환
        if camera_center_pos is not None:
            robot_coordinate = self.transform_to_base(camera_center_pos)
            self.get_logger().info(f"변환된 로봇 절대 좌표 (Base): {robot_coordinate}")

            self.pick_and_move(*robot_coordinate)
        
        self.is_processing = False
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
        base2gripper = self.get_robot_pose_matrix(*get_current_posx()[0])

        base2cam = base2gripper @ self.gripper2cam
        td_coord = np.dot(base2cam, coord)

        return td_coord[:3]

    def pick_and_move(self, x, y, z):
        """계산된 절대 좌표로 이동하여 물체를 잡고 놓는 함수"""
        current_pos = get_current_posx()[0]
        pick_pos1 = posx([x, current_pos[1], z, current_pos[3], current_pos[4], current_pos[5]])
        pick_pos2 = posx([x, y, z, current_pos[3], current_pos[4], current_pos[5]])
        
        self.get_logger().info("목표 상공 위치로 이동합니다.")
        self.gripper.open_gripper()
        movel(pick_pos1, vel=VELOCITY, acc=ACC)
        movel(pick_pos2, vel=VELOCITY, acc=ACC)

        pick_pos_front = posx(0, -70, 0, 0, 0, 0)
        movel(pick_pos_front, vel=VELOCITY, acc=ACC, mod=DR_MV_MOD_REL)

        self.gripper.close_gripper()
        wait(2)

        pick_pos_up = posx(0, 0, 20, 0, 0, 0)
        movel(pick_pos_up, vel=VELOCITY, acc=ACC, mod=DR_MV_MOD_REL)

        pick_pos_back = posx(0, 200, 0, 0, 0, 0)
        movel(pick_pos_back, vel=VELOCITY, acc=ACC, mod=DR_MV_MOD_REL)

        movel(self.scan_home, vel=VELOCITY, acc=ACC)

    def trigger_qr_scan(self):
        self.get_logger().info("📸 QR 스캔 위치로 이동합니다.")
        movel(self.qr_home, vel=VELOCITY, acc=ACC) 

        req = ScanCounterQr.Request()
        req.start = True
        
        future = self.scan_qr.call_async(req)

        num = 0

        while rclpy.ok() and not future.done():
            wait(3)
            if future.done():
                break
            if num == 0:
                movel([0, 60, 0, 0, 0, 0], vel=VELOCITY, acc=ACC, ref=DR_TOOL)
                num = 1
            else:
                movel([0, -60, 0, 0, 0, 0], vel=VELOCITY, acc=ACC, ref=DR_TOOL)
                num = 0

            wait(3)
            if future.done():
                break
            movel([0, 0, 0, 0, 0, 179], vel=VELOCITY, acc=ACC, ref=DR_TOOL)
            wait(3)
            if future.done():
                break
            movel([0, 0, 0, 0, 0, -179], vel=VELOCITY, acc=ACC, ref=DR_TOOL)

        qr_data = None
        try:
            response = future.result()
            if response and response.success: 
                self.get_logger().info("QR 스캔 및 카운팅 성공!")
                qr_data = response.qr_data 
                result = True
            else:
                self.get_logger().warn("QR 인식 실패 또는 매칭되는 코드가 없습니다.")
                result = False
        except Exception as e:
            self.get_logger().error(f"QR 스캔 서비스 통신 중 에러 발생: {e}")
            result = False

        return result, qr_data

    def execute_callback(self, goal_handle):
        result = RobotPickPlace.Result()

        behavior = goal_handle.request.behavior_name
        object = goal_handle.request.object_name      

        if behavior == "MOVE_HOME":     # 초기 위치 이동 요청받을 때
            movej(self.home, vel=VELOCITY, acc=ACC)
            result.success = True
            goal_handle.succeed()
            return result
        
        elif behavior == "MOVE_SCAN":   # 물품 스캔 지점 이동 요청 받을 때
            movej(self.scan_home_waypoint, vel=VELOCITY, acc=ACC)
            movel(self.scan_home, vel=VELOCITY, acc=ACC)
            result.success = True
            goal_handle.succeed()
            return result
        
        elif behavior == "SCAN_AND_PICK":
            success = self.trigger_scan_and_pick(object)
            if success:
                result.success = True
                goal_handle.succeed()
            else:
                result.success = False
                goal_handle.abort()
            return result
        
        elif behavior == "QR_SCAN":
            success, qr_data = self.trigger_qr_scan()
            if success:
                result.success = True
                result.qr_data = qr_data
                goal_handle.succeed()
            else:
                result.success = False
                goal_handle.abort()
            return result
        
        elif behavior == "PLACE_BASKET":
            movel(self.basket_up, vel=VELOCITY, acc=ACC)
            movel(self.basket_down, vel=VELOCITY, acc=ACC)
            self.gripper.open_gripper()
            movel(self.basket_up, vel=VELOCITY, acc=ACC)
            result.success = True
            goal_handle.succeed()
            return result


        else:
            self.get_logger().warn("알 수 없는 명령입니다.")
            result.success = False
            goal_handle.abort()
            return result 

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
    print("==================================================")
    print(f"로봇 자동 픽킹 시스템 가동 (모델: {ROBOT_MODEL}, ID: {ROBOT_ID})")
    print("==================================================")
    
    # 💡 [정석 패턴] 액션 서버와 비전 서비스 클라이언트가 꼬이지 않고 멀티스레드로 동시 스핀되도록 설정
    executor = MultiThreadedExecutor()
    executor.add_node(robot_control_node)

    try:
        # main 루프의 무한 루프 수동 코드를 지우고, ROS2 공식 멀티스레드 엔진에게 제어권을 넘깁니다.
        executor.spin()
    except KeyboardInterrupt:
        print("\n[INFO] 사용자의 인터럽트 신호로 안전 종료를 시작합니다.")
    finally:
        robot_control_node.destroy_node()
        node.destroy_node()
        rclpy.shutdown()

if __name__ == "__main__":
    main()

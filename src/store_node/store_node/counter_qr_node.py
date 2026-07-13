import time
import cv2
import rclpy
from rclpy.node import Node
from std_msgs.msg import String, Bool

class CounterQrNode(Node):
    def __init__(self):
        super().__init__('counter_qr_node')

        self.qr_detector = cv2.QRCodeDetector()    

        self.webcam_index = self.declare_parameter('webcam_index', 9).value     # QR 인식 캠 장치 index
        self.show_counter_camera = self.declare_parameter('show_counter_camera', True).value    # 
        
        self.detect_interval = 0.1  # 0.1초에 한 번씩만 QR 디코딩 진행 (CPU 보호)
        self.last_detect_time = 0.0

        # 카메라 장치 열기
        self.camera_source = self.webcam_index
        self.cap = cv2.VideoCapture(self.camera_source)
        
        if not self.cap.isOpened():
            self.get_logger().error(f'C270 open failed: source={self.camera_source}')
        else:
            self.get_logger().info(f'C270 카메라 연결 성공: source={self.camera_source}')

        if self.show_counter_camera:        # 카메라 화면을 출력할 창 띄우기
            cv2.namedWindow('Counter C270 View', cv2.WINDOW_NORMAL)
            cv2.moveWindow('Counter C270 View', 700, 50)

        self.is_robot_busy = False
        self.admin_is_robot_busy = False
        self.last_qr_data = ""

        # 퍼블리셔
        self.qr_pub_robot = self.create_publisher(String, '/counter_qr_data_robot', 10)     # robot_control에 QR 데이터 퍼플리시
        self.qr_pub_db= self.create_publisher(String, '/counter_qr_data_db', 10)            # database_manager에 QR 데이터 퍼블리시

        # 서브스크라이버
        self.auth_sub = self.create_subscription(String, '/store_state', self.auth_mode_callback, 10)       # 로봇이 동작하고 있는지를 가져옴
        self.admin_state_sub = self.create_subscription(Bool, '/admin_state', self.admin_state_callback, 10)    # 로봇이 동작하고 있는지를 가져옴

    def admin_state_callback(self, msg):        # 로봇의 상태 업데이트
            self.admin_is_robot_busy = msg.data
 
    def auth_mode_callback(self, msg):      # 로봇의 상태 업데이트
        try:
            parts = msg.data.split(',')
            self.is_robot_busy = (parts[1].strip() == 'True')
            
        except Exception as e:
            self.get_logger().error(f"마스터 상태 토픽 파싱 에러: {e}")
        
    def process_continuous_scan(self):
        if not self.cap.isOpened():
            return

        ok, frame = self.cap.read()
        if not ok:
            return

        if self.show_counter_camera:
            cv2.imshow('Counter C270 View', frame)
            cv2.waitKey(1)

        # 주기 체크 (매 프레임마다 QR을 디코딩하면 CPU가 터지므로 0.1초마다 제한)
        now = time.time()
        if (now - self.last_detect_time) < self.detect_interval:
            return
        self.last_detect_time = now

        # QR 코드 검출 시도
        try:
            data, _, _ = self.qr_detector.detectAndDecode(frame)
        except cv2.error as e:
            # convexHull, contourArea 등 OpenCV C++ 내부에서 터지는 모든 에러를 안전하게 포획
            self.get_logger().warn(f"⚠️ OpenCV 내부 기하학 연산 오류 방어 (convexHull 등): {e}")
            return # 프레임 버리고 다음 프레임으로 통과
        except Exception as e:
            # 그 외에 발생할 수 있는 모든 파이썬 런타임 예외 방어
            self.get_logger().warn(f"⚠️ QR 디코딩 파싱 예외 방어: {e}")
            return
        
        if data:
            if data == self.last_qr_data:   # 같은 QR을 인식했을 때
                self.last_success_time = now
                return
                 
            self.last_qr_data = data      
            self.last_success_time = now

            msg = String()
            msg.data = data
            if self.is_robot_busy is True:    # 로봇이 QR 찍을 때
                self.qr_pub_robot.publish(msg)  
                self.get_logger().info(f'QR 코드 인식 및 전송 성공(로봇): {data}')
            elif self.admin_is_robot_busy is True:         # 입고시 로봇이 QR을 찍었을 때
                self.qr_pub_db.publish(msg)
                self.qr_pub_robot.publish(msg)  
                self.get_logger().info(f'QR 코드 인식 및 전송 성공(입고/폐기): {data}')
            else:                # 사람이 직접 QR 찍을 때 
                self.qr_pub_db.publish(msg)                    
                self.qr_pub_robot.publish(msg)  
                self.get_logger().info(f'QR 코드 인식 및 전송 성공(직접): {data}')
        else:
            if hasattr(self, 'last_success_time') and (now - self.last_success_time) > 1.5:
                if self.last_qr_data != "":
                    self.last_qr_data = ""

    def destroy_node(self):
        if self.cap.isOpened():
            self.cap.release()
        cv2.destroyAllWindows()
        super().destroy_node()

def main(args=None):
    rclpy.init(args=args)
    node = CounterQrNode()

    try:
        while rclpy.ok():
            rclpy.spin_once(node, timeout_sec=0.01)
            node.process_continuous_scan() 
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
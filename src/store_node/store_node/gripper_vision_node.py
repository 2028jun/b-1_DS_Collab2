import os
import numpy as np

import time
import cv2
import rclpy
from cv_bridge import CvBridge
from geometry_msgs.msg import Point
from rclpy.node import Node
from sensor_msgs.msg import CameraInfo, Image
from store_interfaces.srv import FineTuneQr
from std_msgs.msg import Bool, Empty

try:
    from ultralytics import YOLO
    YOLO_IMPORT_ERROR = None
except ImportError as exc:
    YOLO = None
    YOLO_IMPORT_ERROR = exc


def get_default_model_path():
    current_file_path = os.path.abspath(__file__)
    
    current_dir = os.path.dirname(current_file_path)
    
    package_root = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
    
    resolved_path = os.path.join(package_root, "best.pt")
    
    if not os.path.exists(resolved_path):
        return os.path.abspath("best.pt")
        
    return resolved_path

class GripperVisionNode(Node):
    """RealSense D435i 이미지에서 YOLO로 상품을 찾고 depth 기반 3D 좌표를 계산"""

    def __init__(self):
        super().__init__('gripper_vision_node')

        self.bridge = CvBridge()

        self.scan_timeout = self.declare_parameter('scan_timeout', 3.0).value
        self.show_realsense = self.declare_parameter('show_realsense', True).value
        self.show_realsense_status = self.declare_parameter(
            'show_realsense_status',
            False,
        ).value

        # YOLO가 사용할 학습된 모델 파일(best.pt) 경로
        self.model_path = self.declare_parameter(
            'model_path',
            get_default_model_path(),
        ).value
        self.conf_threshold = self.declare_parameter('conf_threshold', 0.5).value
        self.detect_interval = self.declare_parameter('detect_interval', 0.5).value
        self.last_detect_time = 0.0
        self.last_emergency_stop_time = 0.0

        # CameraInfo에서 받은 내부 파라미터, 픽셀 좌표를 3D 좌표로 바꿀 때 사용
        self.fx = 0.0
        self.fy = 0.0
        self.ppx = 0.0
        self.ppy = 0.0

        self.rs_color_frame = None
        self.rs_depth_frame = None
        self.latest_detections = []
        self.realsense_window_name = 'RealSense Gripper View'

        self.model = self.load_yolo_model(self.model_path)

        if self.show_realsense:
            cv2.namedWindow(self.realsense_window_name, cv2.WINDOW_NORMAL)
            cv2.moveWindow(self.realsense_window_name, 250, 250)

        self.color_subscription = self.create_subscription(
            Image,
            '/camera/camera/color/image_raw',
            self.realsense_color_callback,
            10,
        )

        self.depth_subscription = self.create_subscription(
            Image,
            '/camera/camera/aligned_depth_to_color/image_raw',
            self.realsense_depth_callback,
            10,
        )
        
        self.camera_info_subscription = self.create_subscription(
            CameraInfo,
            '/camera/camera/color/camera_info',
            self.camera_info_callback,
            10,
        )

        self.realsense_status_timer = None
        if self.show_realsense_status:
            self.realsense_status_timer = self.create_timer(
                2.0,
                self.log_realsense_status,
            )
        
        self.detection_timer = self.create_timer(
            self.detect_interval,
            self.update_detections_for_display,
        )

        # --------------------------------------------------------------------------------
        self.hand_classes_text = self.declare_parameter('hand_classes','hand').value
        self.hand_conf_threshold = self.declare_parameter('hand_conf_threshold', 0.5).value
        self.emergency_stop_cooldown = self.declare_parameter('emergency_stop_cooldown', 1.0).value
        self.target_class = self.declare_parameter('target_class', '').value
        self.ignore_classes_text = self.declare_parameter('ignore_classes', 'gripper, robot').value     # 그리퍼, 로봇 인식 제외

        self.hand_classes = {           # {hand}
            class_name.strip().lower()
            for class_name in self.hand_classes_text.split(',')
            if class_name.strip()
        }
        
        self.ignore_classes = {     # {gripper, robot}
            class_name.strip()
            for class_name in self.ignore_classes_text.split(',')
            if class_name.strip()
        }

        # 퍼블리셔
        self.scan_key_card = self.create_publisher(Bool, 'key_card', 10)    # 키 카드 인식 여부 퍼블리시
        self.emergency_stop_pub = self.create_publisher(Empty, '/emergency_stop', 10)
        
        # 서비스 서버
        self.create_service(    # 인식한 물품의 3D 좌표를 계산
            FineTuneQr,
            'fine_tune_qr',
            self.handle_fine_tune_qr,
        )

        self.get_logger().info('비전 인식 노드 시작')

    def load_yolo_model(self, model_path):      # YOLO 모델 가져오기
        """Ultralytics YOLO 모델을 로드"""
        if YOLO is None:
            self.get_logger().error(
                f'Failed to import ultralytics: {YOLO_IMPORT_ERROR}. '
                'Install or fix ultralytics before YOLO inference.'
            )
            return None

        resolved_path = os.path.expanduser(model_path)
        if not os.path.isabs(resolved_path):
            resolved_path = os.path.abspath(resolved_path)

        if not os.path.exists(resolved_path):
            self.get_logger().warn(f'YOLO model file not found: {resolved_path}')
            return None

        self.get_logger().info(f'Loading YOLO model: {resolved_path}')
        return YOLO(resolved_path)

    def realsense_color_callback(self, msg):
        """RealSense 컬러 이미지를 최신 프레임으로 저장합니다."""
        try:
            self.rs_color_frame = self.bridge.imgmsg_to_cv2(
                msg,
                desired_encoding='bgr8',
            )
        except Exception as e:
            self.get_logger().error(f'RealSense color callback error: {e}')

    def realsense_depth_callback(self, msg):
        """RealSense depth 이미지를 최신 프레임으로 저장합니다."""
        try:
            self.rs_depth_frame = self.bridge.imgmsg_to_cv2(
                msg,
                desired_encoding='passthrough',
            )
        except Exception as e:
            self.get_logger().error(f'RealSense depth callback error: {e}')

    def camera_info_callback(self, msg):
        """픽셀 좌표를 3D 좌표로 바꿀 때 필요한 카메라 내부 파라미터를 저장"""
        self.fx = float(msg.k[0])
        self.fy = float(msg.k[4])
        self.ppx = float(msg.k[2])
        self.ppy = float(msg.k[5])

    def display_realsense_frame(self):
        """RealSense 화면을 계속 갱신하고, YOLO 결과 박스를 그립니다."""
        if not self.show_realsense or self.rs_color_frame is None:
            return

        frame = self.rs_color_frame.copy()
        for det in self.latest_detections:
            x1, y1, x2, y2 = det['box']
            label = f"{det['name']} {det['score']:.2f}"
            box_color = (0, 0, 255) if det.get('is_hand') else (0, 255, 0)
            cv2.rectangle(frame, (x1, y1), (x2, y2), box_color, 2)
            if det.get('is_hand'):
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 3)
            cv2.circle(frame, det['center'], 4, (0, 0, 255), -1)
            cv2.putText(
                frame,
                label,
                (x1, max(20, y1 - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 255, 0),
                2,
            )

            if det['name'] == "card":       # 키 카드 인식 시 True를 퍼블리시
                msg = Bool()
                msg.data = True
                self.scan_key_card.publish(msg)

        cv2.imshow(self.realsense_window_name, frame)
        cv2.waitKey(1)
    
    def update_detections_for_display(self):
        """화면 표시용 YOLO 추론을 일정 주기로 실행합니다."""
        now = time.time()
        if (now - self.last_detect_time) < self.detect_interval:
            return

        self.last_detect_time = now
        self.detect_product_from_realsense(log_warning=False)

    def log_realsense_status(self):
        """RealSense 프레임 수신 상태를 로그로 확인"""
        if self.rs_color_frame is None:
            self.get_logger().warn('RealSense color frame is not received yet')
            return

        height, width = self.rs_color_frame.shape[:2]
        self.get_logger().info(f'RealSense color frame received: {width}x{height}')

    def handle_fine_tune_qr(self, request, response):
        """YOLO로 상품 중심을 찾고 카메라 기준 3D 좌표를 반환합니다.
        """
        self.target_class = request.object  # 인식해야할 물품
        response.offset = Point()
        response.found = False

        if not request.start:
            return response

        detection = self.detect_product_from_realsense()    # 인식한 물품의 정보
        if detection is None:
            self.get_logger().warn('Product was not detected by YOLO')
            return response

        point = self.pixel_to_camera_point(*detection['center'])    # 인식한 물품의 중앙점 좌표 
        if point is None:
            self.get_logger().warn('Failed to convert product pixel to 3D point')
            return response

        response.offset = point
        response.found = True
        response.detected_name = detection['name']      # 인식한 물품 전송
        
        self.get_logger().info(
            f"Detected {detection['name']} score={detection['score']:.2f} "
            f"point=({point.x:.1f}, {point.y:.1f}, {point.z:.1f})"
        )
        return response

    def detect_product_from_realsense(self, log_warning=True):
        """현재 RealSense 컬러 프레임에서 YOLO로 상품을 찾습니다."""
        if self.model is None:
            if log_warning:
                self.get_logger().warn('YOLO model is not loaded')
            return None

        if self.rs_color_frame is None:
            if log_warning:
                self.get_logger().warn('RealSense color frame is not ready')
            return None

        frame = self.rs_color_frame.copy()
        inference_conf = min(self.conf_threshold, self.hand_conf_threshold)     # 물품과 손 인식 score 중 낮은 score을 채택하여 손과 물품을 동시에 인식할 수 있도록 함
        results = self.model(frame, conf=inference_conf, verbose=False)         # YOLO 인식 결과

        if not results:
            self.latest_detections = []
            return None

        result = results[0]
        display_detections = []
        product_detections = []
        names = result.names

        for box in result.boxes:
            score = float(box.conf[0])
            class_id = int(box.cls[0])
            name = names.get(class_id, str(class_id))
            normalized_name = name.lower()
            is_hand = normalized_name in self.hand_classes  # 인식된 결과에 손이 있으면 True

            x1, y1, x2, y2 = [int(v) for v in box.xyxy[0].tolist()]
            cx = int((x1 + x2) / 2)
            cy = int((y1 + y2) / 2)
            detection = {
                'box': (x1, y1, x2, y2),
                'center': (cx, cy),
                'name': name,
                'score': score,
                'is_hand': is_hand,
            }

            if is_hand and score >= self.hand_conf_threshold: # 손이 검출되었고 최소 score보다 높을 때
                self.publish_emergency_stop(name, score)    # 정지 명령 퍼블리시
                display_detections.append(detection)
                continue

            if score < self.conf_threshold:     # score 값이 낮으면 패스
                continue

            # gripper처럼 로봇 부품으로 학습된 클래스는 상품으로 쓰지 않도록 제외
            if name in self.ignore_classes:
                continue

            # target_class를 지정한 경우에는 원하는 상품 클래스만 추출
            if self.target_class and self.target_class != "all" and name != self.target_class:
                display_detections.append(detection)
                continue
            
            display_detections.append(detection)    # 화면에 표시할 물품 추가
            product_detections.append(detection)    # 인식해야할 물품을 리스트에 추가(all인 경우 모두 추가)

        self.latest_detections = display_detections
        if not product_detections:
            return None

        return max(product_detections, key=lambda det: det['score'])    # 가장 높은 score을 가진 한 물체만 반환

    def publish_emergency_stop(self, class_name, score):
        now = time.time()
        if (now - self.last_emergency_stop_time) < self.emergency_stop_cooldown:
            return

        self.last_emergency_stop_time = now
        self.emergency_stop_pub.publish(Empty())    # 정지 명령 퍼블리시
        self.get_logger().error(f'Human hand detected: {class_name} score={score:.2f}. ')

    def pixel_to_camera_point(self, x, y):
        """픽셀 좌표와 depth를 카메라 기준 3D 좌표로 변환합니다."""
        if self.rs_depth_frame is None or self.fx == 0.0 or self.fy == 0.0:
            return None

        height, width = self.rs_depth_frame.shape[:2]
        if not (0 <= x < width and 0 <= y < height):
            return None

        patch = self.rs_depth_frame[y-10:y+11, x-10:x+11]       # 11 by 11 면적의 깊이 값
        valid = patch[patch > 0]    # 유효한 깊이 값 필터링

        if len(valid) == 0: 
            return None

        z = float(np.median(valid))     # 깊이 값의 중앙값을 z로 설정

        # 핀홀 카메라 모델 공식으로 픽셀 좌표를 카메라 기준 x, y, z 좌표로 변환
        point = Point()
        point.x = (x - self.ppx) * z / self.fx
        point.y = (y - self.ppy) * z / self.fy
        point.z = z
        return point


def main(args=None):
    rclpy.init(args=args)
    node = GripperVisionNode()

    try:
        while rclpy.ok():
            rclpy.spin_once(node, timeout_sec=0.01)
            node.display_realsense_frame()
    finally:
        cv2.destroyAllWindows()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
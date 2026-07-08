import time
import numpy as np

import cv2
import rclpy
from rclpy.node import Node

from store_interfaces.srv import ScanCounterQr


class CounterQrNode(Node):
    """C270 카메라로 계산대 QR을 읽는 전용 노드입니다."""

    def __init__(self):
        super().__init__('counter_qr_node')

        self.qr_detector = cv2.QRCodeDetector()
        self.webcam_index = self.declare_parameter('webcam_index', 2).value
        self.webcam_device = self.declare_parameter(
            'webcam_device',
            '/dev/v4l/by-id/usb-046d_C270_HD_WEBCAM_200901010001-video-index2',
        ).value
        self.scan_timeout = self.declare_parameter('scan_timeout').value
        self.show_counter_camera = self.declare_parameter(
            'show_counter_camera',
            True,
        ).value

        self.create_service(
            ScanCounterQr,
            'scan_counter_qr',
            self.handle_scan_counter_qr,
        )

        self.get_logger().info('counter_qr_node start')

    def handle_scan_counter_qr(self, request, response):
        """main_manager가 요청하면 C270으로 QR을 한 번 스캔합니다."""
        if not request.start:
            response.success = False
            response.qr_data = ''
            return response

        qr_data = self.scan_webcam_qr()

        response.success = bool(qr_data)
        response.qr_data = qr_data or ''

        if response.success:
            self.get_logger().info(f'QR data: {response.qr_data}')
        else:
            self.get_logger().warn('QR scan failed')

        return response

    def scan_webcam_qr(self):
        """C270을 열고 QR을 찾습니다."""
        camera_source = self.webcam_index
        cap = cv2.VideoCapture(camera_source)

        if not cap.isOpened():
            self.get_logger().warn(f'C270 open failed: source={camera_source}')
            return None

        self.get_logger().info(f'C270 opened: source={camera_source}')

        if self.show_counter_camera:
            cv2.namedWindow('Counter C270 View', cv2.WINDOW_NORMAL)
            cv2.moveWindow('Counter C270 View', 700, 50)

        qr_data = None

        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

        try:
            while True:
                ok, frame = cap.read()
                if not ok:
                    self.get_logger().warn('C270 frame read failed')
                    time.sleep(0.05)
                    continue
                    
                if self.show_counter_camera:
                    cv2.imshow('Counter C270 View', frame)
                    cv2.waitKey(30)

                data, _, _ = self.qr_detector.detectAndDecode(frame)
                if data:
                    qr_data = data
                    break
        finally:
            if self.show_counter_camera:
                cv2.destroyWindow('Counter C270 View')
            cap.release()

        return qr_data

    def destroy_node(self):
        cv2.destroyAllWindows()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = CounterQrNode()

    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
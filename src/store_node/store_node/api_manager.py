import threading
from typing import List

import rclpy
from rclpy.node import Node

from fastapi import FastAPI, Body
from pydantic import BaseModel
import uvicorn
from store_interfaces.srv import OrderProduct

# 1. 외부 데이터 구조 정의 (Appsmith 수신용 단일 항목 및 장바구니 배열 전체 대응)
class RobotTaskRequest(BaseModel):
    product_id: int
    product_name: str
    quantity: int = 1

class OrderRequest(BaseModel):
    cart: List[RobotTaskRequest]


# 2. ROS 2 노드 클래스 정의
class StoreRobotApiNode(Node):
    def __init__(self):
        super().__init__("store_robot_api_node")
        # 상품 주문/작업 명령을 메인 매니저에게 보낼 토픽
        self.srv_ui = self.create_client(     # 주문 접수
            OrderProduct, 
            '/order_product'
        )

# 3. FastAPI 인스턴스 전역 생성 (Uvicorn 라우팅 매핑용)
app = FastAPI()

# 전역에서 껍데기 변수 선언 (main 내부에서 실물 매핑됨)
ros_node: StoreRobotApiNode = None
@app.post("/orders")
def create_robot_task_from_cart(body: dict = Body(...)):
    req = OrderProduct.Request()
    req.product_name = list(body.keys())     # ['과자', '물']
    req.quantity = list(body.values()) # [2, 1]

    ros_node.srv_ui.call_async(req)
    

def main(args=None):
    global ros_node

    rclpy.init(args=args)
    ros_node = StoreRobotApiNode()

    def spin_ros_node():
        try:
            rclpy.spin(ros_node)
        except Exception as e:
            ros_node.get_logger().error(f"ROS2 Spin Exception: {e}")

    ros_thread = threading.Thread(target=spin_ros_node, daemon=True)
    ros_thread.start()

    try:
        uvicorn.run(app, host="0.0.0.0", port=8000)
    finally:
        ros_node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
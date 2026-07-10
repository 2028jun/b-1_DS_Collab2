import json
import threading
from datetime import datetime

import rclpy
from rclpy.node import Node
from std_msgs.msg import Bool, String

from fastapi import FastAPI
from pydantic import BaseModel
import uvicorn  # 💡 ros2 run 실행을 위해 추가

class RobotTaskRequest(BaseModel):
    product_id: int
    product_name: str
    quantity: int = 1


class StoreRobotApiNode(Node):
    def __init__(self):
        super().__init__("store_robot_api_node")

        # 비상 정지 명령을 보낼 topic
        self.emergency_pub = self.create_publisher(
            Bool,
            "/emergency_stop",
            10
        )

        # 💡 버그 수정: 아래 publish_robot_command에서 사용 중인 publisher가 생성되어 있지 않아 추가했습니다.
        # 상품 주문/작업 명령을 로봇에게 보낼 topic
        self.command_pub = self.create_publisher(
            String,
            "/robot_command",  # 원하시는 토픽 이름으로 변경 가능합니다.
            10
        )

        self.robot_state = {
            "status": "idle",
            "last_command": None,
            "updated_at": None
        }

    def publish_emergency_stop(self):
        msg = Bool()
        msg.data = True
        self.emergency_pub.publish(msg)

        self.robot_state["status"] = "emergency_stopped"
        self.robot_state["last_command"] = "Emergency stop"
        self.robot_state["updated_at"] = datetime.now().isoformat()

        self.get_logger().warn("Emergency stop published to /emergency_stop")
        
    def publish_robot_command(self, task: RobotTaskRequest):
        command_data = {
            "command": "pick_product",
            "product_id": task.product_id,
            "product_name": task.product_name,
            "quantity": task.quantity
        }

        msg = String()
        # 한글 깨짐 방지를 위해 ensure_ascii=False 유지
        msg.data = json.dumps(command_data, ensure_ascii=False)

        self.command_pub.publish(msg)

        self.robot_state["status"] = "command_sent"
        self.robot_state["last_command"] = command_data
        self.robot_state["updated_at"] = datetime.now().isoformat()

        print("\n" + "="*50)
        print("🚨 [🚨 EMERGENCY STOP ALERT 🚨]")
        print(f"시간: {self.robot_state['updated_at']}")
        print("Appsmith로부터 비상정지 신호를 성공적으로 수신했습니다!")
        print("="*50 + "\n")

        self.get_logger().info(f"Robot command published: {msg.data}")

        return command_data


# FastAPI 앱 생성
app = FastAPI()

# ROS2 초기화
rclpy.init()
ros_node = StoreRobotApiNode()


def spin_ros_node():
    rclpy.spin(ros_node)


# ROS2 node를 별도 thread에서 계속 실행
ros_thread = threading.Thread(target=spin_ros_node, daemon=True)
ros_thread.start()


@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "message": "FastAPI + ROS2 bridge is running"
    }


@app.get("/robot/status")
def get_robot_status():
    return ros_node.robot_state


@app.post("/robot/emergency-stop")
def emergency_stop():
    ros_node.publish_emergency_stop()

    return {
        "success": True,
        "message": "Emergency stop command was sent to ROS2",
        "robot_state": ros_node.robot_state
    }


# 💡 [추가] Appsmith에서 상품 정보를 받아 로봇에게 명령을 내리는 POST API
@app.post("/robot/task")
def create_robot_task(task: RobotTaskRequest):
    """
    Appsmith에서 JSON Body로 상품 정보를 보내면 호출되는 API입니다.
    예시 Body: {"product_id": 101, "product_name": "물티슈", "quantity": 2}
    """
    command_result = ros_node.publish_robot_command(task)
    
    return {
        "success": True,
        "message": "Robot task command was sent successfully",
        "sent_command": command_result,
        "robot_state": ros_node.robot_state
    }


# 💡 [추가] ros2 run 명령어로 구동하기 위한 진입점 함수 (main)
def main(args=None):
    # 전역에 이미 선언된 rclpy 초기화 및 스레드 구동 로직이 파일 로드 시 실행되므로,
    # 여기서는 uvicorn 서버만 직접 구동해 줍니다.
    print("Starting Store Robot API Server via ros2 run...")
    uvicorn.run(app, host="0.0.0.0", port=8000)

    # 서버 종료 시 ROS2 깔끔하게 정리
    rclpy.shutdown()


if __name__ == '__main__':
    main()

import rclpy
from rclpy.node import Node
from store_interfaces.srv import OrderProduct

class MainManagerNode(Node):
    def __init__(self):
        super().__init__('main_manager_node')

        self.srv = self.create_service(     # 키오스크 화면으로부터 주문 접수
            OrderProduct, 
            '/order_product', 
            self.order_product_callback  
        )

        self.srv = self.create_service(     # 키오스크 화면으로부터 주문 접수
            OrderProduct, 
            '/voice_order', 
            self.order_product_callback 
        )

    def order_product_callback(self, request, response):

        order_dict = dict(zip(request.product_name, request.quantity)) # 주문 상품과 개수를 딕셔너리 형태로 묶기
        order_items = [f"{name}:{qty}개" for name, qty in order_dict.items()]   # 주문 접수 목록을 문자열로 변환(과자 : 1개)
        self.get_logger().info(f"주문 접수 : {', '.join(order_items)}")  # 주문 접수 목록 출력

        response.success = True

        return response

        

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
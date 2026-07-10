import pymysql
import pymysql.cursors
import rclpy
from rclpy.node import Node
from std_msgs.msg import String 
import json

from store_interfaces.srv import UpdateInventory 

class DatabaseNode(Node):
    def __init__(self):
        super().__init__('database_node')       # 로봇으로 부터 온 QR 데이터

        self.srv = self.create_service(
            UpdateInventory,
            '/update_stock',
            self.update_qr_data
        )

        self.qr_sub_db = self.create_subscription(String, '/counter_qr_data_db', self.qr_sub_db_callback, 10)     # 사람으로 부터 온 QR 데이터

        self.auth_sub = self.create_subscription(String, '/store_state', self.auth_sub_callback, 10)

        self.last_qr_data = None
        self.qr_data = None
        self.auth_status = "SERVICE"
        self.last_processed_mode = None

        try:
            self.conn = pymysql.connect(
                host='localhost',
                user='root',           
                password='1234',        
                database='convenience_store_db',
                charset='utf8mb4',
                cursorclass=pymysql.cursors.DictCursor
            )
            self.get_logger().info("✅ MySQL 데이터베이스와 성공적으로 연결되었습니다.")

        except Exception as e:
            self.get_logger().error(f"❌ 데이터베이스 연결 실패! 에러 내용: {e}")
            raise e # 연결 실패 시 노드 실행 강제 중단
    
    def auth_sub_callback(self, msg):
        parts = msg.data.split(',')
        self.auth_status = parts[0].strip()
    
    def qr_sub_db_callback(self, msg):
        self.qr_data = msg.data
        if (self.last_qr_data != self.qr_data) or (self.last_processed_mode != self.auth_status):
            success = self.handle_update_stock()
            if success is True:
                self.last_qr_data = self.qr_data
                self.last_processed_mode = self.auth_status

    def update_qr_data(self, request, response):
        self.qr_data = request.qr_data

        if not self.qr_data:
            self.get_logger().warn("⚠️ 수신된 시리얼 넘버가 비어있습니다.")
            response.success = False
            return response

        if (self.last_qr_data != self.qr_data) or (self.last_processed_mode != self.auth_status):
            success = self.handle_update_stock()
            if success is True:
                self.last_qr_data = self.qr_data
                self.last_processed_mode = self.auth_status
                response.success = success
            else:
                response.success = False
        else:
            response.success = True

        return response
    
    def handle_update_stock(self):
        success = False
        parsed_data = self.data_parsing(self.qr_data)

        if parsed_data is None:
            self.get_logger().error("❌ 데이터 파싱 실패로 인해 DB 처리를 중단합니다.")
            return False

        product_name, serial_number, clean_price, expiry_date = parsed_data

        if self.auth_status == "ADMIN":
            # 물품 입고 기록
            sql = """
                INSERT INTO products (name, SN, price, expiry_date)
                VALUES (%s, %s, %s, %s) 
                ON DUPLICATE KEY UPDATE
                    name = VALUES(name),
                    price = VALUES(price),
                    expiry_date = VALUES(expiry_date);
            """
            try:
                with self.conn.cursor() as cursor:
                    cursor.execute(sql, (product_name, serial_number, clean_price, expiry_date))
                    
                    self.conn.commit()
                    
                    self.get_logger().info(f"데이터베이스 등록 완료!")
                    success = True
                    
            except Exception as e:
                self.conn.rollback()
                self.get_logger().error(f"❌ 관리자 상품 등록 중 SQL 에러 발생: {e}")
                success = False
        
        elif self.auth_status == "SERVICE":
            # 물품 판매 -> 재고 삭제
            sql_delete_stock = """                  
               DELETE FROM products 
                WHERE SN = %s;
            """
            
            # 물품 출고 기록
            sql_insert_outbound_history= """
                INSERT INTO outbound_history (name, SN)
                VALUES (%s, %s);
            """

            try:
                with self.conn.cursor() as cursor:
                    
                    # 출고 이력에 시리얼 넘버 추가
                    cursor.execute(sql_insert_outbound_history, (product_name, serial_number,))
                    
                    # Step B: 기존 재고 테이블(products)에서 삭제 진행 (인자 1개)
                    affected_rows = cursor.execute(sql_delete_stock, (serial_number,))
                    
                    if affected_rows > 0:
                        self.conn.commit()
                        self.get_logger().info(f"출고 이력 등록 및 재고 삭제 완료")
                        success = True
                    else:
                        self.conn.rollback()
                        self.get_logger().warn(f"⚠️ 출고 실패: 매대 재고(products)에 존재하지 않는 SN입니다: {serial_number}")
                        success = False
                        
            except Exception as e:
                self.conn.rollback()
                self.get_logger().error(f"❌ 서비스 모드 출고 처리 중 SQL 에러 발생: {e}")
                success = False

        return success

    def data_parsing(self, data):
        try:
            data_dict = json.loads(data)
     
            product_name = data_dict.get("name")
            serial_number = data_dict.get("SN")
            
            raw_price = data_dict.get("price", "0")
            clean_price = int(raw_price.replace(",", "").replace("원", "").strip())
            
            expiry_date = data_dict.get("expiry_date")

            return product_name, serial_number, clean_price, expiry_date

        except Exception as e:
            self.get_logger().error(f"QR 데이터 파싱 실패 (올바르지 않은 형식): {e}")
            return None

    def destroy_node(self):
        self.get_logger().info("🔌 데이터베이스 노드 종료 및 자원 해제")
        if hasattr(self, 'conn') and self.conn.open:
            self.conn.close()
            self.get_logger().info("MySQL Connection Closed.")
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    try:
        node = DatabaseNode()
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        # spin이 끊기거나 정상 종료 시 destroy_node 호출을 보장
        if 'node' in locals():
            node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
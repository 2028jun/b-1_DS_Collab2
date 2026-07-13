import json
import os
from datetime import datetime, timedelta

import pymysql
import pymysql.cursors
import rclpy
from rclpy.node import Node

from store_interfaces.srv import GetSalesAnalytics

try:
    from openai import OpenAI
    OPENAI_IMPORT_ERROR = None
except ImportError as exc:
    OpenAI = None
    OPENAI_IMPORT_ERROR = exc


class DbAiAnalyticsManager(Node):
    """DB를 읽어 판매 통계를 만들고, 선택적으로 AI 요약을 생성합니다."""

    def __init__(self):
        super().__init__('db_ai_analytics_manager')

        self.db_host = self.declare_parameter('db_host', 'localhost').value
        self.db_port = self.declare_parameter('db_port', 3306).value
        self.db_user = self.declare_parameter('db_user', 'root').value
        self.db_password = self.declare_parameter('db_password', '1234').value
        self.db_name = self.declare_parameter('db_name', 'convenience_store_db').value
        self.ai_model = self.declare_parameter('ai_model', 'gpt-4o-mini').value

        self.openai_client = self.create_openai_client()

        self.create_service(
            GetSalesAnalytics,
            '/analyze_sales',
            self.handle_analyze_sales,
        )

        self.get_logger().info('db_ai_analytics_manager start')

    def create_openai_client(self):
        if OpenAI is None:
            return None
        api_key = os.getenv('OPENAI_API_KEY')
        return OpenAI(api_key=api_key) if api_key else None

    def handle_analyze_sales(self, request, response):
        period = (request.period or 'today').strip().lower()
        try:
            report = self.build_sales_report(period)
            response.report_json = ''
            response.summary = self.summarize_report(report, request.use_ai)
            response.success = True
        except Exception as exc:
            self.get_logger().error(f'Sales analysis failed: {exc}')
            response.success = False
            response.error_message = str(exc)
        return response

    def get_connection(self):
        return pymysql.connect(
            host=self.db_host,
            port=int(self.db_port),
            user=self.db_user,
            password=self.db_password,
            database=self.db_name,
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor,
        )

    def build_sales_report(self, period):
        start_at = self.get_period_start(period)
        where_sql = ""
        params = []
        if start_at:
            where_sql = "WHERE o.outbound_date >= %s"
            params.append(start_at.strftime('%Y-%m-%d'))

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                # 1. 총 매출 및 판매량 통계
                cursor.execute(
                    f"""
                    SELECT COUNT(*) AS total_orders, COUNT(*) AS total_units, SUM(p.price) AS total_revenue
                    FROM outbound_history o
                    JOIN products p ON p.SN = o.SN
                    {where_sql}
                    """, params
                )
                totals = cursor.fetchone() or {'total_orders': 0, 'total_units': 0, 'total_revenue': 0}

                # 2. 상품별 판매 통계
                cursor.execute(
                    f"""
                    SELECT p.name, p.price, COUNT(o.SN) AS units_sold, SUM(p.price) AS revenue
                    FROM products p
                    LEFT JOIN outbound_history o ON o.SN = p.SN
                    {where_sql.replace('WHERE', 'AND')}
                    GROUP BY p.SN
                    ORDER BY units_sold DESC
                    """, params
                )
                product_rows = cursor.fetchall()

        return {
            'period': period,
            'totals': {
                'total_orders': int(totals['total_orders'] or 0),
                'total_units': int(totals['total_units'] or 0),
                'total_revenue': int(totals['total_revenue'] or 0),
            },
            'top_products': [
                {'name': r['name'], 'units_sold': int(r['units_sold'] or 0), 'revenue': int(r['revenue'] or 0)}
                for r in product_rows
            ]
        }

    def get_period_start(self, period):
        now = datetime.now()
        if period == 'today': return now.replace(hour=0, minute=0, second=0, microsecond=0)
        if period == 'week': return now - timedelta(days=7)
        if period == 'month': return now - timedelta(days=30)
        return None

    def summarize_report(self, report, use_ai):
        if use_ai and self.openai_client:
            return self.generate_ai_summary(report)
        return self.generate_local_summary(report)

    def generate_ai_summary(self, report):
        try:
            prompt = f"편의점 판매 요약: {json.dumps(report, ensure_ascii=False)}"
            completion = self.openai_client.chat.completions.create(
                model=self.ai_model,
                messages=[{'role': 'user', 'content': prompt}]
            )
            return completion.choices[0].message.content.strip()
        except:
            return self.generate_local_summary(report)

    def generate_local_summary(self, report):
        t = report['totals']
        lines = [f"{report['period']} 기준 판매 {t['total_units']}개, 매출 {t['total_revenue']:,}원입니다."]
        if report['top_products']:
            top = report['top_products'][0]
            lines.append(f"가장 많이 팔린 상품은 {top['name']} ({top['units_sold']}개)입니다.")
        return ' '.join(lines)

def main(args=None):
    rclpy.init(args=args)
    node = DbAiAnalyticsManager()
    try: rclpy.spin(node)
    except KeyboardInterrupt: pass
    finally: node.destroy_node(); rclpy.shutdown()

if __name__ == '__main__':
    main()
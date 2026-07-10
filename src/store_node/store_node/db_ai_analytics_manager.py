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
        self.db_name = self.declare_parameter(
            'db_name',
            'convenience_store_db',
        ).value
        self.ai_model = self.declare_parameter('ai_model', 'gpt-4o-mini').value
        self.completed_statuses_text = self.declare_parameter(
            'completed_statuses',
            '',
        ).value

        self.completed_statuses = [
            status.strip()
            for status in self.completed_statuses_text.split(',')
            if status.strip()
        ]

        self.openai_client = self.create_openai_client()

        self.create_service(
            GetSalesAnalytics,
            '/analyze_sales',
            self.handle_analyze_sales,
        )

        self.get_logger().info('db_ai_analytics_manager start')

    def create_openai_client(self):
        if OpenAI is None:
            self.get_logger().warn(
                f'OpenAI package is not available: {OPENAI_IMPORT_ERROR}. '
                'AI summary will use local fallback.'
            )
            return None

        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            self.get_logger().warn(
                'OPENAI_API_KEY is not set. AI summary will use local fallback.'
            )
            return None

        return OpenAI(api_key=api_key)

    def handle_analyze_sales(self, request, response):
        period = (request.period or 'today').strip().lower()

        try:
            report = self.build_sales_report(period)
            
            # --- 수정된 부분 시작 ---
            # 불필요한 전체 데이터를 제외하고 요약 정보만 전달하도록 수정
            response.report_json = ''  # 빈 문자열로 설정하거나 필요 시 제거
            response.summary = self.summarize_report(report, request.use_ai)
            # --- 수정된 부분 끝 ---
            
            response.success = True
            response.error_message = ''
        except Exception as exc:
            self.get_logger().error(f'Sales analysis failed: {exc}')
            response.success = False
            response.report_json = '{}'
            response.summary = ''
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
        where_sql, params = self.build_order_filters(start_at)

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT
                        COUNT(*) AS total_orders,
                        COALESCE(SUM(o.quantity), 0) AS total_units,
                        COALESCE(SUM(o.quantity * p.price), 0) AS total_revenue
                    FROM orders o
                    JOIN products p ON p.id = o.product_id
                    {where_sql}
                    """,
                    params,
                )
                totals = cursor.fetchone()

                cursor.execute(
                    f"""
                    SELECT
                        p.id AS product_id,
                        p.name,
                        p.price,
                        p.stock_quantity,
                        p.min_stock_quantity,
                        COALESCE(SUM(o.quantity), 0) AS units_sold,
                        COALESCE(SUM(o.quantity * p.price), 0) AS revenue
                    FROM products p
                    LEFT JOIN orders o ON o.product_id = p.id
                    {self.build_left_join_filter(start_at)}
                    GROUP BY
                        p.id,
                        p.name,
                        p.price,
                        p.stock_quantity,
                        p.min_stock_quantity
                    ORDER BY units_sold DESC, revenue DESC, p.name ASC
                    """,
                    params,
                )
                product_rows = cursor.fetchall()

                cursor.execute(
                    """
                    SELECT
                        id,
                        name,
                        stock_quantity,
                        min_stock_quantity
                    FROM products
                    WHERE stock_quantity <= min_stock_quantity
                    ORDER BY stock_quantity ASC, name ASC
                    """
                )
                low_stock_rows = cursor.fetchall()

        return {
            'period': period,
            'start_at': start_at.isoformat() if start_at else None,
            'generated_at': datetime.now().isoformat(timespec='seconds'),
            'totals': {
                'total_orders': int(totals['total_orders'] or 0),
                'total_units': int(totals['total_units'] or 0),
                'total_revenue': int(totals['total_revenue'] or 0),
            },
            'top_products': [
                {
                    'product_id': int(row['product_id']),
                    'name': row['name'],
                    'price': int(row['price']),
                    'stock_quantity': int(row['stock_quantity']),
                    'min_stock_quantity': int(row['min_stock_quantity']),
                    'units_sold': int(row['units_sold'] or 0),
                    'revenue': int(row['revenue'] or 0),
                }
                for row in product_rows
            ],
            'low_stock_products': [
                {
                    'product_id': int(row['id']),
                    'name': row['name'],
                    'stock_quantity': int(row['stock_quantity']),
                    'min_stock_quantity': int(row['min_stock_quantity']),
                }
                for row in low_stock_rows
            ],
        }

    def get_period_start(self, period):
        now = datetime.now()
        if period == 'today':
            return now.replace(hour=0, minute=0, second=0, microsecond=0)
        if period == 'week':
            return now - timedelta(days=7)
        if period == 'month':
            return now - timedelta(days=30)
        if period == 'all':
            return None

        raise ValueError('period must be one of: today, week, month, all')

    def build_order_filters(self, start_at):
        filters = []
        params = []

        if start_at is not None:
            filters.append('o.created_at >= %s')
            params.append(start_at)

        if self.completed_statuses:
            placeholders = ', '.join(['%s'] * len(self.completed_statuses))
            filters.append(f'o.status IN ({placeholders})')
            params.extend(self.completed_statuses)

        if not filters:
            return '', params

        return 'WHERE ' + ' AND '.join(filters), params

    def build_left_join_filter(self, start_at):
        join_filters = []

        if start_at is not None:
            join_filters.append('o.created_at >= %s')

        if self.completed_statuses:
            placeholders = ', '.join(['%s'] * len(self.completed_statuses))
            join_filters.append(f'o.status IN ({placeholders})')

        if not join_filters:
            return ''

        return 'AND ' + ' AND '.join(join_filters)

    def summarize_report(self, report, use_ai):
        if use_ai and self.openai_client is not None:
            ai_summary = self.generate_ai_summary(report)
            if ai_summary:
                return ai_summary

        return self.generate_local_summary(report)

    def generate_ai_summary(self, report):
        prompt = (
            '너는 편의점 관리자용 판매 분석 도우미야. '
            '아래 JSON 통계를 바탕으로 한국어로 짧고 실무적으로 요약해줘. '
            '전체 판매량, 매출, 잘 팔린 상품, 재고 보충 필요 상품을 포함해줘.\n\n'
            f'{json.dumps(report, ensure_ascii=False)}'
        )

        try:
            completion = self.openai_client.chat.completions.create(
                model=self.ai_model,
                messages=[
                    {
                        'role': 'system',
                        'content': '편의점 재고/판매 데이터를 간결하게 분석한다.',
                    },
                    {'role': 'user', 'content': prompt},
                ],
                temperature=0.2,
            )
            return completion.choices[0].message.content.strip()
        except Exception as exc:
            self.get_logger().warn(f'AI summary failed, using fallback: {exc}')
            return ''

    def generate_local_summary(self, report):
        totals = report['totals']
        products = [
            item for item in report['top_products']
            if item['units_sold'] > 0
        ]
        low_stock = report['low_stock_products']

        lines = [
            f"{report['period']} 기준 주문 {totals['total_orders']}건, "
            f"판매 수량 {totals['total_units']}개, "
            f"매출 {totals['total_revenue']:,}원입니다."
        ]

        if products:
            top = products[0]
            lines.append(
                f"가장 많이 판매된 상품은 {top['name']} "
                f"{top['units_sold']}개({top['revenue']:,}원)입니다."
            )
        else:
            lines.append('해당 기간 판매 기록이 없습니다.')

        if low_stock:
            names = ', '.join(
                f"{item['name']}({item['stock_quantity']}개)"
                for item in low_stock[:5]
            )
            lines.append(f"재고 보충이 필요한 상품은 {names}입니다.")
        else:
            lines.append('현재 최소 재고 이하 상품은 없습니다.')

        return ' '.join(lines)


def main(args=None):
    rclpy.init(args=args)
    node = DbAiAnalyticsManager()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()

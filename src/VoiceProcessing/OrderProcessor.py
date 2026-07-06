from Order_Extractor import OrderExtractor


class OrderProcessor:
    def __init__(self):
        self.extractor = OrderExtractor()

    def run(self, text: str) -> dict:
        order = self.extractor.extract_order(text)

        if not order:
            print("❌ 주문 물품을 찾지 못했습니다.")
            return {}

        print(f"✅ 주문 처리 결과: {order}")
        return order

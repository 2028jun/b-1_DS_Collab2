from voice_processing.Order_Extractor import OrderExtractor


class OrderProcessor:
    def __init__(self):
        self.extractor = OrderExtractor()

    def run(self, text: str) -> dict:
        order = self.extractor.extract_order(text)      # 물품 목록을 사용자의 음성으로부터 추출

        if not order:       # 음성이 녹음되지 않았을 때
            print("❌ 주문 물품을 찾지 못했습니다.")
            return {}

        print(f"✅ 주문 처리 결과: {order}")
        return order        # 주문 물품 목록을 return

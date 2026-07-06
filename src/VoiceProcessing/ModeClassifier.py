from difflib import SequenceMatcher


class ModeClassifier:
    def __init__(self):
        self.admin_phrases = [
            "관리자 모드",
            "관리자 메뉴",
            "관리자 화면",
            "관리자 로그인",
            "관리 모드",
            "어드민 모드",
            "점장 모드",
            "사장님 모드",
            "재고 관리",
            "매출 확인",
            "시스템 관리",
        ]

        self.threshold = 0.65

    def _normalize(self, text: str) -> str:
        return text.lower().replace(" ", "")

    def _similarity(self, a: str, b: str) -> float:
        return SequenceMatcher(None, a, b).ratio()

    def classify(self, text: str) -> str:
        normalized_text = self._normalize(text)

        for phrase in self.admin_phrases:
            normalized_phrase = self._normalize(phrase)

            if normalized_phrase in normalized_text:
                print("✅ 모드 분류 결과: ADMIN")
                return "ADMIN"

            score = self._similarity(normalized_text, normalized_phrase)
            if score >= self.threshold:
                print(f"✅ 모드 분류 결과: ADMIN / score={score:.2f}")
                return "ADMIN"

        print("✅ 모드 분류 결과: ORDER")
        return "ORDER"


if __name__ == "__main__":
    classifier = ModeClassifier()

    test_inputs = [
        "물 두 개 주세요",
        "주문 시작",
        "관리자 모드로 들어가",
        "관리자 모두로 들어가",
        "관리자 메뉴 열어줘",
        "재고 확인하고 싶어",
        "점장 모드 실행",
    ]

    for text in test_inputs:
        print(text, "->", classifier.classify(text))
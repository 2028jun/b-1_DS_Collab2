class AdminAuthenticator:
    def __init__(self):
        self.voice_ok = False
        self.barcode_ok = False
        self.barcode_enabled = False

        self.admin_voice_keywords = [
            "홍명보 아웃",
            "홍명보 퇴장",
            "홍명보 사퇴",
            "홍명보 물러가",
            "홍명보 물러나라",
            "관리자 모드 입장",
            "관리자 입장",
            "관리자 모드",
            "관리자 모드 진입",
            "관리자 모드로 진입",
            "관리자 모드로 입장",
            "관리자 모드로 들어가",
            "관리자 모드로 들어가라",
        ]

        self.admin_barcode = "ADMIN-2401"

    def _normalize(self, text: str) -> str:
        return text.replace(" ", "")

    def reset(self):
        self.voice_ok = False
        self.barcode_ok = False

    def check_voice(self, text: str) -> bool:
        normalized_text = self._normalize(text)

        for keyword in self.admin_voice_keywords:
            normalized_keyword = self._normalize(keyword)

            if normalized_keyword in normalized_text:
                self.voice_ok = True
                print("✅ 관리자 음성 인증 성공")
                return True

        print("❌ 관리자 음성 인증 실패")
        return False

    def check_barcode(self, barcode: str) -> bool:
        if barcode == self.admin_barcode:
            self.barcode_ok = True
            print("✅ 관리자 바코드 인증 성공")
            return True

        print("❌ 관리자 바코드 인증 실패")
        return False

    def is_authenticated(self) -> bool:
        if self.barcode_enabled:
            return self.voice_ok and self.barcode_ok

        return self.voice_ok
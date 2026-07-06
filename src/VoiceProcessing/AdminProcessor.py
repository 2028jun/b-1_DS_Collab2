from AdminAuthenticator import AdminAuthenticator


class AdminProcessor:
    def __init__(self, stt):
        self.stt = stt
        self.authenticator = AdminAuthenticator()

    def run(self) -> bool:
        print("관리자 모드 요청 감지")
        print("관리자 인증어를 말씀해주세요.")

        auth_text = self.stt.speech2text()
        print(f"관리자 인증 STT 결과: {auth_text}")

        self.authenticator.check_voice(auth_text)

        if self.authenticator.is_authenticated():
            print("✅ 관리자 모드로 진입합니다.")
            return True

        print("❌ 관리자 인증 실패. 사용자 모드로 돌아갑니다.")
        return False

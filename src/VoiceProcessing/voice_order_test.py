from MicController import MicController
from wakeup_word import WakeupWord
from STT import STT
from ModeClassifier import ModeClassifier
from OrderProcessor import OrderProcessor
from AdminProcessor import AdminProcessor
from dotenv import load_dotenv
import os


load_dotenv(dotenv_path=".env")
openai_api_key = os.getenv("OPENAI_API_KEY")


def main():
    if openai_api_key is None:
        raise ValueError("OPENAI_API_KEY가 .env에서 로드되지 않았습니다.")

    mic = MicController()
    mic.open_stream()

    wakeup = WakeupWord(mic.config.buffer_size)
    wakeup.set_stream(mic.stream)

    print("호출어 대기 중...")

    while not wakeup.is_wakeup():
        pass

    mic.close_stream()

    print("호출어 감지됨. 음성 명령을 녹음합니다.")

    stt = STT(openai_api_key)
    command_text = stt.speech2text()

    print(f"STT 결과: {command_text}")

    mode_classifier = ModeClassifier()
    order_processor = OrderProcessor()
    admin_processor = AdminProcessor(stt)

    mode = mode_classifier.classify(command_text)

    if mode == "ADMIN":
        admin_success = admin_processor.run()

        if admin_success:
            print("관리자 기능 실행 준비 완료")
        return

    order = order_processor.run(command_text)
    print(f"최종 주문 결과: {order}")


if __name__ == "__main__":
    main()
#AdminProcessor.py
import os
import json
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain.prompts import PromptTemplate


load_dotenv(dotenv_path=".env")
openai_api_key = os.getenv("OPENAI_API_KEY")


class AdminProcessor:
    def __init__(self, stt):
        self.stt = stt

        self.llm = ChatOpenAI(
            model="gpt-4o",
            temperature=0,
            openai_api_key=openai_api_key,
        )

        prompt = """
당신은 편의점 로봇 시스템의 관리자 음성 인증 판별기입니다.

목표:
- 사용자의 음성 인식 결과가 관리자 인증 의도인지 판단하세요.

인증 성공으로 판단할 수 있는 경우:
- 관리자 인증
- 관리자 모드 입장
- 관리자 모드 진입
- 운영자 인증
- 운영자 로그인
- 관리자 로그인
- 관리자 권한 실행
- 관리자 비밀번호 입력
- 관리자 암호 입력
- 발음이나 STT 오인식이 약간 있어도 관리자/운영자 인증 의도로 해석 가능하면 true

인증 실패로 판단해야 하는 경우:
- 일반 주문
- 상품 요청
- 단순 인사
- 계산 요청
- 관리자 호출 요청
- 관리자 위치 질문
- 의미가 불명확한 문장

반드시 JSON만 출력하세요.
형식:
{{"auth": true}}
또는
{{"auth": false}}

사용자 입력:
"{user_input}"
"""

        self.prompt_template = PromptTemplate(
            input_variables=["user_input"],
            template=prompt,
        )

        self.chain = self.prompt_template | self.llm

    def check_voice_auth(self, text: str) -> bool:
        try:
            response = self.chain.invoke({"user_input": text})

            content = response.content.strip()
            content = content.replace("```json", "").replace("```", "").strip()

            print(f"관리자 인증 LLM 응답: {content}")

            data = json.loads(content)

            return bool(data.get("auth", False))

        except Exception as e:
            print(f"❌ 관리자 인증 판별 실패: {e}")
            return False

    def run(self):
        print("\n관리자 모드 진입 요청 감지")
        print("관리자 인증 문장을 말씀해주세요.")

        auth_text = self.stt.speech2text().strip()
        print(f"관리자 인증 STT 결과: {auth_text}")

        if self.check_voice_auth(auth_text):
            print("✅ 관리자 음성 인증 성공")
            return True

        print("❌ 관리자 음성 인증 실패")
        return False
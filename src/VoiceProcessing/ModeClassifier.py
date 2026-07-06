#ModeClassifier.py
import os
import json
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain.prompts import PromptTemplate
import re

load_dotenv(dotenv_path=".env")
openai_api_key = os.getenv("OPENAI_API_KEY")


class ModeClassifier:
    def __init__(self):

        self.llm = ChatOpenAI(
            model="gpt-4o",
            temperature=0,
            openai_api_key=openai_api_key,
        )

        prompt_content = """
당신은 편의점 음성 주문 시스템의 모드 분류기입니다.

<목표>
사용자의 음성을 아래 둘 중 하나로 분류하세요.

ADMIN
- 관리자 모드 진입
- 운영자 모드 진입
- 관리자 로그인
- 관리자 인증
- 운영자 로그인
- 관리자 설정
- 관리자 권한
- STT 오인식이 있어도 관리자 의도라면 ADMIN으로 판단하세요.
- '걸리죠 모두'와 같은 발음 오인식도 관리자 의도로 판단 가능하면 ADMIN으로 분류하세요.
- '관리자'라는 단어가 포함되어 있으면 ADMIN으로 분류하세요.
- '멀리서 모드'와 같은 발음 오인식도 관리자 의도로 판단 가능하면 ADMIN으로 분류하세요.

ORDER
- 상품 주문
- 계산
- 결제
- 일반 손님 요청
- 기타 모든 일반 명령

<출력 형식>

반드시 JSON만 출력하세요.

{{"mode":"ADMIN"}}

또는

{{"mode":"ORDER"}}

<사용자 입력>

"{user_input}"
"""

        self.prompt_template = PromptTemplate(
            input_variables=["user_input"],
            template=prompt_content,
        )

        self.lang_chain = self.prompt_template | self.llm



    def classify(self, text):

        try:
            response = self.lang_chain.invoke(
                {"user_input": text}
            )

            content = response.content.strip()
            content = content.replace("```json", "").replace("```", "").strip()

            print(f"LLM 응답: {content}")

            result = json.loads(content)

            mode = result.get("mode", "ORDER")

            if mode not in ["ADMIN", "ORDER"]:
                mode = "ORDER"

            print("\n[Mode Classification]")
            print(f"입력 문장 : {text}")
            print(f"분류 결과 : {mode}")

            return mode

        except Exception as e:

            print(f"❌ 모드 분류 실패 : {e}")

            return "ORDER"
        

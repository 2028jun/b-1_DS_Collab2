#ModeClassifier.py
import os
import json
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain.prompts import PromptTemplate

load_dotenv(dotenv_path=".env")     # .env 파일을 환경 변수로 등록
openai_api_key = os.getenv("OPENAI_API_KEY")        # .env 파일의 API 키를 변수에 등록


class ModeClassifier:
    def __init__(self):

        self.llm = ChatOpenAI(      # gpt-4o 모델 불러오기
            model="gpt-4o",
            temperature=0,
            openai_api_key=openai_api_key,
        )

        prompt_content = """
당신은 편의점 음성 주문 시스템의 모드 분류기입니다.

<목표>
사용자의 음성을 아래 셋 중 하나로 분류하세요.

WAREHOUSING
- 입고 모드
- 입고 시작
- 입고 해줘
- 물품 넣어줘
- STT 오인식이 있어도 입고 의도로 판단되면 WAREHOUSING로 분류하세요.
- '입고'라는 단어가 포함되어 있으면 WAREHOUSING로 분류하세요.
- 비슷한 발음 오인식도 서비스/사용자 의도로 판단 가능하면 WAREHOUSING로 분류하세요

SERVICE
- 관리자 모드 해제
- 사용자 모드
- 사용자 모드 진입
- 서비스 모드
- 서비스 모드 진입
- 서비스 재개
- 사용자 모드 재개
- STT 오인식이 있어도 서비스/사용자 의도로 판단되면 SERVICE로 분류하세요.
- '서비스', '사용자'라는 단어가 포함되어 있으면 SERVICE로 분류하세요.
- 비슷한 발음 오인식도 서비스/사용자 의도로 판단 가능하면 SERVICE로 분류하세요

ORDER
- 상품 주문
- 계산
- 결제
- 일반 손님 요청
- 기타 모든 일반 명령

DISPOSE
- 폐기 모드
- 폐기 해줘
- 폐기 시작
- 폐기 고고
- 폐기 하자
- '폐기'라는 단어가 포함되어 있으면 DISPOSE로 분류하세요
- 비슷한 발음 오인식도 폐기 의도로 판단 가능하면 DISPOSE로 분류하세요

<출력 형식>

반드시 JSON만 출력하세요.

{{"mode":"WAREHOUSING"}}

또는

{{"mode":"SERVICE"}}

또는

{{"mode":"ORDER"}}

또는 

{{"mode":"DISPOSE"}}

<사용자 입력>

"{user_input}"
"""
# gpt-4o에 입고/서비스/주문 모드를 인식하도록 프롬프트 작성 

        self.prompt_template = PromptTemplate(      # 프롬프트 문장
            input_variables=["user_input"],
            template=prompt_content,
        )

        self.lang_chain = self.prompt_template | self.llm   # 프롬프트 문장을 gpt-4o에 연결한 변수 (랭체인 라이브러리에서는 | : 연결파이프로 작동)

    def classify(self, text):

        try:
            response = self.lang_chain.invoke({"user_input": text})     # 랭체인 구동 -> 사용자의 음성 단어와 프롬프트가 결합되어 gpt-4o에 전달, 응답을 받아옴

            content = response.content.strip()
            content = content.replace("```json", "").replace("```", "").strip()

            print(f"LLM 응답: {content}")

            result = json.loads(content)        # json을 딕셔너리 형식으로 변환

            mode = result.get("mode", "ORDER")  # 딕셔너리에서 mode의 value값(입고/서비스/주문)을 받아옴, 기본값은 주문 모드

            if mode not in ["WAREHOUSING", "ORDER", "SERVICE", "DISPOSE"]: # mode에 해당되는 단어가 없으면 ORDER 모드로 판단
                mode = "ORDER"

            print("\n[Mode Classification]")
            print(f"입력 문장 : {text}")
            print(f"분류 결과 : {mode}")

            return mode     # 모드 return

        except Exception as e:

            print(f"❌ 모드 분류 실패 : {e}")

            return "ORDER"
        

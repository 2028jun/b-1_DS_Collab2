import os
import json
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain.prompts import PromptTemplate

load_dotenv(dotenv_path=".env")     # .env 파일을 환경 변수로 등록
openai_api_key = os.getenv("OPENAI_API_KEY")    # .env 파일의 API 키를 변수에 등록

class WakeupWord:
    def __init__(self):
        self.llm = ChatOpenAI(
            model="gpt-4o",     # gpt-4o 모델 불러오기
            temperature=0,      # 모델의 창의성(확률적 다양성) 제한
            openai_api_key=openai_api_key,
        )

        prompt = """        
당신은 편의점 로봇 시스템의 호출어 판별기입니다.

목표:
- 사용자의 STT 결과가 로봇 호출어인지 판단하세요.
- 호출어의 기준 단어는 "편돌아"입니다.
- 발음이나 STT 오인식이 있어도 "편돌아"를 부른 의도라면 true로 판단하세요.

호출어로 인정:
- 편돌아
- 편돌이
- 편도라
- 편돌라
- 팬돌아
- 펜돌아
- 편도리
- 편돌돌
- 편돌아야
- 편돌이야
- 편의점 로봇을 부르는 말로 해석 가능한 문장

호출어로 인정하지 않음:
- 일반 주문
- 상품 요청
- 계산 요청
- 단순 인사
- 의미가 불명확한 문장
- "편의점", "편하게", "편도"처럼 호출 의도가 아닌 단어

반드시 JSON만 출력하세요.

형식:
{{"wakeup": true}}
또는
{{"wakeup": false}}

사용자 입력:
"{user_input}"
"""
# gpt-4o에 '편돌이'라는 호출어 이름을 인식하도록 프롬프트 작성

        self.prompt_template = PromptTemplate(  # 프롬프트 문장
            input_variables=["user_input"],     # 사용자의 음성('편돌아) 단어가 들어가는 변수
            template=prompt,
        )

        self.lang_chain = self.prompt_template | self.llm    # 프롬프트 문장을 gpt-4o에 연결한 변수 (랭체인 라이브러리에서는 | : 연결파이프로 작동)

    def is_wakeup(self, text: str) -> bool:
        try:
            response = self.lang_chain.invoke({"user_input": text})      # 랭체인 구동 -> 사용자의 음성 단어와 프롬프트가 결합되어 gpt-4o에 전달, 응답을 받아옴

            content = response.content.strip()      # 응답의 공백 제거
            content = content.replace("```json", "").replace("```", "").strip()     # json, ''' 단어를 지우고 공백 제거

            print(f"호출어 판별 LLM 응답: {content}")       # 처리된 json 문자열 (true / false)

            data = json.loads(content)      # json을 딕셔너리 형식으로 변환
            return bool(data.get("wakeup", False))  # 딕셔너리에서 키의 값을 꺼내고 bool 형식으로 변환하여 return, 없으면 False

        except Exception as e:
            print(f"❌ 호출어 판별 실패: {e}")
            return False
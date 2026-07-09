import os
import json
from langchain_openai import ChatOpenAI
from langchain.prompts import PromptTemplate

from voice_processing.env_utils import load_openai_api_key


class WakeupWord:
    def __init__(self):
        openai_api_key = load_openai_api_key()
        self.llm = ChatOpenAI(
            model="gpt-4o",
            temperature=0,
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

        self.prompt_template = PromptTemplate(
            input_variables=["user_input"],
            template=prompt,
        )

        self.chain = self.prompt_template | self.llm

    def is_wakeup(self, text: str) -> bool:
        try:
            response = self.chain.invoke({"user_input": text})

            content = response.content.strip()
            content = content.replace("```json", "").replace("```", "").strip()

            print(f"호출어 판별 LLM 응답: {content}")

            data = json.loads(content)
            return bool(data.get("wakeup", False))

        except Exception as e:
            print(f"❌ 호출어 판별 실패: {e}")
            return False

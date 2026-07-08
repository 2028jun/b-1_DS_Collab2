#Order_Extractor.py
import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain.prompts import PromptTemplate
import json


load_dotenv(dotenv_path=".env")
openai_api_key = os.getenv("OPENAI_API_KEY")


class OrderExtractor:
    def __init__(self):
        self.llm = ChatOpenAI(
            model="gpt-4o", temperature=0, openai_api_key=openai_api_key
        )

        self.translation_map = {
            "담배": "smoke",
            "컵라면": "cup_noodle",
            "커피": "coffee",
            "음료": "drink",       # 예: 앞서 비전 노드에서 'water'를 썼던 것을 고려하여 매핑
            "초코송이": "choco",
            "쫄병": "jjolbyung"
        }

        prompt_content = """
            당신은 사용자의 음성 주문에서 물품과 수량을 추출해야 합니다.

            <목표>
            - 사용자의 입력에서 각 물품별 수량을 정확히 추출하세요.

            <물품 리스트>
            - 담배, 컵라면, 커피, 음료, 초코송이, 쫄병

            <출력 형식>
            - JSON 형식으로 반드시 다음과 같이 출력하세요: {{"물품명": 수량, "물품명": 수량, ...}}
            - 예시: {{"물": 2, "컵라면": 1, "과자1": 3}}
            - 수량이 명시되지 않은 물품은 1로 처리하세요.
            - 리스트에 없는 물품은 무시하세요.
            - JSON 형식만 출력하고 설명은 하지 마세요.
            - 수량 표현이 특정 물품 바로 뒤에 있으면 해당 물품에만 적용하세요.
            - 여러 물품 뒤에 "각각", "씩"이 있으면 모든 물품에 같은 수량을 적용하세요.
            - "한 개", "하나", "한병", "한 캔", "한 봉지"는 모두 수량 1로 처리하세요.

            <특수 규칙>
            - 명확한 물품 명칭이 없지만 문맥상 유추 가능한 경우(예: "마실 것" → 음료)는 리스트 내 항목으로 최대한 추론해 반환하세요.
            - 다수의 물품이 동시에 등장할 경우 각각에 대해 정확히 매칭하여 순서대로 출력하세요.

            <예시>
            - 입력: "물 2개 달라고"
            출력: {{"물": 2}}

            - 입력: "컵라면하고 과자1 3개"
            출력: {{"컵라면": 1, "과자1": 3}}

            - 입력: "음료 2개하고 과자2 하나"
            출력: {{"음료": 2, "과자2": 1}}

            <사용자 입력>
            "{user_input}"
        """
        
        self.prompt_template = PromptTemplate(
            input_variables=["user_input"], template=prompt_content
        )
        self.lang_chain = self.prompt_template | self.llm

    def extract_order(self, user_input):
        """사용자 입력에서 물품과 수량 추출"""
        try:
            response = self.lang_chain.invoke({"user_input": user_input})

            content = response.content.strip()
            content = content.replace("```json", "").replace("```", "").strip()

            print(f"주문 추출 LLM 응답: {content}")

            korean_dict = json.loads(content)
            
            english_dict = {}
            for kr_item, quantity in korean_dict.items():
                en_item = self.translation_map.get(kr_item, kr_item)
                english_dict[en_item] = quantity

            print(f"✅ 최종 추출된 영문 주문: {english_dict}")
            return english_dict

        except Exception as e:
            print(f"❌ 수량 추출 실패: {e}")
            return {}

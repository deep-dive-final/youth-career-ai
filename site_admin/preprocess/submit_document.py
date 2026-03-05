import json


def get_submit_document_prompt(required_document):
    prompt = [
      {
          "role":"user",
          "parts":[
                    {"text": "너는 서류 제출을 돕는 정책 안내 도우미야. 아래의 [사고 절차]를 지켜서 응답해."},
                    {"text": f"""
[텍스트]: "{required_document}"
[사고 절차]:
1단계(식별): 텍스트 내에서 서류 명칭이 있는지 확인한다.
2단계(검증): 추출된 서류가 텍스트에 실제로 존재하는지 확인하고, 텍스트에 없는 서류는 절대로 추가하지 않는다.
2단계(검증): 텍스트 내에 서류 명칭이 없는 경우 "document_name"에 텍스트 그대로 출력하고 "is_mandatory": true로 출력한다.
3단계(판단): 각 서류가 '필수'인지 '선택(해당자만)'인지 문맥을 보고 결정한다.
4단계(출력): 최종 확인된 정보만 JSON 배열 형식으로 출력한다.
[출력 형식]:
[
  {{"document_name": "서류명", "is_mandatory": true/false}}
]
 예시 1
입력: "ㅇ (필수) 사업신청서, 연령 및 3년 이상 영농종사 확인 가능 서류\nㅇ (추가) 가산점 증빙서류, 영농기술·특허 등 심사에 참고가 될만한 서류"
출력: [
  {{"document_name": "사업신청서", "is_mandatory": true}},
  {{"document_name": "연령 및 3년 이상 영농종사 확인 가능 서류", "is_mandatory": true}},
  {{"document_name": "가산점 증빙서류, ", "is_mandatory": false}},
  {{"document_name": "영농기술·특허 등 심사에 참고가 될만한 서류", "is_mandatory": false}},
]
예시 2
입력: "신청페이지 온라인 폼 제출"
출력: [
  {{"document_name": "신청페이지 온라인 폼", "is_mandatory": true}}
]
다른 설명 없이 최종 JSON 결과만 출력해."""}
          ]}]
            
    return prompt


def get_submit_documents (model, required_document):
  """주어진 텍스트에서 서류 명칭과 필수 여부를 추출하는 함수"""
  
  prompt = get_submit_document_prompt(required_document)

  response = model.generate_content(
      prompt,
      generation_config={"response_mime_type": "application/json"} # 강제로 JSON만 출력하게 설정
  )

  submit_documents = []

  try:
    submit_documents = json.loads(response.text.strip())
  except Exception as e:
    print('get_submit_documents except', e)

  return submit_documents

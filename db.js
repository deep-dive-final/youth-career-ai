var users = {
  _id: "ObjectId()",
  email: "user@email.com",
  provider: "email | google | kakao",
  created_at: "ISODate()",
  last_login_at: "ISODate()",
};

var user_profiles = {
  _id: "ObjectId()",
  user_id: "ObjectId()",
  age: "19-24 | 25-29 | 30-34 | 35-",
  job_status: "재직중 | 구직중 | 학생 | 창업준비중",
  income_level: "-50 | 50-100 | 100-150 | 150-",
  applied_in_6month: "Y | N",
  need_most: "당장 수입 | 방향 정리 | 자신감 회복 | 빠른 취업",
  created_at: "ISODate()",
};

var policies = {
  _id: "ObjectId()",
  type: "text | pdf",
  category: "취업 | 창업",
  policy_id: "WLF00004661",
  policy_name: "청년 취업 지원금 총정리",
  content: "2026년 기준...",
  source: "정부24",
  apply_start_date: "2026-01-01",
  apply_end_date: "2026-09-01",
  required_document: [
    {
      name: "자기소개서",
      format: "PDF",
      is_mandatory: true,
    },
    {
      name: "포트폴리오",
      format: "Link or PDF",
      is_mandatory: false,
    },
  ],
  eligibility: {
    age: { min: 20, max: 30 },
    own_home: false,
    income_level: "중위소득 150%이하",
  },
  homepage: "https://plus.gov.kr/",
  view_count: 123,
  published_at: "ISODate()",
  created_at: "ISODate()",
  updated_at: "ISODate()",
  is_active: true,
};

var policy_vectors = {
  _id: "ObjectId()",
  policy_id: "ObjectId()",
  chunk_id: 1,
  content_chunk: "청년내일채움공제는 중소기업에...",
  embedding_kure_v1: [0.0123, -0.998],
  embedding_e5_v1: [0.0123, -0.998],
  metadata: {
    policy_name: "청년 취업 지원금 총정리",
    source: "2025 청년월세 매뉴얼.pdf",
  },
  created_at: "ISODate()",
};

var Vector_Search_Index = [
  {
    name: "vector_kure_v1",
    type: "vectorSearch",
    definition: {
      fields: [
        {
          type: "vector",
          path: "embedding_kure_v1",
          numDimensions: 768,
          similarity: "cosine",
        },
      ],
    },
  },
  {
    name: "vector_e5_v1",
    type: "vectorSearch",
    definition: {
      fields: [
        {
          type: "vector",
          path: "embedding_e5_v1",
          numDimensions: 1024,
          similarity: "cosine",
        },
      ],
    },
  },
];

var fit_policy = {
  _id: "ObjectId()",
  user_profile_id: "ObjectId()",
  prompt_history_id: "ObjectId()",
  recommendations: [
    {
      policy_id: "ObjectId()",
      score: 0.9876,
      reason: "상신의 소득 수준과 나이가 완벽하게 일치해요!",
    },
  ],
  model: "gpt-4.1",
  embedding_model: "kure-v1",
  ai_comment:
    "사용자의 구직 활동 이력과 현재 상황을 고려할 때, 이 정책이 가장 적합합니다.",
  created_at: "ISODate()",
};

var prompt_history = {
  _id: "ObjectId()",
  type: "policy_recommendation",
  content:
    "사용자의 나이, 소득 수준, 구직 활동 이력 등을 고려하여 가장 적합한 취업 지원 정책을 추천해 주세요.",
  created_at: "ISODate()",
};

var embedding_models = {
  _id: "ObjectId()",
  model_key: "kure-v1",
  provider: "huggingface",
  model_name: "nlpai-lab/KURE-v1",
  num_dimensions: 768,
  similarity: "cosine",
  language: ["ko"],
  created_at: "ISODate()",
  is_active: true,
};

var chat_history = {
  _id: "ObjectId()",
  user_id: "ObjectId()",
  messages: [
    {
      role: "user",
      content: "취업 관련 정책 추천해줘",
      created_at: "ISODate()",
    },
    {
      role: "assistant",
      content: "취업 관련 추천 정책입니다.",
      used_policy: [
        {
          policy_id: "ObjectId()",
        },
      ],
      created_at: "ISODate()",
    },
  ],

  created_at: "ISODate()",
  updated_at: "ISODate()",
  is_closed: false,
};

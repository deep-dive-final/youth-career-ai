// 정책 데이터
const POLICIES = [
  {
    id: "20260107005400212077",
    name: "청년 월세 지원사업",
    category: "주거",
    amount: "최대 240만원",
    dday: "D-5",
    match: 95,
    comment: "당신의 소득 수준과 나이가 완벽하게 일치해요!",
    type: "현금",
    income: "중위소득 150% 이하",
    description: "만 19~34세 청년의 월세를 최대 20만원씩 12개월간 지원합니다.",
    requirements: [
      "만 19~34세",
      "무주택자",
      "중위소득 150% 이하",
      "보증금 5천만원 이하 월세 거주",
    ],
    documents: ["주민등록등본", "소득증명서", "임대차계약서", "통장사본"],
    deadline: "2026-01-25",
    agency: "국토교통부",
    link: "https://www.molit.go.kr",
  },
  {
    id: "20260107005400212072",
    name: "청년도약계좌",
    category: "취업",
    amount: "최대 5000만원",
    dday: "D-12",
    match: 88,
    comment: "장기 저축으로 목돈 마련의 기회!",
    type: "서비스",
    income: "중위소득 180% 이하",
    description:
      "5년간 매월 70만원 납입 시 정부기여금으로 최대 5,000만원 목돈 마련",
    requirements: [
      "만 19~34세",
      "개인소득 6,000만원 이하",
      "가구소득 중위 180% 이하",
    ],
    documents: ["신분증", "소득증명서", "가족관계증명서"],
    deadline: "2026-02-01",
    agency: "금융위원회",
    link: "https://www.fsc.go.kr",
  },
  {
    id: "20251231005400212058",
    name: "청년 내일채움공제",
    category: "창업",
    amount: "최대 1200만원",
    dday: "D-20",
    match: 82,
    comment: "중소기업 재직자라면 꼭 확인하세요!",
    type: "현금",
    income: "제한없음",
    description: "2년 근속 시 청년 1,200만원, 기업 1,200만원 총 2,400만원 수령",
    requirements: ["만 15~34세", "중소·중견기업 정규직", "2년 근속"],
    documents: ["재직증명서", "근로계약서", "신분증"],
    deadline: "2026-02-09",
    agency: "고용노동부",
    link: "https://www.moel.go.kr",
  },
  {
    id: "20251231005400212057",
    name: "청년 일자리 도약 장려금",
    category: "취업",
    amount: "최대 960만원",
    dday: "D-30",
    match: 75,
    comment: "신규 취업자에게 좋은 기회!",
    type: "현금",
    income: "중위소득 120% 이하",
    description: "중소기업 신규 취업 청년에게 월 80만원씩 최대 12개월 지원",
    requirements: ["만 18~34세", "중소기업 신규 취업", "6개월 이상 재직"],
    documents: ["재직증명서", "소득증명서", "4대보험 가입확인서"],
    deadline: "2026-02-19",
    agency: "고용노동부",
    link: "https://www.moel.go.kr",
  },
  {
    id: "20251230005400212056",
    name: "청년 문화패스",
    category: "생활",
    amount: "연 10만원",
    dday: "D-45",
    match: 70,
    comment: "문화생활을 즐기며 힐링하세요!",
    type: "서비스",
    income: "제한없음",
    description: "만 19~24세 청년에게 공연, 전시, 영화 등 문화 포인트 지원",
    requirements: ["만 19~24세", "본인인증"],
    documents: ["신분증"],
    deadline: "2026-03-05",
    agency: "문화체육관광부",
    link: "https://www.mcst.go.kr",
  },
];

// 설문 데이터
const SURVEY_QUESTIONS = [
  {
    step: 1,
    question: "나이를 선택해주세요",
    options: ["19-24세", "25-29세", "30-34세", "35세 이상"],
  },
  {
    step: 2,
    question: "관심 분야를 선택해주세요 (복수 선택 가능)",
    options: ["💼 취업", "🚀 창업", "🎓 교육", "💰 지원금", "🌱 심리/재도전"],
  },
  {
    step: 3,
    question: "거주 지역을 선택해주세요",
    options: [
      "서울",
      "부산",
      "대구",
      "인천",
      "광주",
      "대전",
      "울산",
      "세종",
      "경기",
      "충북",
      "충남",
      "전북",
      "전남",
      "경북",
      "경남",
      "강원",
      "제주",
    ],
  },
  {
    step: 4,
    question: "현재 또는 최종 학업 단계는 무엇인가요?",
    options: ["고등학교 이하", "전문대학", "대학교", "대학원"],
  },
  {
    step: 5,
    question: "현재 학업 상태를 선택해주세요",
    options: ["재학 중", "휴학 중", "졸업 예정", "졸업"],
  },
  {
    step: 6,
    question: "현재 고용 또는 활동 상태를 선택해주세요",
    options: ["재직 중", "구직 중", "창업준비중", "학생 또는 졸업 예정자"],
  },
  {
    step: 7,
    question: "소득 수준을 선택해주세요",
    options: [
      "중위소득 50% 이하 (월 130만 원 미만)",
      "중위소득 50~100% (월 130만 ~ 260만 원)",
      "중위소득 100~150% (월 260만 ~ 380만 원)",
      "중위소득 150% 이상 (월 380만 원 이상)",
    ],
  },
];

// localStorage 헬퍼 함수
const storage = {
  get: (key, defaultValue = null) => {
    try {
      const item = localStorage.getItem(key);
      return item ? JSON.parse(item) : defaultValue;
    } catch {
      return defaultValue;
    }
  },

  set: (key, value) => {
    try {
      localStorage.setItem(key, JSON.stringify(value));
      return true;
    } catch {
      return false;
    }
  },

  remove: (key) => {
    localStorage.removeItem(key);
  },
};

// 사용자 상태 관리
const user = {
  isLoggedIn: () => storage.get("isLoggedIn", false),

  getName: () => storage.get("userName", "게스트"),

  getProfile: () => storage.get("userProfile", {}),

  login: (name) => {
    storage.set("isLoggedIn", true);
    storage.set("userName", name);
  },

  logout: () => {
    storage.remove("isLoggedIn");
    storage.remove("userName");
    storage.remove("userProfile");
    storage.remove("profileImage");
  },

  updateProfile: (data) => {
    storage.set("userProfile", data);
  },
};

// 저장된 정책 관리
const savedPolicies = {
  getAll: () =>
    storage
      .get("savedPolicies", [])
      .map((policyId) => String(policyId))
      .filter((policyId, index, array) => policyId && array.indexOf(policyId) === index),

  add: (policyId) => {
    const normalizedId = String(policyId);
    const saved = savedPolicies.getAll();
    if (!saved.includes(normalizedId)) {
      saved.push(normalizedId);
      storage.set("savedPolicies", saved);
    }
  },

  remove: (policyId) => {
    const normalizedId = String(policyId);
    const saved = savedPolicies.getAll();
    const filtered = saved.filter((id) => id !== normalizedId);
    storage.set("savedPolicies", filtered);
  },

  isSaved: (policyId) => {
    return savedPolicies.getAll().includes(String(policyId));
  },

  toggle: (policyId) => {
    if (savedPolicies.isSaved(policyId)) {
      savedPolicies.remove(policyId);
      return false;
    } else {
      savedPolicies.add(policyId);
      return true;
    }
  },
};

// 알림 관리
const notifications = {
  getAll: () =>
    storage.get("notifications", [
      {
        id: 1,
        title: "청년 월세 지원사업 마감 임박!",
        message: "신청 마감이 5일 남았습니다. 서둘러 신청하세요!",
        time: "1시간 전",
        read: false,
      },
      {
        id: 2,
        title: "새로운 정책이 추가되었어요",
        message: "청년도약계좌가 새롭게 등록되었습니다.",
        time: "3시간 전",
        read: false,
      },
      {
        id: 3,
        title: "신청하신 정책이 승인되었습니다",
        message: "청년 내일채움공제 신청이 승인되었습니다.",
        time: "1일 전",
        read: true,
      },
    ]),

  markAsRead: (id) => {
    const all = notifications.getAll();
    const updated = all.map((n) => (n.id === id ? { ...n, read: true } : n));
    storage.set("notifications", updated);
  },

  getUnreadCount: () => {
    return notifications.getAll().filter((n) => !n.read).length;
  },
};

// 설문 결과 관리
const survey = {
  saveAnswers: (answers) => {
    storage.set("surveyAnswers", answers);
  },

  getAnswers: () => storage.get("surveyAnswers", {}),

  isCompleted: () => {
    const answers = survey.getAnswers();
    return Object.keys(answers).length === SURVEY_QUESTIONS.length;
  },
};

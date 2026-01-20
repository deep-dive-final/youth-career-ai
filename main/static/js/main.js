// 공통 JavaScript 기능

// 페이지 로드 시 실행
document.addEventListener("DOMContentLoaded", () => {
  initSidebar();
  initFloatingHomeButton();
  updateHeaderUI();
});

// 사이드바 초기화
function initSidebar() {
  const menuBtn = document.getElementById("menuBtn");
  const sidebar = document.getElementById("sidebar");
  const sidebarOverlay = document.getElementById("sidebarOverlay");
  const sidebarClose = document.getElementById("sidebarClose");

  if (menuBtn && sidebar && sidebarOverlay) {
    menuBtn.addEventListener("click", () => {
      sidebar.classList.add("active");
      sidebarOverlay.classList.add("active");
    });

    const closeSidebar = () => {
      sidebar.classList.remove("active");
      sidebarOverlay.classList.remove("active");
    };

    if (sidebarClose) {
      sidebarClose.addEventListener("click", closeSidebar);
    }

    sidebarOverlay.addEventListener("click", closeSidebar);
  }

  // 사이드바 사용자 정보 업데이트
  updateSidebarUser();
}

// 사이드바 사용자 정보 업데이트
function updateSidebarUser() {
  const sidebarUserName = document.getElementById("sidebarUserName");
  const sidebarUserEmail = document.getElementById("sidebarUserEmail");

  if (sidebarUserName) {
    sidebarUserName.textContent = user.getName();
  }

  if (sidebarUserEmail) {
    const profile = user.getProfile();
    sidebarUserEmail.textContent = profile.email || "guest@example.com";
  }
}

// 헤더 UI 업데이트
function updateHeaderUI() {
  const isLoggedIn = user.isLoggedIn();
  const userName = user.getName();

  // 사용자 이름 업데이트
  const userNameEl = document.getElementById("userName");
  if (userNameEl) {
    userNameEl.textContent = `${userName}님`;
  }

  // 로그인 버튼 표시/숨김
  const loginBtn = document.getElementById("loginBtn");
  if (loginBtn) {
    loginBtn.style.display = isLoggedIn ? "none" : "flex";
  }

  // 프로필 이미지 업데이트
  const profileBtn = document.getElementById("profileBtn");
  if (profileBtn) {
    const profileImage = localStorage.getItem("profileImage");
    if (isLoggedIn && profileImage) {
      profileBtn.innerHTML = `<img src="${profileImage}" alt="Profile">`;
    }
  }

  // 알림 배지 업데이트
  updateNotificationBadge();
}

// 알림 배지 업데이트
function updateNotificationBadge() {
  const badge = document.getElementById("notificationBadge");
  if (badge) {
    const unreadCount = notifications.getUnreadCount();
    badge.style.display = unreadCount > 0 ? "block" : "none";
  }
}

// Floating Home Button 초기화
function initFloatingHomeButton() {
  const currentPath = window.location.pathname;
  const floatingHome = document.getElementById("floatingHome");

  if (floatingHome) {
    // 홈 페이지에서는 숨김
    if (currentPath.endsWith("index.html") || currentPath === "/") {
      floatingHome.style.display = "none";
    }
  }
}

// 알림 클릭 핸들러
function handleNotificationClick() {
  if (!user.isLoggedIn()) {
    if (
      confirm("로그인이 필요한 기능입니다. 로그인 페이지로 이동하시겠습니까?")
    ) {
      window.location.href = "login.html";
    }
    return;
  }
  window.location.href = "notifications.html";
}

// 프로필 클릭 핸들러
function handleProfileClick() {
  if (user.isLoggedIn()) {
    window.location.href = "profile.html";
  } else {
    window.location.href = "login.html";
  }
}

// 로그아웃 핸들러
function handleLogout() {
  if (confirm("로그아웃 하시겠습니까?")) {
    user.logout();
    alert("로그아웃되었습니다.");
    window.location.href = "index.html";
  }
}

// 정책 카드 렌더링
function renderPolicyCard(policy) {
  const isSaved = savedPolicies.isSaved(policy.id);

  return `
    <a href="/policy?id=${policy.id}" class="policy-card">
      <div class="policy-header">
        <span class="policy-category">${policy.category}</span>
        <span class="policy-dday">${policy.dday}</span>
      </div>
      <h4>${policy.name}</h4>
      <p class="policy-amount">${policy.amount}</p>
      <div class="policy-comment">
        💬 ${policy.comment}
      </div>
      <div class="policy-match">
        <span class="match-label">매칭률</span>
        <span class="match-score">${policy.match}%</span>
      </div>
    </a>
  `;
}

// 정책 목록 렌더링
function renderPolicyList(containerId, policies) {
  const container = document.getElementById(containerId);
  if (!container) return;

  container.innerHTML = policies
    .map((policy) => renderPolicyCard(policy))
    .join("");
}

// 정책 상세 정보 가져오기
function getPolicyById(id) {
  return POLICIES.find((p) => p.id === parseInt(id));
}

// 날짜 포맷팅
function formatDate(dateString) {
  const date = new Date(dateString);
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}.${month}.${day}`;
}

// D-day 계산
function calculateDday(deadline) {
  const today = new Date();
  const deadlineDate = new Date(deadline);
  const diff = Math.ceil((deadlineDate - today) / (1000 * 60 * 60 * 24));

  if (diff < 0) return "마감";
  if (diff === 0) return "D-day";
  return `D-${diff}`;
}

// 검색 기능
function searchPolicies(query) {
  const lowerQuery = query.toLowerCase();
  return POLICIES.filter(
    (policy) =>
      policy.name.toLowerCase().includes(lowerQuery) ||
      policy.category.toLowerCase().includes(lowerQuery) ||
      policy.description.toLowerCase().includes(lowerQuery),
  );
}

// 필터링 기능
function filterPolicies(filters) {
  let filtered = [...POLICIES];

  if (filters.type && filters.type !== "all") {
    filtered = filtered.filter((p) => p.type === filters.type);
  }

  if (filters.income && filters.income !== "all") {
    filtered = filtered.filter(
      (p) => p.income.includes(filters.income) || p.income === "제한없음",
    );
  }

  if (filters.category && filters.category !== "all") {
    filtered = filtered.filter((p) => p.category === filters.category);
  }

  return filtered;
}

// 저장 토글
function toggleSavePolicy(policyId) {
  if (!user.isLoggedIn()) {
    if (
      confirm("로그인이 필요한 기능입니다. 로그인 페이지로 이동하시겠습니까?")
    ) {
      window.location.href = "login.html";
    }
    return;
  }

  const saved = savedPolicies.toggle(policyId);
  return saved;
}

// 신청하기
function applyPolicy(policyId) {
  if (!user.isLoggedIn()) {
    if (
      confirm("로그인이 필요한 기능입니다. 로그인 페이지로 이동하시겠습니까?")
    ) {
      window.location.href = "login.html";
    }
    return;
  }

  window.location.href = `application-form.html?id=${policyId}`;
}

// URL 파라미터 가져오기
function getUrlParameter(name) {
  const urlParams = new URLSearchParams(window.location.search);
  return urlParams.get(name);
}

// 뒤로 가기
function goBack() {
  window.history.back();
}

// SVG 아이콘
const icons = {
  menu: '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="3" y1="12" x2="21" y2="12"></line><line x1="3" y1="6" x2="21" y2="6"></line><line x1="3" y1="18" x2="21" y2="18"></line></svg>',

  user: '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>',

  bell: '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"></path><path d="M13.73 21a2 2 0 0 1-3.46 0"></path></svg>',

  home: '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path><polyline points="9 22 9 12 15 12 15 22"></polyline></svg>',

  search:
    '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"></circle><path d="m21 21-4.35-4.35"></path></svg>',

  filter:
    '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"></polygon></svg>',

  x: '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>',

  arrowLeft:
    '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="19" y1="12" x2="5" y2="12"></line><polyline points="12 19 5 12 12 5"></polyline></svg>',

  bookmark:
    '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m19 21-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"></path></svg>',

  bookmarkFilled:
    '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m19 21-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"></path></svg>',

  logIn:
    '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"></path><polyline points="10 17 15 12 10 7"></polyline><line x1="15" y1="12" x2="3" y2="12"></line></svg>',

  logOut:
    '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path><polyline points="16 17 21 12 16 7"></polyline><line x1="21" y1="12" x2="9" y2="12"></line></svg>',

  chevronRight:
    '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"></polyline></svg>',
};

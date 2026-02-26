/**
 * 맞춤정책 검색 프론트엔드
 * - 검색 API 호출
 * - 검색 결과 렌더링
 * - 페이지네이션 처리
 */

// ============================================================================
// 전역 변수
// ============================================================================
let currentPage = 1; // 현재 페이지
const PAGE_SIZE = 20; // 페이지당 결과 개수
const SHOW_RELEVANCE = false; // 매칭률(관련도) 표시 여부


// ============================================================================
// 공통 유틸 함수
// ============================================================================

/**
 * 숫자 형태의 값을 정수로 변환합니다.
 * @param {unknown} value
 * @returns {number|null}
 */
function toNumber(value) {
    if (value === null || value === undefined || value === "") {
        return null;
    }

    const parsed = Number(String(value).replace(/,/g, ""));
    return Number.isFinite(parsed) ? parsed : null;
}

/**
 * 금액 숫자를 사람이 읽기 쉬운 문자열로 변환합니다.
 * @param {number} value
 * @returns {string}
 */
function formatMoney(value) {
    return `${new Intl.NumberFormat("ko-KR").format(value)}원`;
}

/**
 * 긴 텍스트를 지정 길이로 줄입니다.
 * @param {string} text
 * @param {number} maxLength
 * @returns {string}
 */
function truncateText(text, maxLength = 100) {
    if (!text) return "";
    return text.length > maxLength ? `${text.substring(0, maxLength)}...` : text;
}

/**
 * 텍스트에서 금액(만원/원 등)을 정규식으로 추출합니다.
 * @param {string} text
 * @returns {string|null}
 */
function extractAmountFromText(text) {
    if (!text) return null;
    const amountMatch = String(text).match(/(?:월|연|최대|최소)?\s*\d[\d,]*(?:\s*[~-]\s*\d[\d,]*)?\s*(?:억|만원|천원|원)/);
    return amountMatch ? amountMatch[0].trim().replace(/\s+/g, " ") : null;
}

/**
 * 정책 데이터에서 금액 텍스트를 구성합니다.
 * 우선순위: amount_text -> earn.min/max -> earn.etc_content/suppport_content 정규식 추출
 * @param {Object} policy
 * @returns {string|null}
 */
function getAmountText(policy) {
    if (policy?.amount_text) return policy.amount_text;

    const earn = policy?.earn || {};
    const minAmt = toNumber(earn.min_amt);
    const maxAmt = toNumber(earn.max_amt);

    if (maxAmt !== null) {
        if (maxAmt > 0) {
            if (minAmt !== null && minAmt > 0) {
                return `${formatMoney(minAmt)} ~ ${formatMoney(maxAmt)}`;
            }
            return `최대 ${formatMoney(maxAmt)}`;
        }

        if (maxAmt === 0) {
            if (minAmt !== null && minAmt > 0) {
                return `최소 ${formatMoney(minAmt)}`;
            }
            return null;
        }
    }

    if (minAmt !== null && minAmt > 0) {
        return `최소 ${formatMoney(minAmt)}`;
    }

    return extractAmountFromText(earn.etc_content) || extractAmountFromText(policy?.support_content);
}

/**
 * 정책 마감일(dates.apply_period_end) 기준 D-day 라벨을 계산합니다.
 * @param {Object} policy
 * @returns {string}
 */
function getDdayLabel(policy) {
    const dates = policy?.dates || {};
    if (dates.apply_period_type === "마감") return "마감";

    const endDate = dates.apply_period_end;
    if (!endDate) return "-";
    if (endDate === "99991231") return "상시";

    const normalized = String(endDate);
    if (!/^\d{8}$/.test(normalized)) return "-";

    const yyyy = Number(normalized.slice(0, 4));
    const mm = Number(normalized.slice(4, 6));
    const dd = Number(normalized.slice(6, 8));

    const today = new Date();
    const startOfToday = new Date(today.getFullYear(), today.getMonth(), today.getDate());
    const deadline = new Date(yyyy, mm - 1, dd);

    if (Number.isNaN(deadline.getTime())) return "-";

    const diffMs = deadline.getTime() - startOfToday.getTime();
    const diffDays = Math.ceil(diffMs / (1000 * 60 * 60 * 24));

    if (diffDays > 0) return `D-${diffDays}`;
    if (diffDays === 0) return "D-Day";
    return "마감";
}


// ============================================================================
// 1️⃣ API 호출 함수
// ============================================================================

/**
 * 정책 검색 API 호출
 *
 * @param {string} query - 검색어
 * @param {Object} filters - 필터 조건 {category, subCategory, age, region, jobStatus, openOnly}
 * @param {number} page - 페이지 번호
 * @returns {Promise<Object|null>} 검색 결과 또는 null (에러 시)
 */
async function searchPoliciesAPI(query, filters = {}, page = 1) {
    try {
        // 쿼리 파라미터 구성
        const params = new URLSearchParams({
            query: query || "",
            page: page,
            page_size: PAGE_SIZE,
        });

        // 필터 조건 추가 (모든 필터 파라미터 포함)
        if (filters.category) params.append("category", filters.category);
        if (filters.subCategory) params.append("subCategory", filters.subCategory);
        if (filters.age) params.append("age", filters.age);
        if (filters.region) params.append("region", filters.region);
        if (filters.jobStatus) params.append("jobStatus", filters.jobStatus);
        if (filters.openOnly) params.append("openOnly", "true");

        const response = await fetch(`/search/api/search?${params.toString()}`);

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || "검색에 실패했습니다.");
        }

        return await response.json();
    } catch (error) {
        console.error("검색 오류:", error);
        alert(error.message);
        return null;
    }
}


// ============================================================================
// 2️⃣ 검색 실행 및 필터 수집
// ============================================================================

/**
 * 화면 입력값에서 필터 조건을 수집합니다.
 * @returns {Object}
 */
function collectFilters() {
    const filters = {};

    const category = document.getElementById("categoryFilter")?.value;
    if (category && category !== "all") {
        filters.category = category;

        // 카테고리가 선택되었을 때만 서브 카테고리를 읽음
        const subCategory = document.getElementById("subCategoryFilter")?.value;
        if (subCategory && subCategory !== "all") filters.subCategory = subCategory;
    }

    // 개인 조건 필터
    const age = document.getElementById("ageFilter")?.value;
    if (age) filters.age = parseInt(age, 10);

    const region = document.getElementById("regionFilter")?.value;
    if (region && region !== "all") filters.region = region;

    const jobStatus = document.getElementById("jobStatusFilter")?.value;
    if (jobStatus && jobStatus !== "all") filters.jobStatus = jobStatus;

    // 마감여부 (체크박스)
    const openOnly = document.getElementById("openOnly")?.checked;
    if (openOnly) filters.openOnly = true;

    return filters;
}

/**
 * 검색을 실행하고 결과를 렌더링합니다.
 * @param {number} page
 */
async function performSearch(page = 1) {
    const query = document.getElementById("searchInput")?.value.trim();
    currentPage = page;

    showLoading();

    try {
        const filters = collectFilters();
        const result = await searchPoliciesAPI(query, filters, page);

        if (result && result.results) {
            displaySearchResults(result.results);

            const resultCount = document.getElementById("resultCount");
            if (resultCount) {
                resultCount.textContent = `전체 ${result.total}개 정책`;
            }

            renderPagination(result.total, result.page, result.page_size);
        }
    } finally {
        hideLoading();
    }
}


// ============================================================================
// 3️⃣ 검색 결과 렌더링
// ============================================================================

/**
 * 검색 결과 목록을 카드 형태로 렌더링합니다.
 * @param {Array<Object>} policies
 */
function displaySearchResults(policies) {
    const container = document.getElementById("searchResults");
    const noResults = document.getElementById("noResults");

    if (!policies || policies.length === 0) {
        if (container) container.innerHTML = "";
        if (noResults) noResults.classList.remove("hidden");
        return;
    }

    if (noResults) noResults.classList.add("hidden");

    const html = policies.map((policy) => {
        const detailUrl = policy.policy_id ? `/policy/?id=${encodeURIComponent(policy.policy_id)}` : "#";
        const amountText = getAmountText(policy);
        const ddayLabel = getDdayLabel(policy);
        const summaryBase = policy.summary_text || policy.support_content || policy.content || "";
        const supportSummary = truncateText(summaryBase, 100) || "내용 없음";
        const isClosed = ddayLabel === "마감";

        return `
        <div
          onclick="${detailUrl !== "#" ? `window.location.href='${detailUrl}'` : ""}"
          style="background: white; border-radius: 24px; padding: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.05); transition: all 0.3s; margin-bottom: 16px; cursor: ${detailUrl !== "#" ? "pointer" : "default"}; ${isClosed ? "opacity: 0.7;" : ""}"
          onmouseover="this.style.transform='translateY(-4px)'; this.style.boxShadow='0 8px 16px rgba(0,0,0,0.1)'"
          onmouseout="this.style.transform='translateY(0)'; this.style.boxShadow='0 2px 8px rgba(0,0,0,0.05)'"
        >
          <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 12px; gap: 8px;">
            <span style="padding: 4px 12px; background: linear-gradient(to right, #a8e6cf, #7ec4cf); color: white; border-radius: 50px; font-size: 12px;">${policy.category || "기타"}</span>
            <span style="padding: 4px 12px; background: ${isClosed ? "#cbd5e0" : "#ff7eb9"}; color: white; border-radius: 50px; font-size: 12px;">${ddayLabel}</span>
          </div>

          <h4 style="font-size: 16px; color: #2d3748; margin-bottom: 8px;">${policy.policy_name || "정책명 없음"}</h4>
          ${amountText ? `<p style="font-size: 20px; color: #7ec4cf; margin-bottom: 12px;">${amountText}</p>` : ""}

          <div style="background: linear-gradient(to bottom right, #f8f9fd, #e8f4f8); border-radius: 16px; padding: 12px; margin-bottom: 12px; font-size: 13px; color: #7a8a9e;">
            ${supportSummary}
          </div>

          <div style="display: flex; align-items: center; justify-content: space-between; gap: 8px;">
            <span style="font-size: 13px; color: #7ec4cf;">${policy.supervising_agency || ""}</span>
          </div>

          ${SHOW_RELEVANCE && policy.search_score ? `<div style="margin-top: 8px; font-size: 12px; color: #a0aec0;">관련도 ${Math.round(policy.search_score * 100)}%</div>` : ""}
        </div>
      `;
    }).join("");

    if (container) container.innerHTML = html;
}


// ============================================================================
// 4️⃣ 페이지네이션
// ============================================================================

/**
 * 페이지네이션 UI를 렌더링합니다.
 * @param {number} total
 * @param {number} page
 * @param {number} pageSize
 */
function renderPagination(total, page, pageSize) {
    const container = document.getElementById("pagination");
    if (!container) return;

    const totalPages = Math.max(1, Math.ceil((total || 0) / (pageSize || PAGE_SIZE)));

    if ((total || 0) <= pageSize) {
        container.innerHTML = "";
        return;
    }

    const prevDisabled = page <= 1 ? "disabled" : "";
    const nextDisabled = page >= totalPages ? "disabled" : "";

    container.innerHTML = `
      <div style="display:flex; gap:10px; align-items:center; justify-content:center; margin-top:16px;">
        <button ${prevDisabled} onclick="performSearch(${page - 1})" style="padding:8px 12px; border:1px solid #cbd5e0; border-radius:10px; background:white; cursor:pointer;">이전</button>
        <span style="font-size:14px; color:#64748b;">${page} / ${totalPages}</span>
        <button ${nextDisabled} onclick="performSearch(${page + 1})" style="padding:8px 12px; border:1px solid #cbd5e0; border-radius:10px; background:white; cursor:pointer;">다음</button>
      </div>
    `;
}


// ============================================================================
// 5️⃣ 로딩 UI
// ============================================================================

/**
 * 로딩 상태를 표시합니다.
 */
function showLoading() {
    const container = document.getElementById("searchResults");
    if (container) {
        container.innerHTML = '<div style="text-align:center; padding:20px;">불러오는 중...</div>';
    }
}

/**
 * 로딩 상태를 해제합니다.
 */
function hideLoading() {
    // 별도 처리 없음
}

function getCookie(name) {
  let cookieValue = null;
  if (document.cookie && document.cookie !== "") {
    const cookies = document.cookie.split(";");
    for (let i = 0; i < cookies.length; i++) {
      const cookie = cookies[i].trim();
      if (cookie.substring(0, name.length + 1) === name + "=") {
        cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
        break;
      }
    }
  }
  return cookieValue;
}

function logout(redirect_url) {
  if (!confirm("로그아웃 하시겠습니까?")) return;

  fetch(`/accounts/api/auth/logout`, {
    method: "GET",
    headers: {
      "Content-Type": "application/json",
    },
  })
    .then((response) => response.json())
    .then((result) => {
      console.log("logout result", result);

      if (result.status === "success") location.href = redirect_url;
    })
    .catch((error) => {
      console.error("logout catch", error);
    });
}

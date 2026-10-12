// API 주소: 배포 후 Render 주소로 바꾸세요. (?api=주소 로 임시 지정 가능)
window.FUNDFLOW_API = new URLSearchParams(location.search).get("api") ||
  (["localhost", "127.0.0.1"].includes(location.hostname) ? "http://localhost:8000"
                                                          : "https://fundflow-api.onrender.com");

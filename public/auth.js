const authPage = document.body.dataset.page;
const authStatus = document.querySelector("#auth-status");
const loginForm = document.querySelector("#login-form");

async function getAuthState() {
  const response = await fetch("/api/auth", { cache: "no-store" });
  if (!response.ok) throw new Error("Could not check admin sign-in.");
  return response.json();
}

if (authPage === "login") {
  getAuthState().then((state) => {
    if (!state.configured) {
      authStatus.textContent = "Admin sign-in needs to be configured by the site owner.";
      loginForm.querySelector("button").disabled = true;
      return;
    }
    if (state.authenticated) {
      window.location.replace("/");
    }
  }).catch((error) => {
    authStatus.textContent = error.message;
  });

  loginForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const submit = loginForm.querySelector("button");
    submit.disabled = true;
    authStatus.textContent = "Signing in…";
    try {
      const response = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password: loginForm.elements.password.value }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Sign-in failed.");
      const next = new URLSearchParams(location.search).get("next");
      window.location.replace(next && next.startsWith("/") && !next.startsWith("//") ? next : "/");
    } catch (error) {
      authStatus.textContent = error.message;
      submit.disabled = false;
      loginForm.elements.password.focus();
    }
  });
} else {
  window.daybookAuthReady = getAuthState().then((state) => {
    if (!state.authenticated) {
      const next = encodeURIComponent(`${location.pathname}${location.search}`);
      window.location.replace(`/login.html?next=${next}`);
      return false;
    }
    return true;
  }).catch(() => {
    window.location.replace("/login.html");
    return false;
  });

  document.querySelector("#logout-button")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      const response = await fetch("/api/auth/logout", { method: "POST" });
      if (!response.ok) throw new Error("Sign-out failed.");
      window.location.replace("/login.html");
    } catch {
      button.disabled = false;
      window.alert("Could not sign out. Please try again.");
    }
  });
}

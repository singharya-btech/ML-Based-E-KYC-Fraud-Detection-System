"""Builds a click-to-launch Digio Web SDK component for Streamlit."""

import json


def build_digio_component(session: dict) -> str:
    environment = session["environment"]
    sdk_base = "https://ext.digio.in" if environment == "sandbox" else "https://app.digio.in"
    sdk_url = f"{sdk_base}/sdk/v11/digio.js"
    values = {
        "requestId": session["request_id"],
        "identifier": session["customer_identifier"],
        "accessTokenId": session.get("access_token_id"),
        "environment": environment,
    }
    payload = json.dumps(values, separators=(",", ":")).replace("<", "\\u003c")
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"></head>
<body>
<button id="digio-start" type="button">Continue securely with Digio</button>
<p id="digio-message" role="status" aria-live="polite">Your documents and live face capture are handled in Digio's verification flow.</p>
<script src="{sdk_url}"></script>
<script>
const session = {payload};
const button = document.getElementById("digio-start");
const message = document.getElementById("digio-message");
button.addEventListener("click", function () {{
  if (typeof window.Digio !== "function") {{
    message.textContent = "Digio could not be loaded. Check your connection and retry.";
    return;
  }}
  button.disabled = true;
  const options = {{
    environment: session.environment,
    is_iframe: true,
    callback: function (response) {{
      button.disabled = false;
      message.textContent = response && response.error_code
        ? "The Digio flow ended without completion. You can retry or check status below."
        : "Digio returned control. Check the provider status below; this message is not a verification result.";
    }}
  }};
  const digio = new window.Digio(options);
  digio.init();
  if (session.accessTokenId) {{
    digio.submit(session.requestId, session.identifier, session.accessTokenId);
  }} else {{
    digio.submit(session.requestId, session.identifier);
  }}
}});
</script>
</body>
</html>"""

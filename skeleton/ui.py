"""
TransitFlow — Gradio Web Interface
====================================
Run with:  python skeleton/ui.py
Then open: http://localhost:7860

Students: You do NOT need to change this file.
"""

import sys
sys.path.insert(0, ".")

import gradio as gr
from skeleton.agent import run_agent, _STATION_INDEX
from skeleton.llm_provider import llm
from skeleton.config import GEMINI_CHAT_MODEL, OLLAMA_CHAT_MODEL
from databases.relational.queries import (
    login_user,
    register_user,
    get_user_secret_question,
    verify_secret_answer,
    update_password,
    query_active_alerts,
    query_station_upcoming_departures,
    query_transit_system_analytics,
)

SECRET_QUESTIONS = [
    "What is the name of your first pet?",
    "What is your mother's maiden name?",
    "What city were you born in?",
    "What was the name of your first school?",
    "What is your favourite book?",
    "What was the make of your first car?",
]


# ── Chat handler ───────────────────────────────────────────────────────────────

def chat(user_message: str, history_display: list, agent_history: list,
         show_debug: bool, current_user: str):
    if not user_message.strip():
        return history_display, agent_history, gr.update()

    if show_debug:
        answer, new_agent_history, debug_text = run_agent(
            user_message, agent_history, debug=True, current_user_email=current_user
        )
    else:
        answer, new_agent_history = run_agent(
            user_message, agent_history, debug=False, current_user_email=current_user
        )
        debug_text = ""

    history_display = history_display + [
        {"role": "user",      "content": user_message},
        {"role": "assistant", "content": answer},
    ]

    debug_update = gr.update(value=debug_text, visible=show_debug)
    return history_display, new_agent_history, debug_update


def clear_conversation():
    return [], [], gr.update(value="", visible=False)


# ── Provider / model selection ────────────────────────────────────────────────

_KNOWN_OLLAMA_MODELS = ["llama3.2:1b", "llama3.1:8b"]


def get_ollama_status():
    if llm.ollama_available():
        return "🟢 Ollama is running locally"
    return "🔴 Ollama not detected — install from ollama.com and run `ollama pull " + OLLAMA_CHAT_MODEL + "`"


def get_chat_model_choices() -> list:
    available = set(llm.get_available_ollama_models())
    choices = []
    for m in _KNOWN_OLLAMA_MODELS:
        label = m if m in available else f"{m}  (not pulled)"
        choices.append((label, m))
    choices.append((f"☁️ Gemini ({GEMINI_CHAT_MODEL})", "gemini"))
    return choices


def get_initial_chat_model_value() -> str:
    return "llama3.2:1b"


def on_chat_model_change(value: str):
    if value == "gemini":
        status = llm.set_chat_provider("gemini")
        return f"**Active:** ☁️ Gemini ({GEMINI_CHAT_MODEL})\n\n{status}", get_ollama_status()
    available = set(llm.get_available_ollama_models())
    if value not in available:
        return f"⚠️ `{value}` is not pulled. Run: `ollama pull {value}`", get_ollama_status()
    llm.set_chat_provider("ollama")
    status = llm.set_chat_model(value)
    return f"**Active:** {value}\n\n{status}", get_ollama_status()


# ── Auth handlers ──────────────────────────────────────────────────────────────

def do_login(email: str, password: str):
    """Handle login form submission."""
    if not email.strip() or not password.strip():
        return (
            gr.update(value="Please enter your email and password.", visible=True),
            None,
            gr.update(), gr.update(), gr.update(), gr.update(),
            gr.update(visible=True),
        )

    user = login_user(email.strip(), password)
    if user is None:
        return (
            gr.update(value="Incorrect email or password.", visible=True),
            None,
            gr.update(), gr.update(), gr.update(), gr.update(),
            gr.update(visible=True),
        )

    display_name = f"{user['first_name']} {user['surname']}"
    return (
        gr.update(value="", visible=False),
        user["email"],
        gr.update(visible=False),
        gr.update(visible=False),
        gr.update(value=f"**Welcome, {display_name}**", visible=True),
        gr.update(visible=True),
        gr.update(visible=False),
    )


def do_logout():
    return (
        None,
        gr.update(visible=True),
        gr.update(visible=True),
        gr.update(value="", visible=False),
        gr.update(visible=False),
        gr.update(visible=False),
        gr.update(visible=False),
        gr.update(visible=False),
    )


def do_register(email, first_name, surname, year_of_birth, password, secret_question, secret_answer):
    """Handle registration form submission."""
    if not all([
        str(email).strip(), str(first_name).strip(), str(surname).strip(),
        str(password).strip(), secret_question, str(secret_answer).strip(),
    ]):
        return (
            gr.update(value="All fields are required.", visible=True),
            None,
            gr.update(), gr.update(), gr.update(), gr.update(),
            gr.update(visible=True),
        )

    try:
        year = int(year_of_birth)
        if year < 1900 or year > 2015:
            raise ValueError
    except (ValueError, TypeError):
        return (
            gr.update(value="Please enter a valid year of birth (e.g. 1990).", visible=True),
            None,
            gr.update(), gr.update(), gr.update(), gr.update(),
            gr.update(visible=True),
        )

    ok, err = register_user(
        email.strip(), first_name.strip(), surname.strip(),
        year, password, secret_question, secret_answer.strip(),
    )
    if not ok:
        return (
            gr.update(value=err, visible=True),
            None,
            gr.update(), gr.update(), gr.update(), gr.update(),
            gr.update(visible=True),
        )

    display_name = f"{first_name.strip()} {surname.strip()}"
    return (
        gr.update(value="", visible=False),
        email.strip().lower(),
        gr.update(visible=False),
        gr.update(visible=False),
        gr.update(value=f"**Welcome, {display_name}**", visible=True),
        gr.update(visible=True),
        gr.update(visible=False),
    )


def forgot_find_question(email: str):
    """Step 1 — look up the secret question for the given email."""
    if not email.strip():
        return (
            gr.update(value="Please enter your email address.", visible=True),
            gr.update(visible=False),
            gr.update(visible=False),
            gr.update(visible=False),
            gr.update(visible=False),
        )

    question = get_user_secret_question(email.strip())
    if question is None:
        return (
            gr.update(value="No account found with that email address.", visible=True),
            gr.update(visible=False),
            gr.update(visible=False),
            gr.update(visible=False),
            gr.update(visible=False),
        )

    return (
        gr.update(value="", visible=False),
        gr.update(value=f"**Your security question:** {question}", visible=True),
        gr.update(visible=True),
        gr.update(visible=True),
        gr.update(visible=True),
    )


def forgot_reset_password(email: str, answer: str, new_password: str):
    """Step 2 — verify the secret answer and update the password."""
    if not str(answer).strip() or not str(new_password).strip():
        return gr.update(value="Please fill in all fields.", visible=True)

    if not verify_secret_answer(email.strip(), answer.strip()):
        return gr.update(value="Incorrect answer. Please try again.", visible=True)

    if not update_password(email.strip(), new_password):
        return gr.update(value="Failed to update password. Please try again.", visible=True)

    return gr.update(value="**Password reset successfully. You can now log in.**", visible=True)


# ── Panel visibility toggles ──────────────────────────────────────────────────

def show_login_panel():
    return gr.update(visible=True), gr.update(visible=False), gr.update(visible=False)

def show_register_panel():
    return gr.update(visible=False), gr.update(visible=True), gr.update(visible=False)

def show_forgot_panel():
    return gr.update(visible=False), gr.update(visible=False), gr.update(visible=True)

def hide_all_panels():
    return gr.update(visible=False), gr.update(visible=False), gr.update(visible=False)


# ── Example queries ────────────────────────────────────────────────────────────

EXAMPLES = [
    "What national rail trains run from Central (NR01) to Stonehaven (NR05)?",
    "What is the fastest metro route from MS01 to MS14?",
    "How do I get from Central Square (MS01) to Stonehaven (NR05)?",
    "If Old Town station (NR03) is closed, what alternative routes exist from NR01 to NR05?",
    "My train was delayed 45 minutes — what compensation am I entitled to?",
    "What is the company policy on travelling with a bicycle on national rail?",
]


# ── Custom CSS & Helper Functions for Task 6 Extensions ────────────────────────

CUSTOM_CSS = """
/* Google Fonts import */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Outfit:wght@600;800&display=swap');

/* Global font settings */
body, .gradio-container {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
}

/* Custom Alert classes (Light mode default) */
.alerts-container {
    display: flex;
    flex-direction: column;
    gap: 12px;
    margin-top: 15px;
}
.alert-card {
    border-radius: 10px;
    padding: 16px 20px;
    border-left: 6px solid;
    background: rgba(0, 0, 0, 0.02);
    border: 1px solid rgba(0, 0, 0, 0.08);
    box-shadow: 0 4px 12px rgba(0,0,0,0.05);
    transition: transform 0.2s;
}
.alert-card:hover {
    transform: translateY(-2px);
}
.alert-high {
    border-left: 6px solid #ff4d4f !important;
    background: rgba(255, 77, 79, 0.04) !important;
}
.alert-medium {
    border-left: 6px solid #faad14 !important;
    background: rgba(250, 173, 20, 0.04) !important;
}
.alert-low {
    border-left: 6px solid #1890ff !important;
    background: rgba(24, 144, 255, 0.04) !important;
}
.alert-info {
    border-left: 6px solid #52c41a !important;
    background: rgba(82, 196, 26, 0.04) !important;
}
.alert-header {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 8px;
}
.badge {
    padding: 3px 10px;
    border-radius: 6px;
    font-weight: 700;
    font-size: 0.75em;
    letter-spacing: 0.5px;
    text-transform: uppercase;
}
.badge-high { background-color: #ff4d4f; color: white; }
.badge-medium { background-color: #faad14; color: black; }
.badge-low { background-color: #1890ff; color: white; }
.alert-line {
    background: rgba(0, 0, 0, 0.05);
    border: 1px solid rgba(0, 0, 0, 0.08);
    padding: 2px 8px;
    border-radius: 4px;
    font-weight: 600;
    font-size: 0.85em;
    color: #374151;
}
.alert-station {
    background: rgba(0, 0, 0, 0.05);
    border: 1px solid rgba(0, 0, 0, 0.08);
    padding: 2px 8px;
    border-radius: 4px;
    font-weight: 600;
    font-size: 0.85em;
    color: #374151;
}
.alert-time {
    margin-left: auto;
    color: #6b7280;
    font-size: 0.8em;
}
.alert-body {
    font-size: 0.95em;
    line-height: 1.5;
    color: #1f2937;
}

/* Analytics Dashboard styling (Light mode default) */
.analytics-dashboard {
    display: flex;
    flex-direction: column;
    gap: 24px;
    margin-top: 15px;
}
.kpi-row {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 16px;
}
.kpi-card {
    background: linear-gradient(135deg, rgba(0,0,0,0.02), rgba(0,0,0,0.005));
    border: 1px solid rgba(0, 0, 0, 0.08);
    border-radius: 14px;
    padding: 24px 20px;
    text-align: center;
    box-shadow: 0 6px 15px rgba(0,0,0,0.05);
    transition: transform 0.25s, box-shadow 0.25s;
}
.kpi-card:hover {
    transform: translateY(-4px);
    box-shadow: 0 12px 25px rgba(0,0,0,0.1);
    border-color: rgba(0, 0, 0, 0.15);
}
.kpi-val {
    font-size: 2em;
    font-weight: 700;
    color: #0284c7;
    margin-bottom: 6px;
}
.kpi-label {
    font-size: 0.85em;
    color: #4b5563;
    font-weight: 500;
    letter-spacing: 0.3px;
}
.details-row {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
    gap: 20px;
}
.detail-box {
    background: rgba(0,0,0,0.01);
    border: 1px solid rgba(0,0,0,0.05);
    border-radius: 12px;
    padding: 20px;
}
.detail-box h4 {
    margin-top: 0;
    margin-bottom: 15px;
    border-bottom: 1px solid rgba(0,0,0,0.08);
    padding-bottom: 10px;
    color: #1f2937;
    font-size: 1.1em;
    font-weight: 600;
}
.detail-box ul {
    padding-left: 20px;
    margin-bottom: 0;
}
.detail-box li {
    margin-bottom: 10px;
    color: #374151;
    font-size: 0.95em;
}

/* ============================================================ */
/* DARK MODE OVERRIDES (.dark class added by Gradio to body) */
/* ============================================================ */
.dark .alert-card {
    background: rgba(255, 255, 255, 0.03) !important;
    border: 1px solid rgba(255, 255, 255, 0.08) !important;
    box-shadow: 0 4px 12px rgba(0,0,0,0.2) !important;
}
.dark .alert-high {
    background: rgba(255, 77, 79, 0.08) !important;
}
.dark .alert-medium {
    background: rgba(250, 173, 20, 0.08) !important;
}
.dark .alert-low {
    background: rgba(24, 144, 255, 0.08) !important;
}
.dark .alert-info {
    background: rgba(82, 196, 26, 0.08) !important;
}
.dark .alert-body {
    color: rgba(255, 255, 255, 0.85) !important;
}
.dark .alert-line, .dark .alert-station {
    background: rgba(255, 255, 255, 0.12) !important;
    border: 1px solid rgba(255,255,255,0.1) !important;
    color: rgba(255, 255, 255, 0.85) !important;
}
.dark .alert-time {
    color: rgba(255, 255, 255, 0.45) !important;
}

.dark .kpi-card {
    background: linear-gradient(135deg, rgba(255,255,255,0.05), rgba(255,255,255,0.01)) !important;
    border: 1px solid rgba(255, 255, 255, 0.08) !important;
    box-shadow: 0 6px 20px rgba(0,0,0,0.15) !important;
}
.dark .kpi-card:hover {
    border-color: rgba(255, 255, 255, 0.15) !important;
}
.dark .kpi-val {
    color: #38bdf8 !important;
}
.dark .kpi-label {
    color: rgba(255, 255, 255, 0.5) !important;
}

.dark .detail-box {
    background: rgba(255,255,255,0.02) !important;
    border: 1px solid rgba(255,255,255,0.06) !important;
}
.dark .detail-box h4 {
    border-bottom: 1px solid rgba(255,255,255,0.1) !important;
    color: rgba(255, 255, 255, 0.9) !important;
}
.dark .detail-box li {
    color: rgba(255, 255, 255, 0.75) !important;
}
"""

def get_alerts_html():
    alerts = query_active_alerts()
    if not alerts:
        return "<div class='alert-card alert-info'>🟢 No active service alerts. All networks operating normally.</div>"
    
    html = "<div class='alerts-container'>"
    for a in alerts:
        sev = a["severity"].lower()
        badge_class = f"badge-{sev}"
        line_info = f"<span class='alert-line'>{a['line']}</span>" if a.get("line") else ""
        station_info = f"<span class='alert-station'>{a['station_id']}</span>" if a.get("station_id") else ""
        tags = " ".join(filter(None, [line_info, station_info]))
        
        html += f"""
        <div class="alert-card alert-{sev}">
            <div class="alert-header">
                <span class="badge {badge_class}">{sev.upper()}</span>
                {tags}
                <span class="alert-time">{a.get('created_at', '')}</span>
            </div>
            <div class="alert-body">
                {a['message']}
            </div>
        </div>
        """
    html += "</div>"
    return html


def get_departures_markdown(station_id: str):
    if not station_id:
        return "Please select a station to view departures."
    departures = query_station_upcoming_departures(station_id)
    if not departures:
        return "No departures found for this station."
    
    md = "| Time | Type | Line | Direction | Destination |\n"
    md += "| --- | --- | --- | --- | --- |\n"
    for d in departures:
        md += f"| **{d['departure_time']}** | {d['type']} | {d['line']} | {d['direction'].title()} | {d['destination']} |\n"
    return md


def get_analytics_html():
    data = query_transit_system_analytics()
    if not data:
        return "<div style='padding: 20px; text-align: center; color: #888;'>No analytics data available.</div>"
    
    html = f"""
    <div class="analytics-dashboard">
        <div class="kpi-row">
            <div class="kpi-card">
                <div class="kpi-val">${data.get('total_system_revenue', 0.0):,.2f}</div>
                <div class="kpi-label">Total System Revenue</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-val">{data.get('total_national_rail_bookings', 0):,}</div>
                <div class="kpi-label">Rail Bookings</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-val">{data.get('total_metro_trips', 0):,}</div>
                <div class="kpi-label">Metro Trips</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-val">⭐️ {data.get('average_user_rating', 0.0):.2f}/5</div>
                <div class="kpi-label">Avg Rating ({data.get('total_feedbacks_received', 0)} reviews)</div>
            </div>
        </div>
        
        <div class="details-row">
            <div class="detail-box">
                <h4>🔥 Busiest Rail Origin Stations</h4>
                <ul>
    """
    for s in data.get("top_rail_origin_stations", []):
        html += f"<li><strong>{s['origin_station_name']}</strong>: {s['passenger_count']} passengers</li>"
    if not data.get("top_rail_origin_stations"):
        html += "<li>No data available</li>"
        
    html += """
                </ul>
            </div>
            <div class="detail-box">
                <h4>💳 Payment Method Breakdown</h4>
                <ul>
    """
    for p in data.get("revenue_by_payment_method", []):
        html += f"<li><strong>{p['method'].replace('_', ' ').title()}</strong>: {p['count']} payments (${p['revenue']:,.2f})</li>"
    if not data.get("revenue_by_payment_method"):
        html += "<li>No data available</li>"
        
    html += """
                </ul>
            </div>
        </div>
    </div>
    """
    return html

station_choices = [
    (f"{name.title()} ({sid})", sid)
    for name, sid in sorted(_STATION_INDEX.items(), key=lambda x: x[1])
]

# ── Build UI ───────────────────────────────────────────────────────────────────

with gr.Blocks(title="TransitFlow", css=CUSTOM_CSS) as demo:

    # ── Hidden state ──────────────────────────────────────────────────
    agent_history_state = gr.State([])
    current_user_state  = gr.State(None)   # None = guest, email str = logged in

    # ── Header Banner ────────────────────────────────────────────────
    with gr.Row(equal_height=True):
        gr.HTML("""
        <div style="background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%); padding: 24px; border-radius: 16px; margin-bottom: 20px; color: white !important; box-shadow: 0 8px 32px rgba(0,0,0,0.15); width: 100%;">
            <h1 style="margin: 0; color: white !important; font-weight: 800; font-size: 2.3em; font-family: 'Outfit', 'Inter', sans-serif; letter-spacing: -0.5px;">🚂 TransitFlow Intelligent Transit Assistant</h1>
            <p style="margin: 8px 0 0 0; color: rgba(255, 255, 255, 0.9) !important; font-size: 1.15em; font-family: 'Inter', sans-serif;">Next-generation dual-network routing, live departures schedule, and operations analytics.</p>
        </div>
        """, scale=4)
        with gr.Column(scale=1, min_width=240):
            with gr.Row():
                login_btn    = gr.Button("👤 Login",    size="sm", variant="secondary")
                register_btn = gr.Button("📝 Register", size="sm", variant="secondary")
            user_info_display = gr.Markdown("", visible=False)
            logout_btn = gr.Button("Logout", size="sm", variant="stop", visible=False)

    # ── Login panel (hidden by default) ──────────────────────────────
    with gr.Column(visible=False) as login_panel:
        gr.Markdown("### Login")
        login_email_in    = gr.Textbox(label="Email", placeholder="you@example.com")
        login_password_in = gr.Textbox(label="Password", type="password")
        login_error_msg   = gr.Markdown("", visible=False)
        with gr.Row():
            login_submit_btn = gr.Button("Login", variant="primary")
            forgot_link_btn  = gr.Button("Forgot password?", size="sm")
            login_cancel_btn = gr.Button("Cancel", size="sm")

    # ── Register panel (hidden by default) ───────────────────────────
    with gr.Column(visible=False) as register_panel:
        gr.Markdown("### Create an Account")
        with gr.Row():
            reg_first_name_in = gr.Textbox(label="First name")
            reg_surname_in    = gr.Textbox(label="Surname")
        reg_email_in    = gr.Textbox(label="Email", placeholder="you@example.com")
        reg_year_in     = gr.Textbox(label="Year of birth", placeholder="e.g. 1990")
        reg_password_in = gr.Textbox(label="Password", type="password")
        reg_question_in = gr.Dropdown(choices=SECRET_QUESTIONS, label="Security question")
        reg_answer_in   = gr.Textbox(label="Secret answer")
        reg_error_msg   = gr.Markdown("", visible=False)
        with gr.Row():
            reg_submit_btn = gr.Button("Register", variant="primary")
            reg_cancel_btn = gr.Button("Cancel", size="sm")

    # ── Forgot password panel (hidden by default) ─────────────────────
    with gr.Column(visible=False) as forgot_panel:
        gr.Markdown("### Reset Your Password")
        forgot_email_in          = gr.Textbox(label="Email address", placeholder="you@example.com")
        forgot_check_btn         = gr.Button("Find my question", variant="secondary")
        forgot_question_display  = gr.Markdown("", visible=False)
        forgot_answer_in         = gr.Textbox(label="Your answer", visible=False)
        forgot_new_password_in   = gr.Textbox(label="New password", type="password", visible=False)
        forgot_reset_btn         = gr.Button("Reset password", variant="primary", visible=False)
        forgot_msg               = gr.Markdown("")
        forgot_back_btn          = gr.Button("Back to login", size="sm")

    # ── Main layout area ──────────────────────────────────────────────
    with gr.Row():

        # ── Left: Main Panel Tabs ─────────────────────────────────────
        with gr.Column(scale=3):
            with gr.Tabs():
                with gr.Tab("💬 AI Chat Assistant"):
                    chatbot = gr.Chatbot(label="TransitFlow Assistant", height=420)

                    with gr.Row():
                        msg = gr.Textbox(
                            placeholder="Ask e.g. 'Are there seats from London to Bristol?'",
                            show_label=False,
                            scale=4,
                        )
                        send_btn = gr.Button("Send", variant="primary", scale=1)

                    with gr.Row():
                        clear_btn    = gr.Button("🗑️ Clear conversation", size="sm")
                        debug_toggle = gr.Checkbox(label="🔍 Show database debug panel", value=True)

                    # Debug panel — hidden until checkbox is ticked and a message is sent
                    debug_panel = gr.Markdown(
                        value="",
                        visible=False,
                    )
                    
                with gr.Tab("⚠️ Service Alerts"):
                    gr.Markdown("### 📢 Active Network & Operator Alerts")
                    gr.Markdown("View real-time service disruptions, delays, or maintenance updates across the networks.")
                    alerts_html = gr.HTML(value=get_alerts_html())
                    refresh_alerts_btn = gr.Button("🔄 Refresh Service Alerts", size="sm")
                    
                with gr.Tab("🕒 Station Departures"):
                    gr.Markdown("### 🕒 Real-Time Station Departures")
                    gr.Markdown("Select a station to dynamically compute and display all scheduled train departures for today.")
                    with gr.Row(equal_height=True):
                        station_dd = gr.Dropdown(
                            choices=station_choices,
                            label="Select Transit Station",
                            value="MS01",
                            scale=3
                        )
                        get_departures_btn = gr.Button("🔍 Show Departures", variant="primary", scale=1)
                    departures_table = gr.Markdown(value=get_departures_markdown("MS01"))
                    
                with gr.Tab("📊 System Analytics"):
                    gr.Markdown("### 📊 System Operations & Analytics Dashboard")
                    gr.Markdown("Aggregate real-time metrics showing total passenger volume, revenue, and satisfaction statistics.")
                    analytics_html = gr.HTML(value=get_analytics_html())
                    refresh_analytics_btn = gr.Button("🔄 Refresh Dashboard", size="sm")

        # ── Right: sidebar ────────────────────────────────────────────
        with gr.Column(scale=1):

            gr.Markdown("### 🤖 LLM Provider")
            chat_model_dropdown = gr.Dropdown(
                choices=get_chat_model_choices(),
                value=get_initial_chat_model_value(),
                label="Chat model",
                info="Local Ollama models run fully locally. Gemini uses your API key.",
            )
            provider_status = gr.Markdown(value="**Active:** llama3.2:1b")
            ollama_status   = gr.Markdown(value=get_ollama_status())

            gr.Markdown("---")

            gr.Markdown("### 💡 Try these examples")
            for example in EXAMPLES:
                gr.Button(example, size="sm").click(
                    fn=lambda e=example: e,
                    outputs=msg,
                )

    # ── Event wiring ──────────────────────────────────────────────────

    chat_model_dropdown.change(
        fn=on_chat_model_change,
        inputs=chat_model_dropdown,
        outputs=[provider_status, ollama_status],
    )

    send_btn.click(
        fn=chat,
        inputs=[msg, chatbot, agent_history_state, debug_toggle, current_user_state],
        outputs=[chatbot, agent_history_state, debug_panel],
    ).then(fn=lambda: "", outputs=msg)

    msg.submit(
        fn=chat,
        inputs=[msg, chatbot, agent_history_state, debug_toggle, current_user_state],
        outputs=[chatbot, agent_history_state, debug_panel],
    ).then(fn=lambda: "", outputs=msg)

    clear_btn.click(
        fn=clear_conversation,
        outputs=[chatbot, agent_history_state, debug_panel],
    )

    # Panel toggle buttons
    login_btn.click(
        fn=show_login_panel,
        outputs=[login_panel, register_panel, forgot_panel],
    )
    register_btn.click(
        fn=show_register_panel,
        outputs=[login_panel, register_panel, forgot_panel],
    )
    login_cancel_btn.click(
        fn=hide_all_panels,
        outputs=[login_panel, register_panel, forgot_panel],
    )
    reg_cancel_btn.click(
        fn=hide_all_panels,
        outputs=[login_panel, register_panel, forgot_panel],
    )
    forgot_link_btn.click(
        fn=show_forgot_panel,
        outputs=[login_panel, register_panel, forgot_panel],
    )
    forgot_back_btn.click(
        fn=show_login_panel,
        outputs=[login_panel, register_panel, forgot_panel],
    )

    # Login
    login_submit_btn.click(
        fn=do_login,
        inputs=[login_email_in, login_password_in],
        outputs=[
            login_error_msg,
            current_user_state,
            login_btn,
            register_btn,
            user_info_display,
            logout_btn,
            login_panel,
        ],
    )

    # Logout
    logout_btn.click(
        fn=do_logout,
        outputs=[
            current_user_state,
            login_btn,
            register_btn,
            user_info_display,
            logout_btn,
            login_panel,
            register_panel,
            forgot_panel,
        ],
    )

    # Register
    reg_submit_btn.click(
        fn=do_register,
        inputs=[
            reg_email_in, reg_first_name_in, reg_surname_in,
            reg_year_in, reg_password_in, reg_question_in, reg_answer_in,
        ],
        outputs=[
            reg_error_msg,
            current_user_state,
            login_btn,
            register_btn,
            user_info_display,
            logout_btn,
            register_panel,
        ],
    )

    # Forgot password — step 1: find question
    forgot_check_btn.click(
        fn=forgot_find_question,
        inputs=[forgot_email_in],
        outputs=[
            forgot_msg,
            forgot_question_display,
            forgot_answer_in,
            forgot_new_password_in,
            forgot_reset_btn,
        ],
    )

    # Operator Alerts Tab wiring
    refresh_alerts_btn.click(
        fn=get_alerts_html,
        outputs=alerts_html,
    )

    # Station Departures Tab wiring
    get_departures_btn.click(
        fn=get_departures_markdown,
        inputs=station_dd,
        outputs=departures_table,
    )
    station_dd.change(
        fn=get_departures_markdown,
        inputs=station_dd,
        outputs=departures_table,
    )

    # System Analytics Tab wiring
    refresh_analytics_btn.click(
        fn=get_analytics_html,
        outputs=analytics_html,
    )


if __name__ == "__main__":
    demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
        theme=gr.themes.Soft(),
    )

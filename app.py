"""
Formula 101 - Agente Inteligente de Fórmula 1
Interfaz Streamlit con chat y visualización de tool calls.
"""

import os
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────
# CONFIGURACIÓN DE PÁGINA
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="Fórmula 101",
    page_icon="view/logoF101.png",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────
# CSS PERSONALIZADO
# ─────────────────────────────────────────────
st.markdown(
    """
<style>
    /* Fondo oscuro inspirado en F1 */
    .stApp { background-color: #0d0d0d; }

    /* Header principal */
    .f1-header {
        background: linear-gradient(135deg, #1a1a2e 10%, #a81e1e 90%);
        padding: 1.5rem 2rem;
        border-radius: 12px;
        margin-bottom: 1.5rem;
    }
    .f1-header h1 { color: white; margin: 0; font-size: 2rem; }
    .f1-header p  { color: #fff; margin: 0.3rem 0 0 0; font-size: 0.95rem; }

    /* Tool call badge */
    .tool-badge {
        background: #1a1a2e;
        border-left: 3px solid #e10600;
        padding: 0.4rem 0.8rem;
        border-radius: 0 6px 6px 0;
        font-size: 0.8rem;
        color: #aaa;
        margin: 0.2rem 0;
    }
    .tool-name { color: #ffcc00; font-weight: bold; }

    /* Quick query buttons */
    div[data-testid="stButton"] > button {
        background-color: #1a1a2e;
        color: #ddd;
        border: 1px solid #333;
        border-radius: 8px;
        font-size: 0.8rem;
        padding: 0.3rem 0.6rem;
        width: 100%;
        text-align: left;
        transition: all 0.2s;
    }
    div[data-testid="stButton"] > button:hover {
        background-color: #e10600;
        color: white;
        border-color: #e10600;
    }

    /* Chat message styling */
    .stChatMessage { background-color: #1a1a1a !important; }
</style>
""",
    unsafe_allow_html=True,
)


# ─────────────────────────────────────────────
# INICIALIZACIÓN DEL AGENTE (CACHEADO)
# ─────────────────────────────────────────────
@st.cache_resource(show_spinner="Iniciando agente Fórmula 101...")
def load_agent():
    """Carga el agente y el RAG una sola vez."""
    from agent.rag import get_or_create_vector_store
    from agent.graph import get_agent
    get_or_create_vector_store()
    get_agent()
    from agent.graph import AgentStream
    return AgentStream


# ─────────────────────────────────────────────
# HEADER
# ─────────────────────────────────────────────
import base64

def get_image_base64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

logo_b64 = get_image_base64("view/logoF101.png")

st.markdown(
    f"""
<div class="f1-header">
    <img src="data:image/png;base64,{logo_b64}" alt="Fórmula 101 Logo" style="width: 300px; vertical-align: middle; margin-top:-50px;margin-bottom:-50px;">
    <h1>Fórmula 101</h1>
    <p>Agente Inteligente de Fórmula 1 · Powered by LangGraph + Gemini + RAG</p>
</div>
""",
    unsafe_allow_html=True,
)


# ─────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────

with st.sidebar:
    st.markdown("## ⚙️ Configuración")

    api_key = os.getenv("GOOGLE_API_KEY", "")
    if not api_key:
        api_key = st.text_input(
            "Google API Key",
            type="password",
            placeholder="AIza...",
            help="Ingresa tu API key de Google AI Studio. Se puede configurar también en el archivo .env",
        )
        if api_key:
            os.environ["GOOGLE_API_KEY"] = api_key
    else:
        st.success("✅ API Key configurada")

    st.divider()

    st.markdown("## 🛠️ Herramientas disponibles")
    tools_info = [
        (
            "⚡ OpenF1 API",
            "Datos en tiempo real: posiciones, pit stops, clima, tiempos",
        ),
        (
            "📊 Jolpica API",
            "Histórico: campeonatos, resultados, calendarios desde 1950",
        ),
        ("🧠 Base RAG", "Conocimiento: reglamentos, equipos, historia, estrategia"),
    ]
    for name, desc in tools_info:
        st.markdown(f"**{name}**  \n{desc}")

    st.divider()

    st.markdown("## 💡 Consultas rápidas")
    quick_queries = [
        "¿Cuál fue la última carrera de F1?",
        "¿Quién ganó el campeonato 2023?",
        "¿Cómo funciona el efecto suelo?",
        "Muéstrame el campeonato de pilotos 2021",
        "¿Qué equipos compiten en F1 2025?",
        "¿Cuántos títulos tiene Verstappen?",
        "Explica la estrategia de undercut",
        "¿Quiénes son los pilotos de Ferrari en 2025?",
        "Muéstrame el calendario de la temporada 2024",
        "¿Qué es el DRS?",
    ]
    for q in quick_queries:
        if st.button(q, key=f"quick_{q}"):
            st.session_state.pending_query = q

    st.divider()

    if st.button("🗑️ Limpiar conversación", use_container_width=True):
        st.session_state.messages = []
        st.session_state.tool_history = []
        st.rerun()

    st.markdown("---")
    st.caption("Fórmula 101 · Proyecto Final Sistemas Inteligentes · UNAL")


# ─────────────────────────────────────────────
# ESTADO DE SESIÓN
# ─────────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = []
if "tool_history" not in st.session_state:
    st.session_state.tool_history = {}
if "pending_query" not in st.session_state:
    st.session_state.pending_query = None


# ─────────────────────────────────────────────
# LAYOUT: CHAT + TOOL PANEL
# ─────────────────────────────────────────────
col_chat, col_tools = st.columns([2, 1])

with col_chat:
    st.markdown("### 💬 Chat")

    # Mensaje de bienvenida si no hay historial
    if not st.session_state.messages:
        st.info(
            "👋 ¡Hola! Soy Fórmula 101, tu agente experto en Fórmula 1. "
            "Puedo consultarle datos en tiempo real, resultados históricos y explicarte "
            "todo sobre el deporte. ¡Pregúntame lo que quieras!"
        )

    # Mostrar historial de mensajes
    for i, msg in enumerate(st.session_state.messages):
        with st.chat_message(
            msg["role"], avatar="🏎️" if msg["role"] == "assistant" else "👤"
        ):
            st.markdown(msg["content"])
            # Mostrar tools usadas debajo del mensaje del asistente
            if msg["role"] == "assistant" and i in st.session_state.tool_history:
                tools_used = st.session_state.tool_history[i]
                if tools_used:
                    with st.expander(
                        f"🔧 {len(tools_used)} herramienta(s) usada(s)", expanded=False
                    ):
                        for tc in tools_used:
                            st.markdown(
                                f'<div class="tool-badge">'
                                f'<span class="tool-name">⚡ {tc["tool"]}</span><br>'
                                f'<small>{str(tc["input"])[:200]}</small>'
                                f"</div>",
                                unsafe_allow_html=True,
                            )

    # Input del usuario
    user_input = st.chat_input("Pregunta sobre F1...")

    # Procesar consulta pendiente (desde sidebar)
    if st.session_state.pending_query:
        user_input = st.session_state.pending_query
        st.session_state.pending_query = None


# ─────────────────────────────────────────────
# PROCESAR INPUT
# ─────────────────────────────────────────────
if user_input:
    # Verificar API key
    if not os.getenv("GOOGLE_API_KEY"):
        with col_chat:
            st.error(
                "⚠️ Configura tu Anthropic API Key en el sidebar o en el archivo .env"
            )
        st.stop()

    # Agregar mensaje del usuario
    st.session_state.messages.append({"role": "human", "content": user_input})

    # Mostrar mensaje del usuario
    with col_chat:
        with st.chat_message("user", avatar="👤"):
            st.markdown(user_input)

        # Respuesta del agente con streaming
        with st.chat_message("assistant", avatar="🏎️"):
            AgentStream = load_agent()
            history = st.session_state.messages[:-1]

            answer_placeholder = st.empty()
            answer_placeholder.markdown("*Consultando datos F1...* ⏳")

            try:
                stream     = AgentStream(user_input, history)
                full_answer = ""

                for chunk in stream:
                    full_answer += chunk
                    answer_placeholder.markdown(full_answer + "▌")

                answer_placeholder.markdown(full_answer)
                answer     = full_answer
                tool_calls = stream.tool_calls

            except Exception as e:
                err = str(e)
                if "429" in err or "RESOURCE_EXHAUSTED" in err:
                    answer = (
                        "⚠️ **Límite de cuota alcanzado.**\n\n"
                        "Espera ~1 minuto e intenta de nuevo (límite free tier: 15 req/min)."
                    )
                elif "API_KEY" in err or "401" in err or "403" in err:
                    answer = "⚠️ **API Key inválida.** Verifica la clave en tu archivo `.env`."
                else:
                    answer = f"⚠️ **Error:** {err[:300]}"
                tool_calls = []
                answer_placeholder.markdown(answer)

            # Mostrar tools usadas
            if tool_calls:
                msg_index = len(
                    st.session_state.messages
                )  # índice del mensaje que vamos a agregar
                with st.expander(
                    f"🔧 {len(tool_calls)} herramienta(s) usada(s)", expanded=False
                ):
                    for tc in tool_calls:
                        st.markdown(
                            f'<div class="tool-badge">'
                            f'<span class="tool-name">⚡ {tc["tool"]}</span><br>'
                            f'<small>{str(tc["input"])[:200]}</small>'
                            f"</div>",
                            unsafe_allow_html=True,
                        )

    # Guardar respuesta y metadata
    msg_index = len(st.session_state.messages)
    st.session_state.messages.append({"role": "assistant", "content": answer})
    st.session_state.tool_history[msg_index] = tool_calls

    # Actualizar panel de herramientas
    with col_tools:
        pass

    st.rerun()


# ─────────────────────────────────────────────
# PANEL LATERAL DERECHO: ESTADÍSTICAS
# ─────────────────────────────────────────────
with col_tools:
    st.markdown("### 📊 Actividad del agente")

    total_messages = len([m for m in st.session_state.messages if m["role"] == "human"])
    total_tools = sum(len(v) for v in st.session_state.tool_history.values())

    col_a, col_b = st.columns(2)
    with col_a:
        st.metric("Consultas", total_messages)
    with col_b:
        st.metric("Tools usadas", total_tools)

    if st.session_state.tool_history:
        st.markdown("#### Últimas herramientas")
        all_tools_used = []
        for tools in st.session_state.tool_history.values():
            all_tools_used.extend([t["tool"] for t in tools])

        # Contar uso de cada tool
        tool_counts = {}
        for t in all_tools_used:
            tool_counts[t] = tool_counts.get(t, 0) + 1

        for tool_name, count in sorted(tool_counts.items(), key=lambda x: -x[1]):
            icon = (
                "⚡"
                if "session" in tool_name
                or "pit" in tool_name
                or "lap" in tool_name
                or "weather" in tool_name
                or "position" in tool_name
                or "driver_in" in tool_name
                else (
                    "📊"
                    if "standing" in tool_name
                    or "result" in tool_name
                    or "schedule" in tool_name
                    or "career" in tool_name
                    or "qualifying" in tool_name
                    else "🧠"
                )
            )
            st.markdown(f"{icon} `{tool_name}` × {count}")

    st.divider()
    st.markdown("#### 🔗 APIs conectadas")
    st.markdown("""
    - **OpenF1** — tiempo real
    - **Jolpica/Ergast** — histórico
    - **ChromaDB** — RAG local
    """)

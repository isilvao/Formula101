"""
Grafo LangGraph del Agente Formula 101.
Agente ReAct con streaming de respuesta y captura de tool calls.
"""

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.prebuilt import create_react_agent
from langchain_core.messages import HumanMessage, AIMessage

from agent.tools import ALL_TOOLS
from agent.prompts import SYSTEM_PROMPT

load_dotenv()


# ── LLM + agente ─────────────────────────────────────────────────────────────

def build_agent():
    llm = ChatGoogleGenerativeAI(
        model="gemini-3.1-flash-lite",
        temperature=0,
        max_tokens=8192,
    )
    return create_react_agent(model=llm, tools=ALL_TOOLS, prompt=SYSTEM_PROMPT)


_agent = None

def get_agent():
    global _agent
    if _agent is None:
        _agent = build_agent()
    return _agent


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_text(content) -> str:
    """Extrae texto de un contenido que puede ser str o lista de bloques."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            b if isinstance(b, str) else b.get("text", "")
            for b in content
        ).strip()
    return str(content) if content else ""


def _build_messages(user_message: str, history: list) -> list:
    msgs = []
    for m in (history or []):
        if m["role"] == "human":
            msgs.append(HumanMessage(content=m["content"]))
        elif m["role"] == "assistant":
            msgs.append(AIMessage(content=m["content"]))
    msgs.append(HumanMessage(content=user_message))
    return msgs


# ── AgentStream: iterable que hace streaming + captura tool calls ─────────────

class AgentStream:
    """
    Iterable que hace streaming de los tokens de texto del agente.
    Mientras se consume, acumula las herramientas que el agente usó en self.tool_calls.

    Uso en Streamlit:
        stream = AgentStream(user_input, history)
        for chunk in stream:
            ...  # mostrar chunk
        tool_calls = stream.tool_calls
    """

    def __init__(self, user_message: str, history: list = None):
        self.tool_calls: list[dict] = []
        self._user_message = user_message
        self._history = history or []

    def __iter__(self):
        agent    = get_agent()
        messages = _build_messages(self._user_message, self._history)
        seen_tool_ids: set = set()

        for chunk, _ in agent.stream(
            {"messages": messages},
            stream_mode="messages",
            config={"recursion_limit": 10},
        ):
            # ── Capturar tool calls completos (AIMessage con tool_calls) ──────
            complete_tc = getattr(chunk, "tool_calls", None)
            if complete_tc:
                for tc in complete_tc:
                    tid = tc.get("id", tc.get("name", ""))
                    if tid and tid not in seen_tool_ids:
                        seen_tool_ids.add(tid)
                        self.tool_calls.append({
                            "tool":  tc["name"],
                            "input": tc.get("args", {}),
                        })

            # ── Capturar tool calls parciales (streaming chunks) ──────────────
            partial_tc = getattr(chunk, "tool_call_chunks", None)
            if partial_tc:
                for tc in partial_tc:
                    name = tc.get("name", "")
                    tid  = tc.get("id", name)
                    if name and tid and tid not in seen_tool_ids:
                        seen_tool_ids.add(tid)
                        self.tool_calls.append({"tool": name, "input": {}})

            # ── Yield texto de la respuesta final ─────────────────────────────
            is_ai_chunk = chunk.__class__.__name__ == "AIMessageChunk"
            has_tc      = bool(complete_tc or partial_tc)
            if is_ai_chunk and not has_tc:
                text = _extract_text(chunk.content)
                if text:
                    yield text


# ── invoke_agent: versión no-streaming (mantener para compatibilidad) ─────────

def invoke_agent(user_message: str, history: list = None) -> dict:
    """Invoca el agente y retorna {'answer', 'tool_calls', 'messages'}."""
    agent    = get_agent()
    messages = _build_messages(user_message, history)
    result   = agent.invoke({"messages": messages}, config={"recursion_limit": 10})

    all_messages    = result["messages"]
    final_answer    = ""
    tool_calls_info = []

    for msg in all_messages:
        tc = getattr(msg, "tool_calls", None)
        if tc:
            for t in tc:
                tool_calls_info.append({"tool": t["name"], "input": t.get("args", {})})
        if msg.__class__.__name__ == "AIMessage" and not tc:
            text = _extract_text(msg.content)
            if text:
                final_answer = text

    return {"answer": final_answer, "tool_calls": tool_calls_info, "messages": all_messages}

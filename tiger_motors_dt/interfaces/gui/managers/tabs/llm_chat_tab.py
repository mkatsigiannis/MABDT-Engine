"""AI Assistant tab: hosts the LLMChatWidget when ollama is available."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from tiger_motors_dt.widgets import LLM_AVAILABLE

if LLM_AVAILABLE:
    from tiger_motors_dt.widgets import LLMChatWidget


def build(main_window) -> QWidget:
    """Return the LLMChatWidget, or an install-instructions placeholder."""
    if not LLM_AVAILABLE:
        placeholder = QWidget()
        layout = QVBoxLayout(placeholder)
        label = QLabel(
            "LLM Chat is not available.\n\n"
            "To enable AI Assistant features:\n"
            "1. Install Ollama from https://ollama.com\n"
            "2. Install the ollama Python package: pip install ollama\n"
            "3. Restart the application"
        )
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = QFont()
        font.setPointSize(12)
        label.setFont(font)
        layout.addWidget(label)
        main_window.llm_chat_widget = None
        return placeholder

    main_window.llm_chat_widget = LLMChatWidget()
    return main_window.llm_chat_widget

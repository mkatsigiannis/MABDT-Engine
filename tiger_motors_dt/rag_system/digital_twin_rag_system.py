"""RAG context builder for the LLM service.

Pipes a fresh snapshot of the Digital Twin (workstation states, active
cars, production metrics) through formatter and builder stages to
produce the system-state preamble injected into each LLM prompt.
"""

from datetime import datetime
from typing import Any

from mabdt.utils.logging import get_logger

from .digital_twin_context_builder import DigitalTwinContextBuilder
from .digital_twin_context_formatter import DigitalTwinContextFormatter
from .digital_twin_data_collector import DigitalTwinDataCollector

logger = get_logger(__name__)


class DigitalTwinRAGSystem:
    """Three-stage RAG pipeline: collect → format → build the LLM context block."""

    def __init__(self, environment=None):
        """
        Initialize the RAG system.

        Args:
            environment: TigerMotorsEnvironment instance (optional)
        """
        self.collector = DigitalTwinDataCollector(environment)
        self.formatter = DigitalTwinContextFormatter()
        self.builder = DigitalTwinContextBuilder()
        self.last_context_update = None
        self.cached_context = None
        self.cache_duration_seconds = 30  # Cache context for 30 seconds

    def set_environment(self, environment):
        """Set or update the environment reference."""
        self.collector.set_environment(environment)
        # Clear cache when environment changes
        self.cached_context = None
        self.last_context_update = None

    def is_data_available(self) -> bool:
        """Check if Digital Twin data is available for context enhancement."""
        try:
            return self.collector.is_environment_available()
        except Exception as e:
            logger.error(f"[RAG System] Error checking data availability: {e}")
            return False

    def get_current_context(self, force_refresh: bool = False) -> str | None:
        """
        Get current Digital Twin context for LLM prompts.

        Args:
            force_refresh: Force refresh of cached context

        Returns:
            Natural language context string or None if no data available
        """
        # Check if we should use cached context
        if (
            not force_refresh
            and self.cached_context
            and self.last_context_update
            and (datetime.now().timestamp() - self.last_context_update)
            < self.cache_duration_seconds
        ):
            return self.cached_context

        try:
            # Collect fresh data
            raw_data = self.collector.collect_all_data()

            # Format the data
            formatted_data = self.formatter.format_comprehensive_summary(raw_data)

            # Build natural language context
            context = self.builder.build_comprehensive_context(formatted_data)

            # Cache the result
            self.cached_context = context
            self.last_context_update = datetime.now().timestamp()

            return context

        except Exception as e:
            logger.error(f"[RAG System] Error generating context: {e}")
            return None

    def get_focused_context(
        self, focus_area: str = "overview", force_refresh: bool = False
    ) -> str | None:
        """
        Get focused Digital Twin context for specific areas.

        Args:
            focus_area: Area to focus on ("overview", "workstations", "vehicles", "quality", "performance")
            force_refresh: Force refresh of data

        Returns:
            Focused natural language context string
        """
        try:
            # Always collect fresh data for focused requests
            raw_data = self.collector.collect_all_data()
            formatted_data = self.formatter.format_comprehensive_summary(raw_data)

            # Build focused context
            context = self.builder.build_focused_context(formatted_data, focus_area)

            return context

        except Exception as e:
            logger.error(f"[RAG System] Error generating focused context: {e}")
            return None

    def enhance_prompt(
        self, user_question: str, include_context: bool = True, focus_area: str = "overview"
    ) -> str:
        """
        Enhance a user question with Digital Twin context.

        Args:
            user_question: Original user question
            include_context: Whether to include Digital Twin context
            focus_area: Context focus area if specific context needed

        Returns:
            Enhanced prompt with context
        """
        if not include_context or not self.is_data_available():
            return user_question

        # Get appropriate context
        if focus_area == "overview":
            context = self.get_current_context()
        else:
            context = self.get_focused_context(focus_area)

        if not context:
            return user_question

        # Create enhanced prompt
        enhanced_prompt = self._build_enhanced_prompt(user_question, context)

        return enhanced_prompt

    def _build_enhanced_prompt(self, user_question: str, context: str) -> str:
        """
        Build the enhanced prompt with context and instructions.

        Args:
            user_question: Original user question
            context: Digital Twin context

        Returns:
            Complete enhanced prompt
        """
        prompt_template = """You are an AI assistant for the Tiger Motors Digital Twin production system. You have access to real-time data about the production line status, workstations, vehicles, and quality metrics.

CURRENT SYSTEM STATUS:
{context}

USER QUESTION: {question}

Please provide a helpful response based on the current system status shown above. If the question is related to production, quality, workstations, or vehicles, reference specific data from the status. If you notice any issues or anomalies in the data, please highlight them in your response.

If the question is not related to the production system, you can still answer it normally, but mention if there are any production issues that might need attention."""

        return prompt_template.format(context=context, question=user_question)

    def get_status_summary(self) -> str:
        """
        Get a brief status summary for display purposes.

        Returns:
            Brief status summary
        """
        try:
            if not self.is_data_available():
                return "No Digital Twin data available"

            raw_data = self.collector.collect_all_data()
            formatted_data = self.formatter.format_comprehensive_summary(raw_data)

            return self.builder.get_context_summary_stats(formatted_data)

        except Exception as e:
            return f"Error: {e}"

    def get_context_metadata(self) -> dict[str, Any]:
        """
        Get metadata about the current context for debugging/monitoring.

        Returns:
            Dictionary with context metadata
        """
        metadata = {
            "data_available": self.is_data_available(),
            "cache_valid": False,
            "last_update": self.last_context_update,
            "cache_age_seconds": None,
            "summary": "No data",
        }

        if self.last_context_update:
            cache_age = datetime.now().timestamp() - self.last_context_update
            metadata["cache_age_seconds"] = cache_age
            metadata["cache_valid"] = cache_age < self.cache_duration_seconds

        if self.is_data_available():
            metadata["summary"] = self.get_status_summary()

        return metadata

    def should_include_context(self, user_question: str) -> tuple[bool, str]:
        """
        Determine if context should be included based on the user question.

        Args:
            user_question: User's question

        Returns:
            Tuple of (should_include, focus_area)
        """
        question_lower = user_question.lower()

        # Keywords that suggest production-related questions
        production_keywords = [
            "workstation",
            "production",
            "vehicle",
            "car",
            "fault",
            "quality",
            "status",
            "system",
            "andon",
            "busy",
            "idle",
            "red",
            "yellow",
            "green",
            "takt",
            "cycle",
            "time",
            "performance",
            "assembly",
            "inspection",
            "performing",
            "metrics",
            "finished",
            "completed",  # Added finished/completed
        ]

        # Keywords for specific focus areas with improved logic
        workstation_keywords = ["workstation", "ws", "andon", "idle", "busy"]

        # Enhanced vehicle keywords to include finished/completed states
        vehicle_keywords = [
            "vehicle",
            "car",
            "suv",
            "speedster",
            "assembly",
            "finished",
            "completed",
            "done",
            "finished car",
            "completed car",
            "how many car",
            "how many vehicle",
            "car status",
            "vehicle status",
        ]

        quality_keywords = ["fault", "quality", "defect", "error", "inspection"]
        performance_keywords = [
            "performance",
            "efficiency",
            "utilization",
            "takt",
            "cycle",
            "performing",
            "metrics",
        ]

        # Check if question is production-related
        is_production_related = any(keyword in question_lower for keyword in production_keywords)

        if not is_production_related:
            return False, "overview"

        # Enhanced focus area detection with priority logic

        # First, check for finished/completed car questions - these should be vehicle-focused
        finished_car_patterns = [
            "finished car",
            "completed car",
            "finished vehicle",
            "completed vehicle",
            "how many finished",
            "how many completed",
            "do we have finished",
            "do we have completed",
        ]

        if any(pattern in question_lower for pattern in finished_car_patterns):
            return True, "vehicles"

        # Then check other specific areas
        if any(keyword in question_lower for keyword in workstation_keywords):
            return True, "workstations"
        elif any(keyword in question_lower for keyword in performance_keywords):
            return True, "performance"
        elif any(keyword in question_lower for keyword in vehicle_keywords):
            return True, "vehicles"
        elif any(keyword in question_lower for keyword in quality_keywords):
            # Only categorize as quality if not already caught by vehicle patterns
            return True, "quality"
        else:
            return True, "overview"

    def process_question(
        self, user_question: str, auto_detect_context: bool = True
    ) -> dict[str, Any]:
        """
        Process a user question and return enhanced prompt with metadata.

        Args:
            user_question: Original user question
            auto_detect_context: Automatically detect if context is needed

        Returns:
            Dictionary with enhanced prompt and metadata
        """
        result = {
            "original_question": user_question,
            "enhanced_prompt": user_question,
            "context_included": False,
            "focus_area": "overview",
            "context_available": self.is_data_available(),
            "metadata": self.get_context_metadata(),
        }

        if auto_detect_context:
            should_include, focus_area = self.should_include_context(user_question)
            result["context_included"] = should_include
            result["focus_area"] = focus_area

            if should_include and self.is_data_available():
                enhanced_prompt = self.enhance_prompt(user_question, True, focus_area)
                result["enhanced_prompt"] = enhanced_prompt

        return result

    def clear_cache(self):
        """Clear the cached context to force fresh data collection."""
        self.cached_context = None
        self.last_context_update = None

    def set_cache_duration(self, seconds: int):
        """Set the cache duration in seconds."""
        self.cache_duration_seconds = max(1, seconds)  # Minimum 1 second

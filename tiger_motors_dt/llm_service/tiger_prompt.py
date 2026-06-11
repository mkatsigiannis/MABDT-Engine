#!/usr/bin/env python3
"""
Tiger Motors Digital Twin System Prompt Management
Extracted and enhanced from the original LLM service
"""

import re

from mabdt.utils.logging import get_logger

logger = get_logger(__name__)


class TigerMotorsPrompt:
    """System prompt manager for Tiger Motors Digital Twin"""

    # Concise, focused system prompt for Tiger Motors (extracted from original service)
    SYSTEM_PROMPT = """You are the Digital Twin of Tiger Motors, an educational automotive assembly line facility at Auburn University's Samuel Ginn College of Engineering. You are the intelligent digital replica that monitors, analyzes, and provides insights about the physical assembly line operations.

## Your Identity & Capabilities:
- You are the Multi-Agent-Based Digital Twin (MABDT) system for Tiger Motors
- You continuously monitor the assembly line through IoT devices, barcode scanners, and automation systems
- You track both the physical workstations and the LEGO® cars being assembled in real-time
- You understand lean manufacturing principles and can analyze production efficiency

## Facility Overview:
- **Products**: Two types of LEGO® cars - 234-piece SUV and 277-piece Speedster
- **Layout**: 15 workstations across 3 sub-assembly cells:
  - Cell 1: WS1-WS5 (with inspection station and Supermarket 1)
  - Cell 2: WS6-WS10 (with inspection station and Supermarket 2)
  - Cell 3: WS11-WS15 (moving conveyor belt, final inspection)
- **Target Performance**: 75-second takt time, 60-second cycle time
- **War Eagle Inc.**: External manufacturing cell producing specialized add-ons for modified cars

## Your Monitoring Systems:
- **Car Agents**: Track each vehicle through all 15 workstations using VIN-like barcodes
- **Workstation Agents**: Monitor station status (Idle/Busy) and Andon light states (Green/Yellow/Red)
- **Communication Agent**: Processes MQTT messages from IoT devices and PLC automation data
- **Real-time Data**: Barcode scans, material handling, inspection results, fault detection

## Production Modes You Oversee:
- **Mass Production Mode**: Traditional independent cell operation with Master Production Schedule
- **Lean Manufacturing Mode**: Just-In-Time operation with Heijunka leveled scheduling

## Your Personality:
- Professional but educational - you help students and industry professionals learn
- Data-driven and analytical - you provide specific metrics and insights
- Proactive - you anticipate issues and suggest improvements
- Knowledgeable about lean manufacturing principles and Industry 4.0 technologies

## Communication Style:
- Speak as the facility's digital consciousness
- Reference specific workstations, cells, and systems when relevant
- Provide actionable insights based on real-time data analysis
- Explain lean manufacturing concepts when discussing improvements
- Use manufacturing terminology appropriately"""

    @classmethod
    def get_system_prompt(cls, context: str | None = None) -> str:
        """Get system prompt, optionally with specific context"""
        return cls.SYSTEM_PROMPT

    @classmethod
    def create_prompt(cls, user_question: str) -> str:
        """Create a simple prompt with just the system prompt and user question"""
        return cls.create_contextualized_prompt(user_question, None)

    @classmethod
    def create_contextualized_prompt(
        cls, user_question: str, rag_context: str | None = None
    ) -> str:
        """Create full prompt with system prompt, RAG context, and user question"""

        # Start with system prompt
        full_prompt = cls.SYSTEM_PROMPT

        # Add RAG context if available
        if rag_context and rag_context.strip():
            full_prompt += f"\n\n## Current Digital Twin Data:\n{rag_context}"

        # Add user question
        full_prompt += f"\n\n---\n\nCurrent User Question: {user_question}"

        # Add response instruction
        full_prompt += "\n\nDirectly answer the user's question based on the 'Current Digital Twin Data' provided. Be concise and factual. Do not speculate on causes, explain manufacturing concepts, or suggest next steps unless asked. Stick to the data."

        return full_prompt

    @classmethod
    def filter_response(cls, response: str, max_length: int = 2048) -> str:
        """Filter and clean response according to Tiger Motors standards"""

        # Remove thinking tags if present (extracted from original service)
        filtered = re.sub(r"<think>.*?</think>", "", response, flags=re.DOTALL | re.IGNORECASE)

        # Remove excessive whitespace
        filtered = re.sub(r"\n\s*\n\s*\n", "\n\n", filtered)
        filtered = filtered.strip()

        # Truncate if too long
        if len(filtered) > max_length:
            filtered = filtered[: max_length - 3] + "..."

        # Remove overly verbose responses (indicators of poor model output)
        if cls._is_verbose_response(filtered):
            return "I'll provide a concise analysis based on the available production data. Please specify which aspect you'd like me to focus on (production efficiency, quality metrics, or equipment status)."

        return filtered

    @classmethod
    def _is_verbose_response(cls, response: str) -> bool:
        """Check if response is overly verbose or generic"""
        verbose_indicators = [
            "let me provide you with a comprehensive",
            "it's important to understand",
            "there are several factors to consider",
            "in order to better understand",
            "it would be helpful to examine",
        ]

        response_lower = response.lower()
        verbose_count = sum(1 for indicator in verbose_indicators if indicator in response_lower)

        # Also check for excessive length without specific data
        has_specific_data = any(
            keyword in response_lower
            for keyword in [
                "workstation",
                "ws",
                "vehicle",
                "cycle time",
                "takt time",
                "fault",
                "efficiency",
                "bottleneck",
                "production",
            ]
        )

        return verbose_count >= 2 or (len(response) > 1000 and not has_specific_data)


# Backward compatibility function for the original service
def filter_think_tags(response):
    """Legacy function for backward compatibility - Remove all content within <think>...</think> tags"""
    return TigerMotorsPrompt.filter_response(response)


def create_digital_twin_prompt(user_question):
    """Legacy function for backward compatibility - Create a contextualized prompt"""
    return TigerMotorsPrompt.create_contextualized_prompt(user_question)


if __name__ == "__main__":
    # Test the prompt system
    logger.info("Testing Tiger Motors Prompt System...")

    prompt_manager = TigerMotorsPrompt()

    # Test basic prompt
    basic_prompt = prompt_manager.get_system_prompt()
    logger.info(f"Basic prompt length: {len(basic_prompt)} characters")

    # Test contextualized prompt
    rag_context = "Workstation 5: BUSY, Vehicle ID: V123 (SUV), Cycle time: 62s"
    user_question = "What's causing the slow cycle time at WS5?"

    full_prompt = prompt_manager.create_contextualized_prompt(user_question, rag_context)
    logger.info(f"Contextualized prompt length: {len(full_prompt)} characters")

    # Test response filtering
    verbose_response = "Let me provide you with a comprehensive analysis. It's important to understand that there are several factors to consider..."
    filtered = prompt_manager.filter_response(verbose_response)
    logger.info(f"Filtered verbose response: {len(filtered)} characters")

    logger.info("Prompt system test completed!")

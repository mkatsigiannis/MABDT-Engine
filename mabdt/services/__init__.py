"""Independent services that run alongside the engine.

Maps to the JIM paper's "Independent Services" subsection. A service is anything that connects
to the same broker as the CommunicationAgent but lives outside the engine's
simulation lifecycle: barcode loggers, OPC UA bridges, RAG/LLM clients, etc.
"""

from mabdt.services.base import IndependentService

__all__ = ["IndependentService"]

"""Tiger Motors topic processors.

Three TopicProcessor subclasses that implement the deployment-specific
routing rules described in JIM §3.2's algorithm and Table for the Tiger
Motors deployment:

  - BarcodeProcessor:   scanner/+         (workstation barcode scans)
  - PLCProcessor:       plc/#             (Andon light updates)
  - InspectionProcessor: scanner/InspectionStation
                                          (inspection station scans)

Each processor receives the TigerMotorsEnvironment as its `context` argument
and dispatches events to the appropriate agent(s) within the environment.
"""

from tiger_motors_dt.agents.processors.barcode_processor import BarcodeProcessor
from tiger_motors_dt.agents.processors.inspection_processor import InspectionProcessor
from tiger_motors_dt.agents.processors.plc_processor import PLCProcessor

__all__ = ["BarcodeProcessor", "InspectionProcessor", "PLCProcessor"]

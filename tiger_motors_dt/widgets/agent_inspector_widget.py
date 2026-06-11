"""Runtime agent inspector widget.

Debug-only panel that resolves agents through the SimulationInterface's
named `debug_list_agent_ids` / `debug_get_agent` methods, then introspects
the live Agent's attributes and state machine for display. Modeled on
AnyLogic's runtime inspector.
"""

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mabdt.utils.logging import get_logger

logger = get_logger(__name__)


class AgentInspectorWidget(QWidget):
    """Read-only widget showing the live attributes and state of a selected agent."""

    # Signal emitted when user selects a different agent
    agent_selected = Signal(str, str)  # agent_type, agent_id

    def __init__(self, parent=None):
        """Initialize the agent inspector widget."""
        super().__init__(parent)

        # Current selection state
        self.current_agent_type = None
        self.current_agent_id = None
        self.current_agent = None

        # SimulationInterface reference (set by the display manager once
        # the simulation has initialized). The inspector uses the
        # interface's `debug_*` methods rather than reaching into the
        # environment directly.
        self.iface = None

        self.setup_ui()

    def setup_ui(self):
        """Create and arrange all UI components."""
        layout = QVBoxLayout()

        # Agent selection section
        selection_group = self._create_selection_section()
        layout.addWidget(selection_group)

        # Create splitter for resizable sections
        splitter = QSplitter(Qt.Vertical)

        # Current state and variables section
        state_vars_group = self._create_state_variables_section()
        splitter.addWidget(state_vars_group)

        # State machine hierarchy section
        state_machine_group = self._create_state_machine_section()
        splitter.addWidget(state_machine_group)

        # Set initial splitter sizes (roughly equal)
        splitter.setSizes([300, 300])

        layout.addWidget(splitter)

        self.setLayout(layout)

    def _create_selection_section(self) -> QGroupBox:
        """Create the agent selection controls."""
        group = QGroupBox("Agent Selection")
        layout = QHBoxLayout()

        # Agent type selector
        type_label = QLabel("Agent Type:")
        self.agent_type_combo = QComboBox()
        self.agent_type_combo.addItems(["Workstation Agents", "Car Agents", "Inspection Station"])
        self.agent_type_combo.currentTextChanged.connect(self._on_agent_type_changed)

        # Specific agent selector
        agent_label = QLabel("Agent ID:")
        self.agent_id_combo = QComboBox()
        self.agent_id_combo.currentTextChanged.connect(self._on_agent_id_changed)

        layout.addWidget(type_label)
        layout.addWidget(self.agent_type_combo, 1)
        layout.addWidget(agent_label)
        layout.addWidget(self.agent_id_combo, 1)
        layout.addStretch()

        group.setLayout(layout)
        return group

    def _create_state_variables_section(self) -> QGroupBox:
        """Create the current state and variables display."""
        group = QGroupBox("Agent State & Variables")
        layout = QVBoxLayout()

        # Current state display - prominent
        state_frame = QFrame()
        state_frame.setFrameStyle(QFrame.Box | QFrame.Raised)
        state_layout = QHBoxLayout()

        state_title = QLabel("Current State:")
        state_title.setFont(QFont("Arial", 10, QFont.Bold))

        self.current_state_label = QLabel("No agent selected")
        self.current_state_label.setFont(QFont("Arial", 12, QFont.Bold))
        self.current_state_label.setStyleSheet("color: #2196F3; padding: 5px;")

        state_layout.addWidget(state_title)
        state_layout.addWidget(self.current_state_label)
        state_layout.addStretch()
        state_frame.setLayout(state_layout)

        layout.addWidget(state_frame)

        # Variables table
        self.variables_table = QTableWidget()
        self.variables_table.setColumnCount(2)
        self.variables_table.setHorizontalHeaderLabels(["Attribute", "Value"])
        self.variables_table.horizontalHeader().setStretchLastSection(True)
        self.variables_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeToContents
        )
        self.variables_table.setAlternatingRowColors(True)

        layout.addWidget(self.variables_table)

        group.setLayout(layout)
        return group

    def _create_state_machine_section(self) -> QGroupBox:
        """Create the state machine hierarchy visualization."""
        group = QGroupBox("State Machine Hierarchy")
        layout = QVBoxLayout()

        # State machine tree
        self.state_tree = QTreeWidget()
        self.state_tree.setHeaderLabels(["State", "Type", "Info"])
        self.state_tree.setAlternatingRowColors(True)
        self.state_tree.setColumnWidth(0, 250)

        layout.addWidget(self.state_tree)

        group.setLayout(layout)
        return group

    def _on_agent_type_changed(self, agent_type: str):
        """Handle agent type selection change."""
        self.current_agent_type = agent_type
        self._update_agent_id_list()

    def _on_agent_id_changed(self, agent_id: str):
        """Handle specific agent selection change."""
        if agent_id:
            self.current_agent_id = agent_id
            self._load_agent()
            self.agent_selected.emit(self.current_agent_type, agent_id)

    def _update_agent_id_list(self):
        """Update the agent ID dropdown based on selected type."""
        self.agent_id_combo.clear()

        if self.iface is None or not self.current_agent_type:
            return

        try:
            self.agent_id_combo.addItems(self.iface.debug_list_agent_ids(self.current_agent_type))
        except Exception as e:
            logger.error(f"Error updating agent ID list: {e}")

    def _load_agent(self):
        """Load the selected agent and display its information."""
        if self.iface is None or not self.current_agent_id:
            self.current_agent = None
            return

        try:
            self.current_agent = self.iface.debug_get_agent(
                self.current_agent_type, self.current_agent_id
            )
            self._update_displays()
        except Exception as e:
            logger.error(f"Error loading agent: {e}")
            self.current_agent = None

    def _update_displays(self):
        """Update all display sections with current agent data."""
        if not self.current_agent:
            self._clear_displays()
            return

        try:
            self._update_state_display()
            self._update_variables_table()
            self._update_state_machine_tree()
        except Exception as e:
            logger.error(f"Error updating displays: {e}")

    def _clear_displays(self):
        """Clear all display sections."""
        self.current_state_label.setText("No agent selected")
        self.variables_table.setRowCount(0)
        self.state_tree.clear()

    def _update_state_display(self):
        """Update the current state display."""
        if hasattr(self.current_agent, "state"):
            state = self.current_agent.state
            self.current_state_label.setText(state)

            # Color code based on state type (for workstations)
            if "Green" in state or "Idle" in state:
                self.current_state_label.setStyleSheet(
                    "color: #4CAF50; padding: 5px; font-weight: bold;"
                )
            elif "Yellow" in state:
                self.current_state_label.setStyleSheet(
                    "color: #FFC107; padding: 5px; font-weight: bold;"
                )
            elif "Red" in state:
                self.current_state_label.setStyleSheet(
                    "color: #F44336; padding: 5px; font-weight: bold;"
                )
            elif "Busy" in state:
                self.current_state_label.setStyleSheet(
                    "color: #2196F3; padding: 5px; font-weight: bold;"
                )
            else:
                self.current_state_label.setStyleSheet(
                    "color: #2196F3; padding: 5px; font-weight: bold;"
                )
        else:
            self.current_state_label.setText("State not available")

    def _update_variables_table(self):
        """Update the variables table with all agent attributes."""
        self.variables_table.setRowCount(0)

        if not self.current_agent:
            return

        # Get all attributes
        attributes = vars(self.current_agent)

        # Filter and sort attributes (public first, then private)
        public_attrs = sorted([(k, v) for k, v in attributes.items() if not k.startswith("_")])
        private_attrs = sorted([(k, v) for k, v in attributes.items() if k.startswith("_")])

        all_attrs = public_attrs + private_attrs

        # Populate table
        for attr_name, attr_value in all_attrs:
            row = self.variables_table.rowCount()
            self.variables_table.insertRow(row)

            # Attribute name
            name_item = QTableWidgetItem(attr_name)
            if attr_name.startswith("_"):
                name_item.setForeground(QColor(150, 150, 150))  # Gray for private
            else:
                name_item.setFont(QFont("Arial", 9, QFont.Bold))

            self.variables_table.setItem(row, 0, name_item)

            # Attribute value (formatted)
            value_str = self._format_value(attr_value)
            value_item = QTableWidgetItem(value_str)
            value_item.setFlags(value_item.flags() & ~Qt.ItemIsEditable)  # Read-only

            self.variables_table.setItem(row, 1, value_item)

    def _format_value(self, value: Any) -> str:
        """Format a value for display in the table."""
        try:
            # Handle special types
            if value is None:
                return "None"
            elif isinstance(value, bool):
                return str(value)
            elif isinstance(value, (int, float)):
                if isinstance(value, float):
                    return f"{value:.4f}"
                return str(value)
            elif isinstance(value, str):
                return value if len(value) < 100 else value[:97] + "..."
            elif isinstance(value, (list, tuple)):
                return f"[{len(value)} items]" if len(value) > 5 else str(value)
            elif isinstance(value, dict):
                return f"{{dict: {len(value)} items}}"
            elif hasattr(value, "__class__"):
                # For objects, show class name
                return f"<{value.__class__.__name__}>"
            else:
                return str(value)
        except Exception:
            return "<error formatting value>"

    def _update_state_machine_tree(self):
        """Update the state machine hierarchy tree."""
        self.state_tree.clear()

        if not self.current_agent or not hasattr(self.current_agent, "machine"):
            no_sm_item = QTreeWidgetItem(["No state machine available", "", ""])
            self.state_tree.addTopLevelItem(no_sm_item)
            return

        machine = self.current_agent.machine
        current_state = self.current_agent.state if hasattr(self.current_agent, "state") else None

        # Build state hierarchy
        try:
            # Get all states from the machine
            states = machine.states

            # Create a mapping of states
            state_items = {}
            root_states = []

            for state_name, state_obj in states.items():
                # Create tree item for this state
                is_current = state_name == current_state

                # Determine state type
                is_initial = state_name == machine.initial
                has_children = hasattr(state_obj, "states") and state_obj.states

                state_type = []
                if is_initial:
                    state_type.append("initial")
                if has_children:
                    state_type.append("composite")

                type_str = ", ".join(state_type) if state_type else "simple"

                # Create the tree item
                item = QTreeWidgetItem([state_name, type_str, ""])

                # Highlight current state
                if is_current:
                    font = item.font(0)
                    font.setBold(True)
                    item.setFont(0, font)
                    item.setForeground(0, QColor(33, 150, 243))  # Blue
                    item.setText(2, "← CURRENT")
                    item.setForeground(2, QColor(33, 150, 243))

                state_items[state_name] = item

                # Determine if this is a root state or child state
                if "." not in state_name and "_" not in state_name:
                    root_states.append(state_name)
                elif "_" in state_name:
                    # Hierarchical state (e.g., Production_GreenAndon_Idle)
                    parts = state_name.split("_")
                    if len(parts) > 1:
                        parent_name = "_".join(parts[:-1])
                        if parent_name in state_items:
                            state_items[parent_name].addChild(item)
                        else:
                            root_states.append(state_name)
                    else:
                        root_states.append(state_name)
                else:
                    root_states.append(state_name)

            # Add root states to tree
            for state_name in sorted(root_states):
                if state_name in state_items:
                    self.state_tree.addTopLevelItem(state_items[state_name])

            # Expand all items to show hierarchy
            self.state_tree.expandAll()

        except Exception as e:
            error_item = QTreeWidgetItem([f"Error loading state machine: {e}", "", ""])
            self.state_tree.addTopLevelItem(error_item)

    def set_interface(self, iface):
        """Bind the inspector to a SimulationInterface for `debug_*` lookups."""
        self.iface = iface
        self._update_agent_id_list()

    def refresh(self):
        """Refresh the display with current agent data."""
        if self.current_agent:
            self._update_displays()

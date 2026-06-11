# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller Specification — Tiger Motors Digital Twin
=====================================================

Builds a standalone Windows folder distribution for the Tiger Motors
Digital Twin GUI application.

Build (run from repo root, or call scripts\windows_build\build_standalone.bat):
    pyinstaller scripts/windows_build/TigerMotorsDT.spec --clean --noconfirm

Output:
    dist/TigerMotorsDT/        Portable application folder
    dist/TigerMotorsDT/TigerMotorsDT.exe   Entry-point launcher (gui_main.py)

This spec lives in scripts/windows_build/ but resolves every source path
against the repo root (`repo_root` below), so it works regardless of the
working directory PyInstaller is invoked from.
"""

import os
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

block_cipher = None

# Spec lives in <repo_root>/scripts/windows_build/. Anchor every source
# path to the repo root so the spec is invocation-directory-independent.
spec_root = os.path.abspath(SPECPATH)
repo_root = os.path.abspath(os.path.join(spec_root, os.pardir, os.pardir))

pyside6_datas = collect_data_files('PySide6')
pyside6_binaries = collect_dynamic_libs('PySide6')

# ==============================================================================
# DATA FILES — config + runtime asset folders
# ==============================================================================
#
# config.json is gitignored but expected to exist locally for the build;
# the user edits it post-install to point at their broker. Same for the
# LLM service config. Templates ship alongside.
#
datas = [
    (os.path.join(repo_root, 'config.json'), '.'),
    (os.path.join(repo_root, 'config_template.json'), '.'),
    (os.path.join(repo_root, 'tiger_motors_dt', 'llm_service', 'llm_service_config.json'), 'llm_service'),
    (os.path.join(repo_root, 'tiger_motors_dt', 'llm_service', 'llm_service_config_template.json'), 'llm_service'),
    (os.path.join(repo_root, 'diagrams_and_data'), 'diagrams_and_data'),
]
datas += pyside6_datas

# ==============================================================================
# HIDDEN IMPORTS — modules PyInstaller's static analysis can miss
# ==============================================================================
hiddenimports = [
    # ---- mabdt engine package ----
    'mabdt',
    'mabdt.agent',
    'mabdt.agent.base',
    'mabdt.agent.statemachine',
    'mabdt.communication_kernel',
    'mabdt.communication_kernel.communication_agent',
    'mabdt.communication_kernel.event_bus',
    'mabdt.communication_kernel.processor',
    'mabdt.communication_kernel.protocol',
    'mabdt.simulation_environment',
    'mabdt.simulation_environment.environment',
    'mabdt.simulation_environment.population',
    'mabdt.simulation_environment.factory',
    'mabdt.interface_layer',
    'mabdt.interface_layer.simulation_interface',
    'mabdt.interface_layer.dto',
    'mabdt.interface_layer.query',
    'mabdt.services',
    'mabdt.services.base',
    'mabdt.utils',
    'mabdt.utils.logging',
    'mabdt.utils.config',
    'mabdt.protocols',
    'mabdt.exceptions',

    # ---- tiger_motors_dt deployment package ----
    'tiger_motors_dt',
    'tiger_motors_dt.config',
    'tiger_motors_dt.topic_helper',

    # Agents
    'tiger_motors_dt.agents',
    'tiger_motors_dt.agents.car_agent',
    'tiger_motors_dt.agents.comm_agent',
    'tiger_motors_dt.agents.is_agent',
    'tiger_motors_dt.agents.ws_agent',
    'tiger_motors_dt.agents.processors',
    'tiger_motors_dt.agents.processors._base',
    'tiger_motors_dt.agents.processors.barcode_processor',
    'tiger_motors_dt.agents.processors.plc_processor',
    'tiger_motors_dt.agents.processors.inspection_processor',

    # Simulation
    'tiger_motors_dt.simulation',
    'tiger_motors_dt.simulation.environment',
    'tiger_motors_dt.simulation.interface',
    'tiger_motors_dt.simulation.factory',
    'tiger_motors_dt.simulation.dto',
    'tiger_motors_dt.simulation.converters',
    'tiger_motors_dt.simulation.converters.dto_converters',
    'tiger_motors_dt.simulation.queries',
    'tiger_motors_dt.simulation.queries.workstation_queries',
    'tiger_motors_dt.simulation.queries.car_queries',
    'tiger_motors_dt.simulation.queries.metrics_queries',

    # Interfaces (CLI + GUI)
    'tiger_motors_dt.interfaces',
    'tiger_motors_dt.interfaces.cli',
    'tiger_motors_dt.interfaces.cli.cli_interface',
    'tiger_motors_dt.interfaces.gui',
    'tiger_motors_dt.interfaces.gui.main_window',
    'tiger_motors_dt.interfaces.gui.controllers',
    'tiger_motors_dt.interfaces.gui.controllers.simulation_controller',
    'tiger_motors_dt.interfaces.gui.managers',
    'tiger_motors_dt.interfaces.gui.managers.display_manager',
    'tiger_motors_dt.interfaces.gui.managers.tab_manager',
    'tiger_motors_dt.interfaces.gui.managers.tabs',
    'tiger_motors_dt.interfaces.gui.managers.tabs.production_tab',
    'tiger_motors_dt.interfaces.gui.managers.tabs.cars_tab',
    'tiger_motors_dt.interfaces.gui.managers.tabs.finished_cars_tab',
    'tiger_motors_dt.interfaces.gui.managers.tabs.llm_chat_tab',
    'tiger_motors_dt.interfaces.gui.managers.tabs.barcode_service_tab',
    'tiger_motors_dt.interfaces.gui.managers.tabs.agent_inspector_tab',

    # Services
    'tiger_motors_dt.services',
    'tiger_motors_dt.services.barcode_scanner_service',
    'tiger_motors_dt.services.opc_ua_bridge_service',

    # Widgets
    'tiger_motors_dt.widgets',
    'tiger_motors_dt.widgets.worker',
    'tiger_motors_dt.widgets.state_pie_chart',
    'tiger_motors_dt.widgets.workstation_card',
    'tiger_motors_dt.widgets.inspection_station_card',
    'tiger_motors_dt.widgets.car_tracking_widget',
    'tiger_motors_dt.widgets.finished_car_tracking_widget',
    'tiger_motors_dt.widgets.production_control_widget',
    'tiger_motors_dt.widgets.barcode_service_widget',
    'tiger_motors_dt.widgets.agent_inspector_widget',
    'tiger_motors_dt.widgets.opc_service_status_widget',
    'tiger_motors_dt.widgets.llm_chat_widget',

    # RAG (deployment-specific)
    'tiger_motors_dt.rag_system',
    'tiger_motors_dt.rag_system.digital_twin_context_builder',
    'tiger_motors_dt.rag_system.digital_twin_context_formatter',
    'tiger_motors_dt.rag_system.digital_twin_data_collector',
    'tiger_motors_dt.rag_system.digital_twin_rag_system',

    # LLM service (optional sidecar)
    'tiger_motors_dt.llm_service',
    'tiger_motors_dt.llm_service.tiger_llm_service',
    'tiger_motors_dt.llm_service.tiger_prompt',

    # Tools
    'tiger_motors_dt.tools',
    'tiger_motors_dt.tools.data_generator',

    # ---- third-party libraries the engine depends on ----
    'transitions',
    'transitions.core',
    'transitions.extensions',
    'transitions.extensions.states',

    # GUI framework
    'PySide6',
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtWidgets',
    'PySide6.QtNetwork',
    'PySide6.QtPrintSupport',
    'shiboken6',

    # Messaging
    'paho.mqtt',
    'paho.mqtt.client',

    # PLC bridge (optional)
    'opcua',
    'opcua.client',
    'opcua.common',
    'opcua.common.subscription',

    # Service auxiliaries
    'openpyxl',
    'openpyxl.utils',
    'openpyxl.styles',
    'openpyxl.worksheet',
    'openpyxl.workbook',
    'zeroconf',

    # Plotting (workstation pie charts)
    'matplotlib',
    'matplotlib.pyplot',
    'matplotlib.backends',
    'matplotlib.backends.backend_qtagg',
    'matplotlib.backends.backend_qt5agg',
    'numpy',

    # System utilities
    'psutil',
    'socket',
    'threading',
    'queue',
    'json',
    'datetime',
    'uuid',
    'logging',
]

# ==============================================================================
# EXCLUDED MODULES — reduce binary size
# ==============================================================================
excludes = [
    # Test + lint tooling
    'pytest',
    'pytest_cov',
    'pytest_timeout',
    'unittest',
    'test',
    'tests',
    'black',
    'isort',
    'ruff',
    'pylint',
    'mypy',

    # Jupyter
    'jupyter',
    'jupyter_client',
    'jupyter_core',
    'notebook',

    # Docs
    'sphinx',
    'docutils',

    # Alternative GUI frameworks
    'tkinter',
    'PyQt5',
    'PyQt6',
    'wx',

    # Unused matplotlib backends
    'matplotlib.backends.backend_gtk3',
    'matplotlib.backends.backend_gtk4',
    'matplotlib.backends.backend_wx',
    'matplotlib.backends.backend_tkagg',

    # PIL tkinter support
    'PIL.ImageTk',
]

# ==============================================================================
# ANALYSIS — entry point and dependency graph
# ==============================================================================
a = Analysis(
    [os.path.join(repo_root, 'gui_main.py')],
    pathex=[repo_root],
    binaries=pyside6_binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='TigerMotorsDT',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='TigerMotorsDT',
)

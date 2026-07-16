Tiger Motors Digital Twin - Standalone Edition
================================================

This folder contains a portable Windows distribution of the Tiger
Motors Digital Twin application. No Python install is needed on the
target machine.


Contents
--------

  TigerMotorsDT.exe              The GUI application
  config.json                    Edit this to point at your MQTT broker
  config_template.json           Reference template if config.json is missing
  llm_service\                   LLM service config + template
  diagrams_and_data\             Excel log output destination (created
                                 automatically by the barcode scanner service)
  create_shortcut.vbs            Run once to drop a desktop shortcut
  version.txt                    Build metadata (Python version, commit SHA)
  README_STANDALONE.txt          This file


First run
---------

1. Edit config.json
   Open in any text editor and set:
     - mqtt.host          The MQTT broker IP (or "localhost" if running
                          mosquitto on this machine).
     - mqtt.port          1883 plaintext, 8883 TLS.
     - facility.*         Number of cells / workstations if different
                          from the default (3 cells x 5 WS = 15).

   If config.json is missing or corrupted, the application will fall
   back to localhost defaults and warn in the status bar.

2. Optional: create a desktop shortcut
   Double-click create_shortcut.vbs. The shortcut shows up on the
   current user's desktop as "Tiger Motors Digital Twin".

3. Launch the application
   Double-click TigerMotorsDT.exe (or the desktop shortcut).
   The GUI opens; the status bar will report "Initializing...",
   then "Ready" once the simulation environment is up.


Production workflow
-------------------

1. Make sure the MQTT broker is running and reachable from this
   machine. The status bar will show "Disconnected" if not.
2. Click "Start Production" in the Production Monitor tab. Workstation
   cards turn green and start tracking Andon state. Scanner messages
   begin to drive car agents.
3. Watch the Active Cars and Finished Cars tables fill in as cars
   move through the line.
4. Click "Stop Production" when done. Cars freeze in place; nothing
   new is created.


LLM-assisted chat
-----------------

If a local Ollama instance is running, the LLM Chat tab will send
natural-language queries about the current production state. Edit
llm_service\llm_service_config.json to point at your Ollama host/port
and model. Default is localhost:11434.


Diagrams and Excel logs
-----------------------

The barcode scanner service logs every scan event to an Excel file in
diagrams_and_data\. Files are timestamped; the service appends new
sheets per production cycle.


Troubleshooting
---------------

- Application opens but shows "Disconnected":
  MQTT broker is not reachable. Check config.json and that the broker
  IP responds to a `mosquitto_sub -h <ip> -t '#'` from this machine.

- Workstation cards stay gray ("OFFLINE"):
  The simulation environment didn't finish initializing. Check the
  console (run TigerMotorsDT.exe from cmd.exe to see logs) for error
  messages.

- LLM Chat tab is missing or grayed out:
  The Ollama Python package isn't bundled (optional). The rest of the
  application works fine without it.

- Crashes or hangs on startup:
  Send version.txt plus any console output to the development team —
  the git SHA in version.txt pins the source revision.


Where to get a new build
------------------------

The application's source lives in the MABDT-Engine repository.
To produce a fresh dist\TigerMotorsDT\ folder from a checkout, run
build_standalone.bat at the repo root (see QUICK_START_BUILDING.txt
for the full procedure).

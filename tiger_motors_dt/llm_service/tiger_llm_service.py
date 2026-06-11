#!/usr/bin/env python3
"""Tiger Motors LLM service (separate process per JIM §3.4 C52).

Run as either:
  python tiger_motors_dt/llm_service/tiger_llm_service.py
  python -m tiger_motors_dt.llm_service.tiger_llm_service

The sys.path bootstrap below makes the first form work even without
`pip install -e .`, so this file is portable as a copy-and-run sidecar.
"""

import argparse
import json
import logging
import logging.handlers
import os
import signal
import sys
import time
from typing import Any

# Bootstrap: ensure the repo root is on sys.path so `mabdt` and the
# absolute tiger_motors_dt.* imports below resolve regardless of cwd
# or whether the package is installed editably.
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, os.pardir, os.pardir))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

try:
    import ollama
except ImportError:
    print(
        "ERROR: the 'ollama' package is required for the LLM service.\n"
        "Install it with one of:\n"
        "    pip install ollama\n"
        '    pip install -e ".[llm]"        # from the repo root\n'
        '    pip install -e ".[tiger]"      # full Tiger Motors deployment',
        file=sys.stderr,
    )
    sys.exit(1)

import paho.mqtt.client as mqtt

from tiger_motors_dt.llm_service.tiger_prompt import TigerMotorsPrompt


class TigerLLMService:
    """Consolidated Tiger Motors LLM Service - All-in-one standalone service"""

    # Built-in default configuration
    DEFAULT_CONFIG = {
        "mqtt": {
            "host": "localhost",
            "port": 1883,
            "topics": {"question": "llm/question", "answer": "llm/answer"},
        },
        "ollama": {"model": "qwen3:4b", "host": "localhost", "port": 11434, "temperature": 0.7},
        "service": {"name": "Tiger Motors LLM Service", "log_level": "INFO"},
        "tiger_motors": {
            "enable_rag": True,
            "max_response_length": 2048,
            "remove_think_tags": True,
        },
    }

    def __init__(self, config_file: str | None = None):
        """Initialize service with optional configuration file"""
        self.config = self._load_configuration(config_file)
        self.logger = self._setup_logging()
        self.mqtt_client = None
        self.running = False
        self.prompt_manager = TigerMotorsPrompt()

        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        self.logger.info(f"Initialized {self.config['service']['name']}")

    def _load_configuration(self, config_file: str | None) -> dict[str, Any]:
        """Load configuration from file or use defaults"""
        config = self.DEFAULT_CONFIG.copy()

        # If no config file specified, try to find default config file
        if config_file is None:
            # Try to find config file in current directory or script directory
            possible_configs = [
                "llm_service_config.json",
                os.path.join(os.path.dirname(__file__), "llm_service_config.json"),
            ]

            for possible_config in possible_configs:
                if os.path.exists(possible_config):
                    config_file = possible_config
                    break

        if config_file and os.path.exists(config_file):
            try:
                with open(config_file) as f:
                    file_config = json.load(f)
                    self._merge_config(config, file_config)
                print(f"Configuration loaded from {config_file}")
            except Exception as e:
                print(f"Warning: Could not load config file {config_file}: {e}")
        else:
            print("No configuration file found, using default settings")

        return config

    def _merge_config(self, default: dict, override: dict) -> None:
        """Recursively merge configuration dictionaries"""
        for key, value in override.items():
            if key in default and isinstance(default[key], dict) and isinstance(value, dict):
                self._merge_config(default[key], value)
            else:
                default[key] = value

    def _setup_logging(self) -> logging.Logger:
        """Setup logging with rotation and Unicode support"""
        logger = logging.getLogger("tiger_llm_service")
        logger.handlers.clear()

        log_level = getattr(logging, self.config["service"]["log_level"].upper())
        logger.setLevel(log_level)

        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        )

        # Console handler with UTF-8 encoding support
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        # Fix Unicode issues on Windows by setting encoding
        if hasattr(console_handler.stream, "reconfigure"):
            try:
                console_handler.stream.reconfigure(encoding="utf-8")
            except (AttributeError, OSError):
                pass  # Fall back to default encoding
        logger.addHandler(console_handler)

        # File handler with rotation and UTF-8 encoding
        file_handler = logging.handlers.RotatingFileHandler(
            "llm_service.log", maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

        return logger

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully"""
        self.logger.info(f"Received signal {signum}, shutting down...")
        self.stop()

    def _setup_mqtt(self) -> mqtt.Client:
        """Setup MQTT client with callbacks"""
        client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION1)
        client.on_connect = self._on_mqtt_connect
        client.on_message = self._on_mqtt_message
        client.on_disconnect = self._on_mqtt_disconnect
        return client

    def _on_mqtt_connect(self, client, userdata, flags, rc):
        """MQTT connection callback (VERSION1 API)"""
        if rc == 0:
            question_topic = self.config["mqtt"]["topics"]["question"]
            client.subscribe(question_topic)
            self.logger.info(f"Connected to MQTT, subscribed to {question_topic}")
        else:
            self.logger.error(f"MQTT connection failed with code {rc}")

    def _on_mqtt_disconnect(self, client, userdata, rc):
        """MQTT disconnection callback (VERSION1 API)"""
        if rc != 0:
            self.logger.warning("Unexpected MQTT disconnection")

    def _on_mqtt_message(self, client, userdata, msg):
        """Process incoming questions"""
        try:
            # Parse the question (like working example)
            data = json.loads(msg.payload.decode())
            question = data["question"]
            user_id = data["user_id"]
            rag_context = data.get("rag_context", "")

            self.logger.info(f"Question from {user_id}: {question[:100]}...")

            # Process and respond
            answer = self._process_question(question, rag_context)
            self._send_answer(user_id, question, answer)

        except Exception as e:
            self.logger.error(f"Error processing message: {e}")
            self._send_error_response(str(e))

    def _process_question(self, question: str, rag_context: str | None = None) -> str:
        """Process question using Ollama with optional RAG context"""
        try:
            # Always use Tiger Motors prompt system
            if self.config["tiger_motors"]["enable_rag"] and rag_context:
                prompt = self.prompt_manager.create_contextualized_prompt(question, rag_context)
                self.logger.info(
                    f"Processing question with RAG context (length: {len(rag_context)})"
                )
            else:
                # Even without RAG, use the Tiger Motors system prompt
                prompt = self.prompt_manager.create_prompt(question)
                self.logger.info("Processing question with standard Tiger Motors prompt")

            # Call Ollama using generate (like working example)
            response = ollama.generate(model=self.config["ollama"]["model"], prompt=prompt)

            # Get raw answer
            raw_answer = response["response"]

            # Apply response filtering
            if self.config["tiger_motors"]["remove_think_tags"]:
                answer = self.prompt_manager.filter_response(raw_answer)
                self.logger.info(
                    f"Filtered response. Original: {len(raw_answer)} chars, Filtered: {len(answer)} chars"
                )
            else:
                answer = raw_answer

            # Truncate if needed
            max_length = self.config["tiger_motors"]["max_response_length"]
            if len(answer) > max_length:
                answer = answer[:max_length] + "... [truncated]"

            return answer

        except Exception as e:
            self.logger.error(f"Error processing question: {e}")
            return f"Sorry, I encountered an error processing your question: {str(e)}"

    def _send_answer(self, user_id: str, question: str, answer: str):
        """Send answer via MQTT"""
        try:
            response_data = {
                "user_id": user_id,
                "question": question,
                "answer": answer,
                "timestamp": time.time(),
                "service": self.config["service"]["name"],
            }

            answer_topic = self.config["mqtt"]["topics"]["answer"]
            self.mqtt_client.publish(answer_topic, json.dumps(response_data))
            self.logger.info(f"Sent answer to {user_id}")

        except Exception as e:
            self.logger.error(f"Error sending answer: {e}")

    def _send_error_response(self, error: str):
        """Send error response"""
        try:
            error_data = {
                "error": error,
                "timestamp": time.time(),
                "service": self.config["service"]["name"],
            }
            answer_topic = self.config["mqtt"]["topics"]["answer"]
            self.mqtt_client.publish(answer_topic, json.dumps(error_data))
        except Exception as e:
            self.logger.error(f"Error sending error response: {e}")

    def _test_connections(self) -> bool:
        """Test Ollama and MQTT connections"""
        # Test Ollama
        try:
            ollama.list()
            self.logger.info("Ollama connection successful")
        except Exception as e:
            self.logger.error(f"Ollama connection failed: {e}")
            return False

        return True

    def start(self):
        """Start the LLM service"""
        if not self._test_connections():
            return False

        # Setup MQTT
        self.mqtt_client = self._setup_mqtt()

        try:
            mqtt_config = self.config["mqtt"]
            self.logger.info(f"Connecting to {mqtt_config['host']}:{mqtt_config['port']}...")
            self.mqtt_client.connect(mqtt_config["host"], mqtt_config["port"], 60)
            self.running = True

            self.logger.info("Tiger Motors LLM Service started successfully")
            self.mqtt_client.loop_forever()

        except Exception as e:
            self.logger.error(f"Failed to start service: {e}")
            return False

    def stop(self):
        """Stop the service gracefully"""
        self.running = False
        if self.mqtt_client:
            self.mqtt_client.disconnect()
        self.logger.info("Service stopped")


def create_sample_config(filename: str = "llm_service_config.json"):
    """Create a sample configuration file"""
    config = TigerLLMService.DEFAULT_CONFIG.copy()
    try:
        with open(filename, "w") as f:
            json.dump(config, f, indent=4)
        print(f"Sample configuration created: {filename}")
    except Exception as e:
        print(f"Error creating config: {e}")


def setup_cli() -> argparse.ArgumentParser:
    """Setup command line interface"""
    parser = argparse.ArgumentParser(
        prog="tiger-llm-service", description="Tiger Motors Digital Twin LLM Service"
    )

    parser.add_argument("-c", "--config", help="Configuration file path")
    parser.add_argument("--create-config", action="store_true", help="Create sample config file")
    parser.add_argument("--model", help="Override Ollama model")
    parser.add_argument("--mqtt-host", help="Override MQTT host")
    parser.add_argument("--mqtt-port", type=int, help="Override MQTT port")
    parser.add_argument(
        "--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="Set log level"
    )
    parser.add_argument("--dry-run", action="store_true", help="Test configuration only")

    return parser


def apply_cli_overrides(service: TigerLLMService, args: argparse.Namespace):
    """Apply command line overrides to service configuration"""
    if args.model:
        service.config["ollama"]["model"] = args.model
    if args.mqtt_host:
        service.config["mqtt"]["host"] = args.mqtt_host
    if args.mqtt_port:
        service.config["mqtt"]["port"] = args.mqtt_port
    if args.log_level:
        service.config["service"]["log_level"] = args.log_level


def main():
    """Main entry point with CLI support"""
    parser = setup_cli()
    args = parser.parse_args()

    # Handle special commands
    if args.create_config:
        create_sample_config()
        return

    # Create and configure service
    service = TigerLLMService(config_file=args.config)
    apply_cli_overrides(service, args)

    # Dry run mode
    if args.dry_run:
        print("Configuration loaded successfully")
        print("Service initialized without errors")
        return

    # Start service
    try:
        service.start()
    except KeyboardInterrupt:
        print("\nShutting down...")
        service.stop()


if __name__ == "__main__":
    main()

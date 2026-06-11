# cli_main.py (~20 lines)
from tiger_motors_dt.interfaces.cli.cli_interface import CLIInterface

def main():
    try:
        cli = CLIInterface()
        cli.run()
    except KeyboardInterrupt:
        print("\nShutting down...")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()

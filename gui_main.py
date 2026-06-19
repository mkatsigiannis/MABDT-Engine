import sys

from PySide6.QtWidgets import QApplication

from tiger_motors_dt.interfaces.gui.main_window import TigerMotorsDTGUI


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Tiger Motors Digital Twin")

    window = TigerMotorsDTGUI()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()

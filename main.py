import sys
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication
from app.database.db import Database
from app.ui.main_window import MainWindow


def main():
    data_dir = Path.home() / "AITradingJournal"
    data_dir.mkdir(exist_ok=True)
    app = QApplication(sys.argv)
    app.setLayoutDirection(Qt.RightToLeft)
    app.setFont(QFont("Segoe UI", 10))
    win = MainWindow(Database(data_dir / "journal.db"), data_dir / "images", data_dir)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

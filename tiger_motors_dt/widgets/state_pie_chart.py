"""Matplotlib-backed pie chart for workstation state-time visualization."""

import matplotlib
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

matplotlib.use("Qt5Agg")  # Qt5 backend for PySide6 compatibility


class StatePieChart(FigureCanvas):
    """Embedded pie chart of time spent in each workstation state."""

    def __init__(self, parent=None, width=2, height=2, dpi=50):
        self.fig = Figure(figsize=(width, height), dpi=dpi, facecolor="white")
        super().__init__(self.fig)
        self.setParent(parent)

        self.axes = self.fig.add_subplot(111)
        self.axes.set_aspect("equal")

        self.update_chart(0, 0, 0, 0)

    def update_chart(self, idle_time, busy_time, yellow_time, red_time):
        """Redraw the pie chart with the four state durations."""
        self.axes.clear()

        total_time = idle_time + busy_time + yellow_time + red_time

        if total_time == 0:
            self.axes.text(
                0.5,
                0.5,
                "No Data",
                transform=self.axes.transAxes,
                ha="center",
                va="center",
                fontsize=8,
            )
            self.axes.set_xlim(-1, 1)
            self.axes.set_ylim(-1, 1)
        else:
            times = [idle_time, busy_time, yellow_time, red_time]
            labels = ["Idle", "Busy", "Yellow", "Red"]
            colors = ["#90EE90", "#4169E1", "#FFD700", "#FF6347"]

            filtered_data = [
                (t, label, color)
                for t, label, color in zip(times, labels, colors, strict=False)
                if t > 0
            ]

            if filtered_data:
                times_filtered, labels_filtered, colors_filtered = zip(*filtered_data, strict=False)

                wedges, texts, autotexts = self.axes.pie(
                    times_filtered,
                    labels=labels_filtered,
                    colors=colors_filtered,
                    autopct=lambda pct: f"{pct:.1f}%" if pct > 5 else "",
                    startangle=90,
                    textprops={"fontsize": 6},
                    pctdistance=0.85,
                )

                for text in texts:
                    text.set_fontsize(6)
                for autotext in autotexts:
                    autotext.set_color("white")
                    autotext.set_fontweight("bold")
                    autotext.set_fontsize(5)

        self.axes.set_xticks([])
        self.axes.set_yticks([])
        self.axes.axis("off")

        self.draw()

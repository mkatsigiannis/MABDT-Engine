"""Reshapes raw Digital Twin snapshots into structured per-domain summaries."""

from datetime import datetime
from typing import Any


class DigitalTwinContextFormatter:
    """Bucketizes raw collector output into the per-domain summaries the builder consumes."""

    def __init__(self):
        """Initialize the context formatter."""
        pass

    def format_workstation_summary(
        self, workstation_data: dict[str, dict[str, Any]]
    ) -> dict[str, Any]:
        """
        Format workstation data into a structured summary.

        Args:
            workstation_data: Raw workstation data from collector

        Returns:
            Formatted workstation summary
        """
        if not workstation_data:
            return {
                "total_workstations": 0,
                "by_state": {},
                "performance_summary": "No workstation data available",
                "performance_issues": [],
                "high_performers": [],
                "details": [],
            }

        # Group workstations by current state
        by_state = {}
        performance_issues = []
        high_performers = []

        for ws_id, data in workstation_data.items():
            state = data["current_state"]

            # Group by state
            if state not in by_state:
                by_state[state] = []
            by_state[state].append(ws_id)

            # Analyze performance
            red_pct = data.get("red_percentage", 0)
            yellow_pct = data.get("yellow_percentage", 0)
            busy_pct = data.get("busy_percentage", 0)

            if red_pct > 10:  # More than 10% in red state
                performance_issues.append(f"{ws_id} (Red: {red_pct:.1f}%)")
            elif yellow_pct > 20:  # More than 20% in yellow state
                performance_issues.append(f"{ws_id} (Yellow: {yellow_pct:.1f}%)")
            elif busy_pct > 70:  # High utilization
                high_performers.append(f"{ws_id} (Busy: {busy_pct:.1f}%)")

        # Create performance summary
        performance_summary = []
        if performance_issues:
            performance_summary.append(f"Issues: {', '.join(performance_issues)}")
        if high_performers:
            performance_summary.append(f"High utilization: {', '.join(high_performers)}")
        if not performance_summary:
            performance_summary.append("All workstations operating normally")

        return {
            "total_workstations": len(workstation_data),
            "by_state": by_state,
            "performance_summary": "; ".join(performance_summary),
            "performance_issues": performance_issues,
            "high_performers": high_performers,
            "details": [
                {
                    "id": ws_id,
                    "state": data["current_state"],
                    "idle_pct": data.get("idle_percentage", 0),
                    "busy_pct": data.get("busy_percentage", 0),
                    "yellow_pct": data.get("yellow_percentage", 0),
                    "red_pct": data.get("red_percentage", 0),
                }
                for ws_id, data in workstation_data.items()
            ],
        }

    def format_car_summary(self, car_data: dict[str, dict[str, Any]]) -> dict[str, Any]:
        """
        Format car data into a structured summary with proper categorization.

        Args:
            car_data: Raw car data from collector

        Returns:
            Formatted car summary with active, inspection, and finished cars separated
        """
        if not car_data:
            return {
                "total_cars": 0,
                "active_cars": 0,
                "inspection_cars": 0,
                "finished_cars": 0,
                "unknown_cars": 0,
                "by_location": {},
                "by_state": {},
                "by_category": {},
                "quality_summary": "No cars in system",
                "total_faults": 0,
                "cars_with_faults": 0,
                "fault_rate_percent": 0,
                "average_faults_per_car": 0,
                "details": [],
            }

        # Initialize categorization
        by_location = {}
        by_state = {}
        by_category = {"active": [], "inspection": [], "finished": [], "unknown": []}
        total_faults = 0
        cars_with_faults = 0

        for car_id, data in car_data.items():
            workstation = data.get("current_workstation")
            state = data.get("current_state", "Unknown")
            category = data.get("category", "unknown")
            fault_count = data.get("total_faults", 0)

            # Group by workstation
            location_key = f"WS{workstation}" if workstation else "Unknown"
            if location_key not in by_location:
                by_location[location_key] = []
            by_location[location_key].append(car_id)

            # Group by state
            if state not in by_state:
                by_state[state] = []
            by_state[state].append(car_id)

            # Group by category (NEW)
            if category in by_category:
                by_category[category].append(car_id)
            else:
                by_category["unknown"].append(car_id)

            # Count faults
            total_faults += fault_count
            if fault_count > 0:
                cars_with_faults += 1

        # Count cars by category
        active_count = len(by_category["active"])
        inspection_count = len(by_category["inspection"])
        finished_count = len(by_category["finished"])
        unknown_count = len(by_category["unknown"])

        # Create enhanced quality summary
        total_cars = len(car_data)
        fault_rate = (cars_with_faults / total_cars * 100) if total_cars > 0 else 0
        avg_faults = (total_faults / total_cars) if total_cars > 0 else 0

        # Create detailed status summary
        status_parts = []
        if active_count > 0:
            status_parts.append(f"{active_count} active in production")
        if inspection_count > 0:
            status_parts.append(f"{inspection_count} under inspection")
        if finished_count > 0:
            status_parts.append(f"{finished_count} completed")
        if unknown_count > 0:
            status_parts.append(f"{unknown_count} unknown status")

        quality_summary = f"Total: {total_cars} cars ({', '.join(status_parts)}), {cars_with_faults} with faults ({fault_rate:.1f}% fault rate), avg {avg_faults:.1f} faults per car"

        return {
            "total_cars": total_cars,
            "active_cars": active_count,
            "inspection_cars": inspection_count,
            "finished_cars": finished_count,
            "unknown_cars": unknown_count,
            "by_location": by_location,
            "by_state": by_state,
            "by_category": by_category,
            "quality_summary": quality_summary,
            "total_faults": total_faults,
            "cars_with_faults": cars_with_faults,
            "fault_rate_percent": fault_rate,
            "average_faults_per_car": avg_faults,
            "details": [
                {
                    "id": car_id,
                    "workstation": data.get("current_workstation"),
                    "state": data.get("current_state"),
                    "category": data.get("category", "unknown"),
                    "time_in_system": data.get("time_in_system"),
                    "total_faults": data.get("total_faults", 0),
                    "production_faults": data.get("production_faults", []),
                    "inspection_faults": data.get("inspection_faults", []),
                }
                for car_id, data in car_data.items()
            ],
        }

    def format_production_metrics(self, metrics_data: dict[str, Any]) -> dict[str, Any]:
        """
        Format production metrics into a structured summary with enhanced car categorization.

        Args:
            metrics_data: Raw metrics data from collector

        Returns:
            Formatted production metrics with detailed car counts
        """
        formatted_metrics = {
            "system_status": "Unknown",
            "production_tracking": metrics_data.get("tracking_production", False),
            "targets": {},
            "current_performance": {},
            "car_breakdown": {},
            "summary": "No production metrics available",
        }

        # System status
        if metrics_data.get("tracking_production"):
            formatted_metrics["system_status"] = "Production Active"
        else:
            formatted_metrics["system_status"] = "Production Stopped"

        # Targets
        formatted_metrics["targets"] = {
            "takt_time": metrics_data.get("target_takt_time", 75),
            "cycle_time": metrics_data.get("target_cycle_time", 60),
        }

        # Current performance with detailed car breakdown
        formatted_metrics["current_performance"] = {
            "total_workstations": metrics_data.get("total_workstations", 0),
            "total_cars_in_system": metrics_data.get("total_cars_in_system", 0),
        }

        # Enhanced car breakdown
        formatted_metrics["car_breakdown"] = {
            "active_cars": metrics_data.get("active_cars", 0),
            "inspection_cars": metrics_data.get("inspection_cars", 0),
            "finished_cars": metrics_data.get("finished_cars", 0),
            "unknown_cars": metrics_data.get("unknown_cars", 0),
        }

        # Create enhanced summary
        status = formatted_metrics["system_status"]
        ws_count = formatted_metrics["current_performance"]["total_workstations"]
        total_cars = formatted_metrics["current_performance"]["total_cars_in_system"]
        active_cars = formatted_metrics["car_breakdown"]["active_cars"]
        inspection_cars = formatted_metrics["car_breakdown"]["inspection_cars"]
        finished_cars = formatted_metrics["car_breakdown"]["finished_cars"]

        car_details = []
        if active_cars > 0:
            car_details.append(f"{active_cars} in production")
        if inspection_cars > 0:
            car_details.append(f"{inspection_cars} under inspection")
        if finished_cars > 0:
            car_details.append(f"{finished_cars} completed")

        car_summary = f" ({', '.join(car_details)})" if car_details else ""

        formatted_metrics["summary"] = (
            f"{status}: {ws_count} workstations, {total_cars} total cars{car_summary}"
        )

        return formatted_metrics

    def format_comprehensive_summary(self, all_data: dict[str, Any]) -> dict[str, Any]:
        """
        Format all collected data into a comprehensive, structured summary.

        Args:
            all_data: Complete data from collector's collect_all_data()

        Returns:
            Comprehensive formatted summary ready for LLM consumption
        """
        timestamp = all_data.get("timestamp", datetime.now().isoformat())

        # Format each data type
        workstation_summary = self.format_workstation_summary(all_data.get("workstations", {}))
        car_summary = self.format_car_summary(all_data.get("cars", {}))
        metrics_summary = self.format_production_metrics(all_data.get("metrics", {}))

        # Create overall status
        overall_status = "System Status: "
        if metrics_summary["production_tracking"]:
            overall_status += f"ACTIVE - {workstation_summary['total_workstations']} workstations, {car_summary['total_cars']} cars in production"
        else:
            overall_status += "INACTIVE - Production tracking stopped"

        # Identify key insights
        key_insights = []

        # Production insights
        if workstation_summary["performance_issues"]:
            key_insights.append(
                f"Workstation issues detected: {', '.join(workstation_summary['performance_issues'])}"
            )

        if car_summary["fault_rate_percent"] > 20:
            key_insights.append(
                f"High fault rate: {car_summary['fault_rate_percent']:.1f}% of cars have faults"
            )

        if car_summary["total_cars"] == 0 and metrics_summary["production_tracking"]:
            key_insights.append("No cars in production - potential startup or completion scenario")

        if not key_insights:
            key_insights.append("Production operating normally with no major issues detected")

        return {
            "timestamp": timestamp,
            "overall_status": overall_status,
            "key_insights": key_insights,
            "workstations": workstation_summary,
            "cars": car_summary,
            "metrics": metrics_summary,
            "raw_data_available": {
                "workstation_count": len(all_data.get("workstations", {})),
                "car_count": len(all_data.get("cars", {})),
                "has_metrics": bool(all_data.get("metrics", {})),
            },
        }

    def create_quick_status(self, formatted_data: dict[str, Any]) -> str:
        """
        Create a quick, one-line status summary.

        Args:
            formatted_data: Output from format_comprehensive_summary()

        Returns:
            Quick status string
        """
        if not formatted_data:
            return "No data available"

        status = formatted_data.get("overall_status", "Unknown status")
        insights = formatted_data.get("key_insights", [])

        if insights:
            primary_insight = insights[0]
            return f"{status}. {primary_insight}"

        return status
